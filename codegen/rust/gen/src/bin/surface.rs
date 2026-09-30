//! Prints the surface of the generated Rust models as JSON, for
//! `scripts/check_cross_language.py`.
//!
//!   surface rust/src/generated.rs
//!
//! Read from the serde attributes, not the field declarations: what the codec
//! accepts and writes is `#[serde(rename)]` (the wire key), `#[serde(default)]`
//! (omittable) and the type's variants' renames (the enum's wire values). A
//! struct declaration alone says none of that.
//!
//! Output: {"files": 1, "types": {Name: {"fields": {wire: {"kind", "default"}},
//! "required": [wire...], "enums": {wire: [value...]}}}}

use std::collections::BTreeMap;
use std::{env, fs, process};

use serde_json::{json, Map, Value};
use syn::punctuated::Punctuated;
use syn::{Expr, Fields, GenericArgument, Item, Lit, Meta, PathArguments, Token, Type};

fn die(message: String) -> ! {
    eprintln!("ERROR: {message}");
    process::exit(1);
}

/// `(rename, default fn path)` from a field's or variant's serde attributes.
fn serde_items(attrs: &[syn::Attribute]) -> (Option<String>, Option<String>) {
    let (mut rename, mut default) = (None, None);
    for attr in attrs.iter().filter(|a| a.path().is_ident("serde")) {
        let Meta::List(list) = &attr.meta else { continue };
        let metas = list
            .parse_args_with(Punctuated::<Meta, Token![,]>::parse_terminated)
            .expect("parse serde attr");
        for meta in metas {
            match &meta {
                Meta::NameValue(nv) if nv.path.is_ident("rename") => {
                    if let Expr::Lit(syn::ExprLit { lit: Lit::Str(s), .. }) = &nv.value {
                        rename = Some(s.value());
                    }
                }
                Meta::NameValue(nv) if nv.path.is_ident("default") => {
                    if let Expr::Lit(syn::ExprLit { lit: Lit::Str(s), .. }) = &nv.value {
                        default = Some(s.value());
                    }
                }
                Meta::Path(p) if p.is_ident("default") => {
                    default = Some(String::new());
                }
                _ => {}
            }
        }
    }
    (rename, default)
}

fn last_segment(ty: &Type) -> Option<&syn::PathSegment> {
    match ty {
        Type::Path(p) => p.path.segments.last(),
        _ => None,
    }
}

fn unwrap_option(ty: &Type) -> (&Type, bool) {
    if let Some(seg) = last_segment(ty) {
        if seg.ident == "Option" {
            if let PathArguments::AngleBracketed(args) = &seg.arguments {
                if let Some(GenericArgument::Type(inner)) = args.args.first() {
                    return (inner, true);
                }
            }
        }
    }
    (ty, false)
}

fn kind(ty: &Type) -> Value {
    match last_segment(ty).map(|s| s.ident.to_string()).as_deref() {
        Some("f64") | Some("f32") => json!("number"),
        Some("i64") | Some("i32") | Some("u64") | Some("u32") => json!("integer"),
        Some("String") => json!("string"),
        Some("bool") => json!("boolean"),
        _ => Value::Null,
    }
}

/// A default function's value as JSON: a bare literal, or the JSON text handed to
/// `serde_json::from_str`. Anything else is a generator change this must not
/// paper over.
fn default_value(body: &syn::Block, name: &str) -> Value {
    let Some(syn::Stmt::Expr(expr, None)) = body.stmts.first() else {
        die(format!("default fn {name}: unexpected body"));
    };
    match expr {
        Expr::Lit(l) => match &l.lit {
            Lit::Float(f) => json!(f.base10_parse::<f64>().unwrap()),
            Lit::Int(i) => json!(i.base10_parse::<i64>().unwrap()),
            Lit::Bool(b) => json!(b.value),
            other => die(format!("default fn {name}: literal {other:?}")),
        },
        Expr::MethodCall(call) => {
            if let Expr::Call(inner) = &*call.receiver {
                if let Some(Expr::Lit(syn::ExprLit { lit: Lit::Str(s), .. })) = inner.args.first() {
                    return serde_json::from_str(&s.value())
                        .unwrap_or_else(|e| die(format!("default fn {name}: {e}")));
                }
            }
            die(format!("default fn {name}: unexpected call shape"))
        }
        _ => die(format!("default fn {name}: unexpected expression")),
    }
}

/// A unit variant's wire value: its explicit integer discriminant when it has one
/// (the integer enums `codegen/rust` generates), else its serde `rename`, else its
/// identifier.
fn variant_wire_value(variant: &syn::Variant) -> Value {
    if let Some((_, Expr::Lit(syn::ExprLit { lit: Lit::Int(i), .. }))) = &variant.discriminant {
        return json!(i.base10_parse::<i64>().unwrap());
    }
    json!(serde_items(&variant.attrs).0.unwrap_or_else(|| variant.ident.to_string()))
}

fn main() {
    let path = env::args().nth(1).unwrap_or_else(|| die("usage: surface GENERATED.rs".into()));
    let file: syn::File = syn::parse_str(&fs::read_to_string(&path).expect("read")).expect("parse");

    let mut enums: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    let mut defaults: BTreeMap<String, Value> = BTreeMap::new();
    for item in &file.items {
        match item {
            Item::Enum(e) if e.variants.iter().all(|v| matches!(v.fields, Fields::Unit)) => {
                let values = e.variants.iter().map(variant_wire_value).collect();
                enums.insert(e.ident.to_string(), values);
            }
            Item::Mod(m) if m.ident == "defaults" => {
                for inner in &m.content.as_ref().expect("defaults body").1 {
                    if let Item::Fn(f) = inner {
                        let name = f.sig.ident.to_string();
                        let value = default_value(&f.block, &name);
                        defaults.insert(name, value);
                    }
                }
            }
            _ => {}
        }
    }

    let mut types = Map::new();
    for item in &file.items {
        let Item::Struct(s) = item else { continue };
        let Fields::Named(fields) = &s.fields else { continue };
        // A struct that is only a flattened string-keyed map is a map on the wire,
        // like a zod record; Python calls it a RootModel and reports it separately.
        if fields.named.len() == 1
            && fields.named[0].ident.as_ref().is_some_and(|i| i == "additional_properties")
        {
            continue;
        }
        let mut out_fields = Map::new();
        let mut required = Vec::new();
        let mut out_enums = Map::new();
        for field in &fields.named {
            let ident = field.ident.as_ref().unwrap().to_string();
            let (rename, default) = serde_items(&field.attrs);
            let wire = rename.unwrap_or_else(|| ident.trim_start_matches("r#").to_string());
            let (inner, is_option) = unwrap_option(&field.ty);
            let default_json = match default.as_deref() {
                None => Value::Null,
                Some("") => Value::Null,
                Some(path) => {
                    let name = path.strip_prefix("defaults::").unwrap_or_else(|| {
                        die(format!("{}.{wire}: default path {path:?}", s.ident))
                    });
                    defaults
                        .get(name)
                        .cloned()
                        .unwrap_or_else(|| die(format!("{}.{wire}: no default fn {name}", s.ident)))
                }
            };
            if default.is_none() && !is_option {
                required.push(json!(wire));
            }
            if let Some(values) = last_segment(inner).and_then(|seg| enums.get(&seg.ident.to_string())) {
                out_enums.insert(wire.clone(), json!(values));
            }
            out_fields.insert(wire, json!({"kind": kind(inner), "default": default_json}));
        }
        types.insert(
            s.ident.to_string(),
            json!({"fields": out_fields, "required": required, "enums": out_enums}),
        );
    }
    println!("{}", json!({"files": 1, "types": types}));
}
