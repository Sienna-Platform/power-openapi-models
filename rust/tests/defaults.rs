//! Schema defaults. openapi-to-rust drops them; the post-process restores them.
//! Each case mirrors a divergence the Python and TypeScript packages already had
//! to fix, and asserts what pydantic materializes.

use power_openapi_models::generated::*;
use serde_json::{json, Value};

fn written<T: serde::Serialize>(value: &T) -> Value {
    serde_json::to_value(value).unwrap()
}

#[test]
fn required_and_defaulted_field_may_be_omitted() {
    // CostCurve requires vom_cost and power_units and defaults both.
    let curve: CostCurve = serde_json::from_value(json!({
        "value_curve": {
            "curve_type": "INPUT_OUTPUT",
            "function_data": {
                "function_type": "LINEAR",
                "constant_term": 0.0,
                "proportional_term": 1.0
            }
        }
    }))
    .expect("omitted vom_cost / power_units take their schema defaults");
    let out = written(&curve);
    assert_eq!(out["power_units"], "NATURAL_UNITS");
    assert_eq!(out["variable_cost_type"], "COST");
    assert_eq!(
        out["vom_cost"]["function_data"]["proportional_term"].as_f64(),
        Some(0.0)
    );
}

#[test]
fn required_defaulted_object_with_its_own_defaults_is_complete() {
    // Source.operation_cost defaults to an object whose CostCurves omit
    // power_units; that must resolve through CostCurve's own default.
    let source: Source = serde_json::from_value(json!({
        "id": 1, "name": "s", "available": true, "bus": 1,
        "power_units": "NATURAL_UNITS"
    }))
    .unwrap_or_else(|e| panic!("{e}"));
    let out = written(&source);
    assert_eq!(out["operation_cost"]["cost_type"], "IMPORTEXPORT");
    assert_eq!(
        out["operation_cost"]["import_offer_curves"]["power_units"],
        "NATURAL_UNITS"
    );
}

#[test]
fn optional_defaulted_field_materializes_its_nonzero_default() {
    // internal_voltage defaults to 1.0: a Rust zero would be 0.0, an Option None.
    let source: Source = serde_json::from_value(json!({
        "id": 1, "name": "s", "available": true, "bus": 1,
        "power_units": "NATURAL_UNITS"
    }))
    .unwrap();
    let out = written(&source);
    assert_eq!(out["internal_voltage"].as_f64(), Some(1.0));
    assert_eq!(out["base_power"].as_f64(), Some(100.0));
    assert_eq!(out["active_power_limits"]["max"].as_f64(), Some(0.0));
}

#[test]
fn optional_defaulted_enum_field_materializes_its_default() {
    let data: EmissionsData = serde_json::from_value(json!({
        "id": 1, "name": "e", "pollutant": "CO2",
        "emission_rate": {
            "curve_type": "INCREMENTAL",
            "function_data": {"function_type": "LINEAR", "constant_term": 0.0, "proportional_term": 0.0},
            "initial_input": 0.0
        },
        "basis": "FUEL_INPUT", "energy_unit": "MMBTU"
    }))
    .unwrap_or_else(|e| panic!("{e}"));
    let out = written(&data);
    assert_eq!(out["mass_unit"], "KG");
    assert_eq!(out["available"], true);
}

#[test]
fn explicit_values_override_defaults() {
    let source: Source = serde_json::from_value(json!({
        "id": 1, "name": "s", "available": true, "bus": 1,
        "power_units": "NATURAL_UNITS", "internal_voltage": 1.05
    }))
    .unwrap();
    assert_eq!(written(&source)["internal_voltage"].as_f64(), Some(1.05));
}

#[test]
fn nullable_field_without_default_stays_null() {
    let converter: InterconnectingConverter = serde_json::from_value(json!({
        "id": 1, "name": "c", "available": true, "bus": 1, "dc_bus": 2,
        "active_power": 0.0, "rating": 1.0, "base_power": 100.0,
        "power_units": "NATURAL_UNITS",
        "active_power_limits": {"min": 0.0, "max": 1.0}
    }))
    .unwrap_or_else(|e| panic!("{e}"));
    let out = written(&converter);
    assert!(out["remote_bus_control"].is_null());
    // ac_setpoint defaults to 1.0; Rust's zero value would be 0.0.
    assert_eq!(out["ac_setpoint"].as_f64(), Some(1.0));
}

#[test]
fn types_compare_by_value() {
    let a: MinMax = serde_json::from_value(json!({"min": 0.9, "max": 1.1})).unwrap();
    assert_eq!(a, a.clone());
}

#[test]
fn acronym_type_names_are_not_recased() {
    // The schema titles are AGC and ACBus; a recasing generator exports `Agc`.
    let _: Option<AGC> = None;
    let _: Option<ACBus> = None;
}

#[test]
fn integer_enums_reject_values_the_schema_does_not_list() {
    // pydantic (IntEnum) and zod (union of literals) reject 5; a bare i64 accepts it.
    assert_eq!(
        serde_json::from_value::<CurveStyles>(json!(1)).unwrap(),
        CurveStyles::V1
    );
    assert!(serde_json::from_value::<CurveStyles>(json!(5)).is_err());
    assert_eq!(serde_json::to_value(CurveStyles::V0).unwrap(), json!(0));
}

#[test]
fn optional_ref_to_a_defaulted_type_gets_no_default() {
    // Only a *required* property inherits its target type's default.
    let curve: FuelCurve = serde_json::from_value(json!({
        "value_curve": {
            "curve_type": "INPUT_OUTPUT",
            "function_data": {"function_type": "LINEAR", "constant_term": 0, "proportional_term": 0}
        },
        "power_units": "NATURAL_UNITS"
    }))
    .unwrap_or_else(|e| panic!("{e}"));
    let out = written(&curve);
    assert!(
        out["vom_cost"].is_object(),
        "required vom_cost inherits InputOutputCurve's default"
    );
    assert!(out.get("startup_fuel_offtake").is_none_or(Value::is_null));
}
