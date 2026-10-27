//! Row and component checks against the compiled-in strict bundle.
#![cfg(feature = "validate")]

use power_openapi_models::document::DocumentError;
use power_openapi_models::validate::Validator;
use serde_json::{json, Value};

fn single_time_series() -> Value {
    json!({
        "association_id": 1,
        "owner_id": 7,
        "owner_type": "ThermalStandard",
        "owner_category": "Component",
        "time_series_type": "SingleTimeSeries",
        "name": "max_active_power",
        "features": {},
        "uri": "6044a282e6ea37af7982ca551b8d5dca932fe4fb696bf9cfa14e7316e2693286",
        "element_type": "f64",
        "element_shape": [],
        "initial_timestamp": "2030-01-01T00:00:00Z",
        "resolution": "PT1H",
        "length": 24
    })
}

fn rows() -> Validator {
    Validator::new("TimeSeriesAssociation").unwrap()
}

#[test]
fn a_valid_row_passes() {
    rows().validate(&single_time_series()).unwrap();
}

#[test]
fn a_timestamp_without_an_offset_passes_as_in_the_generated_types() {
    let mut row = single_time_series();
    row["initial_timestamp"] = json!("2030-01-01T00:00:00");
    rows().validate(&row).unwrap();
}

#[test]
fn a_failed_one_of_reports_the_rows_own_type() {
    let mut row = single_time_series();
    row["length"] = json!(-1);
    assert_eq!(
        rows().violations(&row).len(),
        1,
        "{:?}",
        rows().violations(&row)
    );
    assert!(rows().violations(&row)[0].starts_with("/length:"));
}

#[test]
fn an_unknown_property_fails() {
    let mut row = single_time_series();
    row["owner_typ"] = json!("Typo");
    assert_eq!(rows().violations(&row), ["/owner_typ: unknown property"]);
}

#[test]
fn a_reserved_feature_name_fails() {
    let mut row = single_time_series();
    row["features"] = json!({"resolution": "high"});
    let Err(DocumentError::Schema { definition, paths }) = rows().validate(&row) else {
        panic!("a feature named after a field is reserved");
    };
    assert_eq!(definition, "TimeSeriesAssociation");
    assert!(
        paths.iter().all(|p| p.starts_with("/features")),
        "{paths:?}"
    );
}

#[test]
fn a_component_checks_against_its_type() {
    let acbus = Validator::new("ACBus").unwrap();
    acbus
        .validate(&json!({"id": 1, "name": "bus1", "available": true, "number": 1}))
        .unwrap();
    let violations = acbus.violations(&json!({"id": 1, "name": "bus1", "available": true}));
    assert_eq!(violations.len(), 1, "{violations:?}");
    assert!(violations[0].contains("number"), "{violations:?}");
}

#[test]
fn an_unknown_definition_fails() {
    assert!(matches!(
        Validator::new("NoSuchType"),
        Err(DocumentError::Invalid(_))
    ));
}
