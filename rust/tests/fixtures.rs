//! Serde tests against real 14-bus operations documents, the same fixtures the
//! Python and TypeScript suites use. Operations types only, no time series.

use std::fs;
use std::path::PathBuf;

use power_openapi_models::document::{document_to_string, parse_document};
use power_openapi_models::generated::*;
use serde_json::Value;

const EXPECTED_COMPONENT_COUNT: usize = 119;
const FIXTURES: [&str; 2] = ["NATURAL_UNITS", "COMPONENT_BASE"];

fn fixture_text(variant: &str) -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../fixtures")
        .join(format!("case14_operations.{variant}.json"));
    fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

/// Deserializes `entry` as the generated type named `type_name` and serializes it
/// back. Fails for a type this list does not know, so a fixture gaining a type
/// cannot pass by being skipped.
fn roundtrip(type_name: &str, entry: &Value) -> Value {
    macro_rules! through {
        ($($ty:ident),* $(,)?) => {
            match type_name {
                $(stringify!($ty) => {
                    let value: $ty = serde_json::from_value(entry.clone())
                        .unwrap_or_else(|e| panic!("{type_name}: {e}\n{entry}"));
                    serde_json::to_value(&value).unwrap()
                })*
                other => panic!("no generated model registered for {other:?}"),
            }
        };
    }
    through!(
        ACBus,
        Arc,
        Area,
        DiscreteControlledACBranch,
        FACTSControlDevice,
        FixedAdmittance,
        Line,
        LoadZone,
        StandardLoad,
        SwitchedAdmittance,
        ThermalStandard,
        ThreeWindingTransformer,
        TransformerCircuit,
        TwoTerminalLCCLine,
        TwoWindingTransformer,
    )
}

/// Drops null-valued keys so an omitted field and an explicit null compare equal.
fn strip_null(value: &Value) -> Value {
    match value {
        Value::Object(map) => Value::Object(
            map.iter()
                .filter(|(_, v)| !v.is_null())
                .map(|(k, v)| (k.clone(), strip_null(v)))
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(strip_null).collect()),
        other => other.clone(),
    }
}

fn diff(before: &Value, after: &Value, path: &str, out: &mut Vec<String>) {
    match (before, after) {
        (Value::Object(b), Value::Object(a)) => {
            let mut keys: Vec<&String> = b.keys().chain(a.keys()).collect();
            keys.sort();
            keys.dedup();
            for key in keys {
                let here = if path.is_empty() {
                    key.clone()
                } else {
                    format!("{path}.{key}")
                };
                match (b.get(key), a.get(key)) {
                    (Some(v), None) => out.push(format!("dropped {here} (was {v})")),
                    (None, Some(v)) => out.push(format!("added {here} = {v}")),
                    (Some(b), Some(a)) => diff(b, a, &here, out),
                    (None, None) => unreachable!(),
                }
            }
        }
        (Value::Array(b), Value::Array(a)) => {
            if b.len() != a.len() {
                out.push(format!("length {path}: {} -> {}", b.len(), a.len()));
            } else {
                for (i, (b, a)) in b.iter().zip(a).enumerate() {
                    diff(b, a, &format!("{path}[{i}]"), out);
                }
            }
        }
        (b, a) => {
            let same = match (b.as_f64(), a.as_f64()) {
                (Some(x), Some(y)) => x == y,
                _ => b == a,
            };
            if !same {
                out.push(format!("changed {path}: {b} -> {a}"));
            }
        }
    }
}

#[test]
fn component_count() {
    for variant in FIXTURES {
        let doc = parse_document(&fixture_text(variant)).unwrap();
        let total: usize = doc.components.values().map(Vec::len).sum();
        assert_eq!(total, EXPECTED_COMPONENT_COUNT, "{variant}");
    }
}

#[test]
fn all_components_deserialize_and_roundtrip_without_drift() {
    for variant in FIXTURES {
        let raw: Value = serde_json::from_str(&fixture_text(variant)).unwrap();
        let mut diffs = Vec::new();
        for (type_name, entries) in raw["components"].as_object().unwrap() {
            for (i, entry) in entries.as_array().unwrap().iter().enumerate() {
                let rebuilt = roundtrip(type_name, entry);
                diff(
                    &strip_null(entry),
                    &strip_null(&rebuilt),
                    &format!("{type_name}[{i}]"),
                    &mut diffs,
                );
            }
        }
        assert!(
            diffs.is_empty(),
            "{variant}:\n{}",
            diffs[..diffs.len().min(20)].join("\n")
        );
    }
}

#[test]
fn document_roundtrip_is_byte_identical() {
    for variant in FIXTURES {
        let raw = fixture_text(variant);
        let doc = parse_document(&raw).unwrap();
        assert_eq!(document_to_string(&doc).unwrap(), raw, "{variant}");
    }
}

#[test]
fn natural_units_spot_checks() {
    let raw: Value = serde_json::from_str(&fixture_text("NATURAL_UNITS")).unwrap();
    let bus = &raw["components"]["ACBus"][0];
    assert_eq!(bus["base_voltage"], 138.0);
    assert!(bus.get("power_units").is_none());
    let thermal = &raw["components"]["ThermalStandard"][0];
    assert_eq!(thermal["power_units"], "NATURAL_UNITS");
    assert_eq!(
        raw["supplemental_attribute_associations"]
            .as_array()
            .unwrap()
            .len(),
        9
    );
}
