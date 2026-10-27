//! Checks a JSON value against one definition of this crate's strict bundle.
//! Needs the `validate` cargo feature.
//!
//! The generated types check shape: a missing field, a wrong type, or an
//! unknown property. They accept a reserved feature name or a number out of its
//! bounds. A [`Validator`] checks all the schema states.
//!
//! The bundle is the `SystemDocument` bundle of [`crate::SCHEMA_VERSION`],
//! compiled in, so the check needs no filesystem and no network. Formats are
//! not checked, so a timestamp without an offset passes, as it does in the
//! generated types.

use std::sync::OnceLock;

use serde_json::{json, Value};

use crate::document::DocumentError;

const SYSTEM_BUNDLE: &str = include_str!(env!("POM_SYSTEM_BUNDLE"));

fn definitions() -> &'static Value {
    static DEFINITIONS: OnceLock<Value> = OnceLock::new();
    DEFINITIONS.get_or_init(|| {
        let mut bundle: Value =
            serde_json::from_str(SYSTEM_BUNDLE).expect("the compiled-in bundle is JSON");
        bundle["definitions"].take()
    })
}

/// The compiled check for one schema definition. Compile it once and use it for
/// every value, because compiling costs much more than a check.
pub struct Validator {
    definition: String,
    inner: jsonschema::Validator,
}

impl Validator {
    /// Compiles the check for `definition`, a definition name in the bundle:
    /// a component type such as `ACBus`, or a row type such as
    /// `TimeSeriesAssociation` or `SupplementalAttributeAssociation`.
    pub fn new(definition: &str) -> Result<Self, DocumentError> {
        let definitions = definitions();
        if definitions.get(definition).is_none() {
            return Err(DocumentError::Invalid(format!(
                "schema {} has no definition {definition:?}",
                crate::SCHEMA_VERSION
            )));
        }
        let schema = json!({
            "$schema": "http://json-schema.org/draft-07/schema#",
            "definitions": definitions,
            "allOf": [{"$ref": format!("#/definitions/{definition}")}],
        });
        let inner = jsonschema::draft7::options()
            .should_validate_formats(false)
            .build(&schema)
            .map_err(|e| DocumentError::Invalid(format!("definition {definition:?}: {e}")))?;
        Ok(Self {
            definition: definition.to_owned(),
            inner,
        })
    }

    /// Every JSON path in `value` that the definition rejects, sorted, as
    /// `/json/pointer: reason`. A failed `oneOf` reports its closest branch, so
    /// a time series row reports against its own type.
    pub fn violations(&self, value: &Value) -> Vec<String> {
        let mut violations = Vec::new();
        for error in self.inner.iter_errors(value) {
            crate::schema_version::leaves(&error, &mut violations);
        }
        violations.sort();
        violations.dedup();
        violations
    }

    /// Fails with [`DocumentError::Schema`] when `value` breaks the definition.
    pub fn validate(&self, value: &Value) -> Result<(), DocumentError> {
        let paths = self.violations(value);
        if paths.is_empty() {
            return Ok(());
        }
        Err(DocumentError::Schema {
            definition: self.definition.clone(),
            paths,
        })
    }
}
