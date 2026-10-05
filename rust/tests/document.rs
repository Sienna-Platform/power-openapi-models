//! SystemDocument / PortfolioDocument rules, mirroring python/tests/test_document.py.

use power_openapi_models::document::*;
use power_openapi_models::schema_version::current_schema_version;
use serde_json::{json, Value};

fn system() -> Value {
    json!({
        "schema_version": current_schema_version(),
        "components": {"ACBus": []},
        "supplemental_attributes": [],
        "supplemental_attribute_associations": [],
        "plant_associations": [],
        "combined_cycle_associations": [],
        "service_associations": [],
        "time_series_associations": [],
        "time_series_storage_file": null
    })
}

fn portfolio() -> Value {
    json!({
        "schema_version": current_schema_version(),
        "aggregation": "PSY.Area",
        "components": {},
        "supplemental_attributes": [],
        "supplemental_attribute_associations": [],
        "requirements_associations": [],
        "time_series_associations": [],
        "base_system_file": null,
        "time_series_storage_file": null
    })
}

fn parse(value: &Value) -> Result<SystemDocument, DocumentError> {
    parse_document(&value.to_string())
}

#[test]
fn minimal_document_parses() {
    parse(&system()).unwrap();
    parse_portfolio_document(&portfolio().to_string()).unwrap();
}

#[test]
fn each_required_key_is_required() {
    for key in system().as_object().unwrap().keys() {
        let mut doc = system();
        doc.as_object_mut().unwrap().remove(key);
        assert!(parse(&doc).is_err(), "{key} should be required");
    }
    for key in portfolio().as_object().unwrap().keys() {
        let mut doc = portfolio();
        doc.as_object_mut().unwrap().remove(key);
        assert!(
            parse_portfolio_document(&doc.to_string()).is_err(),
            "{key} should be required"
        );
    }
}

#[test]
fn required_nullable_key_accepts_null_but_not_absence() {
    let mut doc = system();
    doc["time_series_storage_file"] = json!("ts.h5");
    assert_eq!(
        parse(&doc).unwrap().time_series_storage_file.as_deref(),
        Some("ts.h5")
    );
    assert_eq!(parse(&system()).unwrap().time_series_storage_file, None);
}

#[test]
fn unknown_keys_are_rejected() {
    // Includes the removed document-level unit_system / base_power.
    for key in ["unit_system", "base_power", "surprise"] {
        let mut doc = system();
        doc[key] = json!(1);
        assert!(parse(&doc).is_err(), "{key}");
    }
}

#[test]
fn frequency_must_be_positive() {
    for bad in [0.0, -60.0] {
        let mut doc = system();
        doc["frequency"] = json!(bad);
        assert!(
            matches!(parse(&doc), Err(DocumentError::Invalid(_))),
            "{bad}"
        );
    }
    let mut doc = system();
    doc["frequency"] = json!(60.0);
    assert_eq!(parse(&doc).unwrap().frequency, Some(60.0));
}

#[test]
fn ext_values_must_be_objects() {
    let mut doc = system();
    doc["ext"] = json!({"3": {"k": 1}});
    parse(&doc).unwrap();
    doc["ext"] = json!({"3": 1});
    assert!(matches!(parse(&doc), Err(DocumentError::Invalid(_))));
}

#[test]
fn omitted_optional_fields_stay_omitted_on_write() {
    let text = document_to_string(&parse(&system()).unwrap()).unwrap();
    let written: Value = serde_json::from_str(&text).unwrap();
    for key in [
        "name",
        "description",
        "frequency",
        "ext",
        "trading_hub_associations",
    ] {
        assert!(written.get(key).is_none(), "{key} was added");
    }
    assert!(written["time_series_storage_file"].is_null());
    assert!(text.ends_with("}\n"));
}

#[test]
fn present_empty_ext_survives_a_roundtrip_but_defaulted_arrays_do_not() {
    let mut doc = system();
    doc["trading_hub_associations"] = json!([]);
    doc["ext"] = json!({});
    let written: Value =
        serde_json::from_str(&document_to_string(&parse(&doc).unwrap()).unwrap()).unwrap();
    assert!(written.get("trading_hub_associations").is_none());
    assert_eq!(written["ext"], json!({}));
}

#[test]
fn keys_are_written_sorted() {
    let mut doc = system();
    doc["components"] = json!({"Line": [], "ACBus": [], "Area": []});
    doc["name"] = json!("n");
    let text = document_to_string(&parse(&doc).unwrap()).unwrap();
    let written: Value = serde_json::from_str(&text).unwrap();
    let top: Vec<&String> = written.as_object().unwrap().keys().collect();
    assert_eq!(top[0], "schema_version");
    let mut sorted = top[1..].to_vec();
    sorted.sort();
    assert_eq!(top[1..], sorted);
    let comps: Vec<&String> = written["components"].as_object().unwrap().keys().collect();
    assert_eq!(comps, ["ACBus", "Area", "Line"]);
}

#[test]
fn portfolio_keys_are_written_sorted() {
    let text =
        portfolio_document_to_string(&parse_portfolio_document(&portfolio().to_string()).unwrap())
            .unwrap();
    let written: Value = serde_json::from_str(&text).unwrap();
    let top: Vec<&String> = written.as_object().unwrap().keys().collect();
    assert_eq!(top[0], "schema_version");
    let mut sorted = top[1..].to_vec();
    sorted.sort();
    assert_eq!(top[1..], sorted);
}

#[test]
fn indent_is_configurable() {
    let doc = parse(&system()).unwrap();
    let four = document_to_string_with_indent(&doc, 4).unwrap();
    assert!(four.contains("\n    \"combined_cycle_associations\""));
}

#[test]
fn write_then_read_via_files() {
    let dir = std::env::temp_dir().join(format!("pom-doc-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("doc.json");
    let doc = parse(&system()).unwrap();
    write_document(&doc, &path, SchemaVersionTarget::Current).unwrap();
    assert_eq!(read_document(&path).unwrap(), doc);
    std::fs::remove_dir_all(&dir).unwrap();
}
