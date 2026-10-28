//! Schema defaults. The SDK contract (see the README): a schema `default` documents the
//! value a consumer assumes for an absent field, and no SDK inserts it. An omitted optional
//! field stays absent, and a schema-required field stays required even with a default, as
//! in the Julia package. A `const` field, such as a discriminator, keeps its fixed value.

use power_openapi_models::generated::*;
use serde_json::{json, Value};

fn written<T: serde::Serialize>(value: &T) -> Value {
    serde_json::to_value(value).unwrap()
}

fn linear(proportional_term: f64) -> Value {
    json!({
        "curve_type": "INPUT_OUTPUT",
        "function_data": {
            "function_type": "LINEAR",
            "constant_term": 0.0,
            "proportional_term": proportional_term
        }
    })
}

#[test]
fn required_field_with_a_default_must_be_given() {
    // CostCurve requires vom_cost and power_units, and the schema gives both a default.
    let omitted = serde_json::from_value::<CostCurve>(json!({"value_curve": linear(1.0)}));
    assert!(omitted.is_err());
    let curve: CostCurve = serde_json::from_value(json!({
        "value_curve": linear(1.0),
        "vom_cost": linear(0.0),
        "power_units": "NATURAL_UNITS"
    }))
    .unwrap_or_else(|e| panic!("{e}"));
    let out = written(&curve);
    assert_eq!(out["power_units"], "NATURAL_UNITS");
    // A `const` discriminator keeps its fixed value.
    assert_eq!(out["variable_cost_type"], "COST");
}

#[test]
fn optional_field_with_a_default_stays_absent() {
    let emissions = json!({
        "id": 1, "name": "e", "pollutant": "CO2",
        "emission_rate": {
            "curve_type": "INCREMENTAL",
            "function_data": {"function_type": "LINEAR", "constant_term": 0.0, "proportional_term": 0.0},
            "initial_input": 0.0
        },
        "basis": "FUEL_INPUT", "energy_unit": "MMBTU"
    });
    let data: EmissionsData =
        serde_json::from_value(emissions.clone()).unwrap_or_else(|e| panic!("{e}"));
    let out = written(&data);
    assert!(out.get("mass_unit").is_none(), "{out}");
    assert!(out.get("available").is_none(), "{out}");

    let mut given = emissions;
    given["mass_unit"] = json!("LB");
    let data: EmissionsData = serde_json::from_value(given).unwrap_or_else(|e| panic!("{e}"));
    assert_eq!(written(&data)["mass_unit"], "LB");
}

#[test]
fn nullable_field_stays_null_and_defaulted_field_stays_absent() {
    let converter: InterconnectingConverter = serde_json::from_value(json!({
        "id": 1, "name": "c", "available": true, "bus": 1, "dc_bus": 2,
        "active_power": 0.0, "rating": 1.0, "base_power": 100.0,
        "power_units": "NATURAL_UNITS",
        "active_power_limits": {"min": 0.0, "max": 1.0}
    }))
    .unwrap_or_else(|e| panic!("{e}"));
    let out = written(&converter);
    assert!(out.get("remote_bus_control").is_none_or(Value::is_null));
    // The schema default of power_factor_weighting_fraction is 1.0; it is not inserted.
    assert!(
        out.get("power_factor_weighting_fraction").is_none(),
        "{out}"
    );
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
fn optional_ref_to_a_defaulted_type_stays_absent() {
    let curve: FuelCurve = serde_json::from_value(json!({
        "value_curve": linear(0.0),
        "vom_cost": linear(0.0),
        "power_units": "NATURAL_UNITS",
        "fuel_units": "MMBTU"
    }))
    .unwrap_or_else(|e| panic!("{e}"));
    assert!(written(&curve)
        .get("startup_fuel_offtake")
        .is_none_or(Value::is_null));
}
