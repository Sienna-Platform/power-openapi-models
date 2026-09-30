//! Post-processes openapi-to-rust's `types.rs` and writes the crate's generated
//! sources. Each `fn` below fixes one generator defect and says which.
//!
//!   postprocess BUNDLE.json TYPES.rs OUT_DIR
//!
//! Writes OUT_DIR/generated.rs plus one OUT_DIR/<domain>.rs per SiennaSchemas spec.

use std::collections::{BTreeMap, BTreeSet};
use std::{env, fs, path::Path, process};

use proc_macro2::TokenStream;
use quote::{format_ident, quote};
use serde_json::Value;
use syn::punctuated::Punctuated;
use syn::{Fields, GenericArgument, Item, Meta, PathArguments, Token, Type};

type Schemas = BTreeMap<String, Value>;

fn die(message: String) -> ! {
    eprintln!("ERROR: {message}");
    process::exit(1);
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 4 {
        eprintln!("usage: postprocess BUNDLE.json TYPES.rs OUT_DIR");
        process::exit(2);
    }
    let bundle: Value = serde_json::from_str(&fs::read_to_string(&args[1]).expect("read bundle"))
        .expect("parse bundle");
    let schemas: Schemas = bundle["components"]["schemas"]
        .as_object()
        .expect("components.schemas")
        .iter()
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();
    let mut file: syn::File =
        syn::parse_str(&fs::read_to_string(&args[2]).expect("read types.rs")).expect("parse types.rs");

    let defaults = apply_schema_defaults(&mut file, &schemas);
    integer_enums(&mut file, &schemas);
    derive_partial_eq(&mut file);
    lenient_timestamps(&mut file);
    order_fields_like_schema(&mut file, &schemas);
    let idents = rust_idents(&file, &schemas);
    let out = Path::new(&args[3]);
    write_generated(out, &file, &defaults);
    write_domains(out, &bundle["x-domains"], &idents);
}

/// One defaulted field: the function that produces its default, and that
/// function's return type.
struct DefaultFn {
    name: String,
    ty: Type,
    struct_name: String,
    field: String,
    json: Value,
}

/// A property's own `default`, else, for a *required* property, the `default` its
/// `$ref` target declares. Python and TypeScript both resolve a type-level default
/// onto a required field of that type (`FuelCurve.vom_cost` has none of its own;
/// `InputOutputCurve` does) but not onto an optional one (`startup_fuel_offtake`
/// stays absent), so Rust must do exactly that or the same document loads
/// differently.
fn effective_default<'a>(
    property: &'a Value,
    required: bool,
    schemas: &'a Schemas,
) -> Option<&'a Value> {
    if let Some(default) = property.get("default") {
        return Some(default);
    }
    if !required {
        return None;
    }
    let target = property.get("$ref")?.as_str()?.rsplit('/').next()?;
    schemas.get(target)?.get("default")
}

/// DEFECT: openapi-to-rust does not honour a schema `default`.
///
/// * optional + default (`internal_voltage`, default 1.0) becomes `Option<T>`
///   and decodes to `None` when omitted, where Python materializes 1.0;
/// * required + default becomes either a required field with no default
///   (`CostCurve.vom_cost`: a document omitting it fails in Rust, loads in
///   Python) or `#[serde(default)]`, which is Rust's zero value, not the
///   schema's (`ac_setpoint`, default 1.0, would silently decode to 0.0).
///
/// A `default` declared on the referenced schema counts (see `effective_default`).
///
/// Every defaulted property becomes a plain `T` with
/// `#[serde(default = "defaults::<Struct>_<field>")]` returning the schema's
/// own value. Fails loudly if a defaulted property has no matching field, or is
/// nullable (none are today; an `Option` default would need its own decision).
fn apply_schema_defaults(file: &mut syn::File, schemas: &Schemas) -> Vec<DefaultFn> {
    let mut out = Vec::new();
    let mut seen: BTreeSet<(String, String)> = BTreeSet::new();
    for item in &mut file.items {
        let Item::Struct(item_struct) = item else { continue };
        let name = item_struct.ident.to_string();
        let Some(schema) = schemas.get(&name) else { continue };
        let Some(properties) = schema.get("properties").and_then(Value::as_object) else {
            continue;
        };
        let Fields::Named(fields) = &mut item_struct.fields else { continue };
        for field in &mut fields.named {
            let ident = field.ident.as_ref().expect("named field").to_string();
            let wire = serde_rename(&field.attrs).unwrap_or_else(|| ident.trim_start_matches("r#").to_string());
            let Some(default) = effective_default(&properties[&wire], is_required(schema, &wire), schemas)
            else {
                continue;
            };
            if default.is_null() {
                continue;
            }
            if is_nullable(&properties[&wire]) {
                die(format!("{name}.{wire}: nullable property with a non-null default"));
            }
            seen.insert((name.clone(), wire.clone()));
            let inner = unwrap_option(&field.ty);
            field.ty = inner.clone();
            let fn_name = format!("{name}_{}", ident.trim_start_matches("r#"));
            set_serde_default(&mut field.attrs, &format!("defaults::{fn_name}"));
            out.push(DefaultFn {
                name: fn_name,
                ty: inner,
                struct_name: name.clone(),
                field: wire,
                json: default.clone(),
            });
        }
    }
    for (name, schema) in schemas {
        let Some(properties) = schema.get("properties").and_then(Value::as_object) else {
            continue;
        };
        for (prop, value) in properties {
            let wants = matches!(
                effective_default(value, is_required(schema, prop), schemas),
                Some(d) if !d.is_null()
            );
            if wants && !seen.contains(&(name.clone(), prop.clone())) {
                die(format!("{name}.{prop} declares a default but no struct field was found for it"));
            }
        }
    }
    out
}

/// DEFECT: openapi-to-rust emits struct fields alphabetically, so a serialized
/// value's keys come out in a different order from the schema's `properties`,
/// which is the order pydantic and the TypeScript models write. Reordering makes
/// a document's typed rows read, then write, in the order the producer emitted.
/// Fields the schema does not list (none today) keep their place, last.
fn order_fields_like_schema(file: &mut syn::File, schemas: &Schemas) {
    for item in &mut file.items {
        let Item::Struct(item_struct) = item else { continue };
        let Some(schema) = schemas.get(&item_struct.ident.to_string()) else { continue };
        let Some(properties) = schema.get("properties").and_then(Value::as_object) else {
            continue;
        };
        let Fields::Named(fields) = &mut item_struct.fields else { continue };
        let position = |field: &syn::Field| {
            let ident = field.ident.as_ref().expect("named field").to_string();
            let wire = serde_rename(&field.attrs).unwrap_or_else(|| ident.trim_start_matches("r#").to_string());
            properties.keys().position(|k| *k == wire).unwrap_or(usize::MAX)
        };
        let mut ordered: Vec<syn::Field> = fields.named.iter().cloned().collect();
        ordered.sort_by_key(|f| position(f));
        fields.named = ordered.into_iter().collect();
    }
}

/// DEFECT: openapi-to-rust turns an integer `enum` into `pub type X = i64`, so
/// `curve_style: 5` is accepted where pydantic (an `IntEnum`) and zod (a union of
/// literals) reject it. Replaced by a real enum whose serde impls go through
/// `TryFrom<i64>`, which refuses any value the schema does not list.
fn integer_enums(file: &mut syn::File, schemas: &Schemas) {
    let mut items = Vec::with_capacity(file.items.len());
    for item in std::mem::take(&mut file.items) {
        let Item::Type(alias) = &item else {
            items.push(item);
            continue;
        };
        let name = alias.ident.to_string();
        let ints = match schemas.get(&name).filter(|s| s.get("type") == Some(&Value::from("integer"))) {
            Some(schema) => match schema.get("enum").and_then(Value::as_array) {
                Some(values) => values
                    .iter()
                    .map(|v| {
                        v.as_i64()
                            .unwrap_or_else(|| die(format!("{name}: non-integer enum value {v}")))
                    })
                    .collect::<Vec<i64>>(),
                None => {
                    items.push(item);
                    continue;
                }
            },
            None => {
                items.push(item);
                continue;
            }
        };
        let ident = format_ident!("{name}");
        let variants: Vec<syn::Ident> = ints
            .iter()
            .map(|v| {
                if *v < 0 {
                    format_ident!("VNeg{}", v.unsigned_abs())
                } else {
                    format_ident!("V{v}")
                }
            })
            .collect();
        let message = format!("{{other}} is not one of the values {name} allows");
        let tokens = quote! {
            #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, ::serde::Serialize, ::serde::Deserialize)]
            #[serde(try_from = "i64", into = "i64")]
            #[repr(i64)]
            pub enum #ident { #(#variants = #ints),* }

            impl From<#ident> for i64 {
                fn from(value: #ident) -> i64 {
                    value as i64
                }
            }

            impl TryFrom<i64> for #ident {
                type Error = String;

                fn try_from(value: i64) -> Result<Self, String> {
                    match value {
                        #(#ints => Ok(Self::#variants),)*
                        other => Err(format!(#message)),
                    }
                }
            }
        };
        let replacement: syn::File = syn::parse2(tokens).expect("integer enum");
        items.extend(replacement.items);
    }
    file.items = items;
}

/// DEFECT: a `format: date-time` field is `chrono::DateTime<Utc>`, which rejects a
/// timestamp with no offset. Real producers write `2024-01-01T00:00:00`, and the
/// Python and TypeScript packages accept it too (read as UTC), so every such field
/// is routed through the hand-written `crate::timestamp`. Fails loudly on a
/// `DateTime` in a shape this does not handle rather than leaving one field
/// stricter than the rest.
fn lenient_timestamps(file: &mut syn::File) {
    let datetime = "chrono :: DateTime < chrono :: Utc >";
    let text = |ty: &Type| quote!(#ty).to_string();
    let mut handled = 0;
    for item in &mut file.items {
        let Item::Struct(item_struct) = item else { continue };
        let Fields::Named(fields) = &mut item_struct.fields else { continue };
        for field in &mut fields.named {
            let ty = text(&field.ty);
            if !ty.contains("DateTime") {
                continue;
            }
            let name = format!("{}.{}", item_struct.ident, field.ident.as_ref().unwrap());
            if ty == datetime {
                field.attrs.push(syn::parse_quote!(#[serde(with = "crate::timestamp")]));
            } else if ty == format!("Option < {datetime} >") {
                field.attrs.push(syn::parse_quote!(#[serde(with = "crate::timestamp::option")]));
                if serde_default(&field.attrs).is_none() {
                    field.attrs.push(syn::parse_quote!(#[serde(default)]));
                }
            } else if ty == format!("Option < Option < {datetime} > >") {
                retarget_deserialize_with(&mut field.attrs, "crate::timestamp::deserialize_tri_state")
                    .unwrap_or_else(|| die(format!("{name}: tri-state field without deserialize_with")));
            } else {
                die(format!("{name}: unhandled date-time shape `{ty}`"));
            }
            handled += 1;
        }
    }
    let total = quote!(#file).to_string().matches(datetime).count();
    if total != handled {
        die(format!(
            "{total} date-time type(s) in the output but {handled} were routed through timestamp"
        ));
    }
}

/// The value of a field's serde `default`, or `Some("")` for a bare one.
fn serde_default(attrs: &[syn::Attribute]) -> Option<String> {
    for attr in attrs.iter().filter(|a| a.path().is_ident("serde")) {
        let Meta::List(list) = &attr.meta else { continue };
        let metas = list
            .parse_args_with(Punctuated::<Meta, Token![,]>::parse_terminated)
            .expect("parse serde attr");
        for meta in metas {
            match &meta {
                Meta::Path(p) if p.is_ident("default") => return Some(String::new()),
                Meta::NameValue(nv) if nv.path.is_ident("default") => return Some("set".into()),
                _ => {}
            }
        }
    }
    None
}

/// Rewrites the field's serde `deserialize_with` path; `None` if it had none.
fn retarget_deserialize_with(attrs: &mut [syn::Attribute], path: &str) -> Option<()> {
    for attr in attrs.iter_mut().filter(|a| a.path().is_ident("serde")) {
        let Meta::List(list) = &attr.meta else { continue };
        let metas: Vec<Meta> = list
            .parse_args_with(Punctuated::<Meta, Token![,]>::parse_terminated)
            .expect("parse serde attr")
            .into_iter()
            .collect();
        if !metas.iter().any(|m| m.path().is_ident("deserialize_with")) {
            continue;
        }
        let rewritten: Vec<Meta> = metas
            .into_iter()
            .map(|m| {
                if m.path().is_ident("deserialize_with") {
                    syn::parse_quote!(deserialize_with = #path)
                } else {
                    m
                }
            })
            .collect();
        *attr = syn::parse_quote!(#[serde(#(#rewritten),*)]);
        return Some(());
    }
    None
}

/// DEFECT: openapi-to-rust derives `PartialEq` on enums but not on structs, so
/// two decoded values cannot be compared. Python and TypeScript models compare by
/// value; a Rust model that cannot is a surface gap, and a document type built
/// from these rows could not derive it either.
fn derive_partial_eq(file: &mut syn::File) {
    for item in &mut file.items {
        let attrs = match item {
            Item::Struct(i) => &mut i.attrs,
            Item::Enum(i) => &mut i.attrs,
            _ => continue,
        };
        let Some(derive) = attrs.iter_mut().find(|a| a.path().is_ident("derive")) else {
            continue;
        };
        let Meta::List(list) = &derive.meta else { continue };
        let mut paths = list
            .parse_args_with(Punctuated::<syn::Path, Token![,]>::parse_terminated)
            .expect("parse derive");
        if paths.iter().any(|p| p.is_ident("PartialEq")) {
            continue;
        }
        paths.push(syn::parse_quote!(PartialEq));
        *derive = syn::parse_quote!(#[derive(#paths)]);
    }
}

fn is_required(schema: &Value, property: &str) -> bool {
    schema
        .get("required")
        .and_then(Value::as_array)
        .is_some_and(|r| r.iter().any(|x| x == property))
}

fn is_nullable(property: &Value) -> bool {
    let typed = property.get("type").and_then(Value::as_array);
    typed.is_some_and(|t| t.iter().any(|x| x == "null"))
        || property
            .get("anyOf")
            .and_then(Value::as_array)
            .is_some_and(|a| a.iter().any(|x| x.get("type") == Some(&Value::from("null"))))
}

fn unwrap_option(ty: &Type) -> Type {
    if let Type::Path(path) = ty {
        if let Some(segment) = path.path.segments.last() {
            if segment.ident == "Option" {
                if let PathArguments::AngleBracketed(args) = &segment.arguments {
                    if let Some(GenericArgument::Type(inner)) = args.args.first() {
                        return inner.clone();
                    }
                }
            }
        }
    }
    ty.clone()
}

fn serde_rename(attrs: &[syn::Attribute]) -> Option<String> {
    for attr in attrs.iter().filter(|a| a.path().is_ident("serde")) {
        let Meta::List(list) = &attr.meta else { continue };
        let metas = list
            .parse_args_with(Punctuated::<Meta, Token![,]>::parse_terminated)
            .expect("parse serde attr");
        for meta in metas {
            if let Meta::NameValue(nv) = &meta {
                if nv.path.is_ident("rename") {
                    if let syn::Expr::Lit(syn::ExprLit { lit: syn::Lit::Str(s), .. }) = &nv.value {
                        return Some(s.value());
                    }
                }
            }
        }
    }
    None
}

/// Replaces the field's `default` and `skip_serializing_if` serde items (the
/// latter would drop the now-always-present value) with `default = "path"`,
/// keeping every other item, e.g. `rename`.
fn set_serde_default(attrs: &mut Vec<syn::Attribute>, path: &str) {
    let mut kept: Vec<Meta> = Vec::new();
    attrs.retain(|attr| {
        if !attr.path().is_ident("serde") {
            return true;
        }
        let Meta::List(list) = &attr.meta else { return true };
        let metas = list
            .parse_args_with(Punctuated::<Meta, Token![,]>::parse_terminated)
            .expect("parse serde attr");
        for meta in metas {
            if meta.path().is_ident("default") || meta.path().is_ident("skip_serializing_if") {
                continue;
            }
            kept.push(meta);
        }
        false
    });
    let attr: syn::Attribute = syn::parse_quote!(#[serde(#(#kept,)* default = #path)]);
    attrs.push(attr);
}

/// The Rust identifier openapi-to-rust gave each schema. Usually the schema name
/// itself; `FromTo_ToFrom` and `XY_Coords` are re-cased. Matching ignores
/// punctuation and case and fails loudly unless exactly one type matches.
fn rust_idents(file: &syn::File, schemas: &Schemas) -> BTreeMap<String, String> {
    let squash = |s: &str| s.chars().filter(|c| c.is_alphanumeric()).collect::<String>().to_lowercase();
    let mut types: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut exact: BTreeSet<String> = BTreeSet::new();
    for item in &file.items {
        let name = match item {
            Item::Struct(i) => i.ident.to_string(),
            Item::Enum(i) => i.ident.to_string(),
            Item::Type(i) => i.ident.to_string(),
            _ => continue,
        };
        exact.insert(name.clone());
        types.entry(squash(&name)).or_default().push(name);
    }
    let mut out = BTreeMap::new();
    for name in schemas.keys() {
        if exact.contains(name) {
            out.insert(name.clone(), name.clone());
            continue;
        }
        match types.get(&squash(name)).map(Vec::as_slice) {
            Some([one]) => {
                out.insert(name.clone(), one.clone());
            }
            other => die(format!("schema {name}: no unique generated type (candidates: {other:?})")),
        }
    }
    out
}

fn default_body(d: &DefaultFn) -> TokenStream {
    let ty = &d.ty;
    let ty_text = quote!(#ty).to_string();
    match (&d.json, ty_text.as_str()) {
        (Value::Number(n), "f64") => {
            let v = n.as_f64().expect("f64 default");
            quote!(#v)
        }
        (Value::Number(n), "i64") if n.is_i64() => {
            let v = n.as_i64().unwrap();
            quote!(#v)
        }
        (Value::Bool(b), "bool") => quote!(#b),
        _ => {
            let text = serde_json::to_string(&d.json).unwrap();
            let context = format!("schema default for {}.{}", d.struct_name, d.field);
            quote!(::serde_json::from_str::<#ty>(#text).expect(#context))
        }
    }
}

/// DEFECT companion: `defaults` holds the functions `apply_schema_defaults`
/// points serde at, and a generated test calls every one so a default that does
/// not deserialize into its own type fails in CI, not in a user's process.
fn write_generated(out: &Path, file: &syn::File, defaults: &[DefaultFn]) {
    let fns = defaults.iter().map(|d| {
        let name = format_ident!("{}", d.name);
        let ty = &d.ty;
        let body = default_body(d);
        quote! { pub fn #name() -> #ty { #body } }
    });
    let calls = defaults.iter().map(|d| {
        let name = format_ident!("{}", d.name);
        quote! { let _ = defaults::#name(); }
    });
    let tail: TokenStream = quote! {
        #[allow(non_snake_case)]
        pub mod defaults {
            use super::*;
            #(#fns)*
        }

        #[cfg(test)]
        mod default_tests {
            use super::*;

            #[test]
            fn every_schema_default_deserializes() {
                #(#calls)*
            }
        }
    };
    let mut file = file.clone();
    let tail_file: syn::File = syn::parse2(tail).expect("defaults module");
    file.items.extend(tail_file.items);
    let mut text = String::from("// @generated by codegen/rust. Do not edit.\n");
    text.push_str(&prettyplease::unparse(&file));
    fs::write(out.join("generated.rs"), text).expect("write generated.rs");
}

fn write_domains(out: &Path, domains: &Value, idents: &BTreeMap<String, String>) {
    let domains = domains.as_object().expect("x-domains");
    for (domain, names) in domains {
        let mut listed: Vec<&str> = names
            .as_array()
            .expect("domain names")
            .iter()
            .map(|n| n.as_str().expect("name"))
            .collect();
        listed.sort();
        let paths = listed.iter().map(|n| {
            let ident = format_ident!("{}", idents[*n]);
            quote!(#ident)
        });
        let tokens = quote! { pub use crate::generated::{ #(#paths),* }; };
        let file: syn::File = syn::parse2(tokens).expect("domain module");
        let text = format!(
            "// @generated by codegen/rust. Do not edit.\n//! The `{domain}` SiennaSchemas spec.\n{}",
            prettyplease::unparse(&file)
        );
        fs::write(out.join(format!("{domain}.rs")), text).expect("write domain");
    }
}
