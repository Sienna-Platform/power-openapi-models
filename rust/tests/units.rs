//! Lookups in the unit metadata generated from the x-unit annotations.

use power_openapi_models::generated::UnitSystem;
use power_openapi_models::units::{conversion_factor, field_unit, unit_base, FieldUnit, Unit};

#[test]
fn fixed_unit_and_base() {
    let magnitude = Unit {
        unit: "pu",
        quantity: "Voltage",
    };
    assert_eq!(
        field_unit("ACBus", "magnitude"),
        Some(FieldUnit::Fixed(magnitude))
    );
    assert_eq!(unit_base("ACBus", "magnitude"), Some("base_voltage"));
    assert_eq!(unit_base("ACBus", "angle"), None);
}

#[test]
fn discriminated_unit() {
    let Some(FieldUnit::Discriminated {
        discriminator,
        units,
    }) = field_unit("ThermalStandard", "active_power")
    else {
        panic!("ThermalStandard.active_power is not discriminated");
    };
    assert_eq!(discriminator, "power_units");
    let natural = units
        .iter()
        .find(|(k, _)| *k == UnitSystem::NaturalUnits.as_str());
    assert_eq!(natural.map(|(_, u)| u.unit), Some("MW"));
}

#[test]
fn keyed_by_rust_field_name() {
    // The schema property is `Y`; the Rust field is `y`.
    assert!(field_unit("FixedAdmittance", "y").is_some());
    assert!(field_unit("FixedAdmittance", "Y").is_none());
}

#[test]
fn conversion_factors() {
    assert_eq!(conversion_factor("ActivePower", "kW"), Some(0.001));
    assert_eq!(conversion_factor("ActivePower", "pu"), None);
    // units.json stores the nominal frequency (60.0) here, not a factor.
    assert_eq!(conversion_factor("Frequency", "Hz"), Some(1.0));
}
