//! Hand-written (NOT generated): the `SystemDocument` and `PortfolioDocument`
//! containers and their JSON I/O.
//!
//! Counterpart of `power_openapi_models/document.py` and
//! `typescript/src/document.ts`. `Core/SystemDocument.json` and
//! `Investments/PortfolioDocument.json` in SiennaSchemas are authoritative for
//! the two shapes; this module mirrors their properties and `required` lists.
//!
//! Both are hand-written because `components` is a map from type name to an
//! array of heterogeneous objects, which a generator cannot express as typed
//! buckets. `components` and `supplemental_attributes` therefore stay untyped
//! JSON objects; the association arrays use the generated row types.
//!
//! Writing follows the Python package's rules: `schema_version` first, then the
//! other top-level keys and `components` keys sorted, everything else in input
//! order, and a trailing newline. Encoding is canonical: an optional property
//! that is absent, null, or equal to its schema default is omitted, so
//! `trading_hub_associations` and `voltage_control_associations` are written
//! only when non-empty. Component and
//! supplemental attribute rows are untyped JSON and are written as read; the
//! typed rows omit unset optional fields themselves.
//!
//! Every read checks `schema_version` against this crate's own (see
//! [`crate::schema_version`]) on the raw JSON before decoding. Writes stamp the
//! crate's version, or the version the document was read at with
//! [`SchemaVersionTarget::Source`].

use std::collections::BTreeMap;
use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};

use serde::de::DeserializeOwned;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{json, Map, Value};

use crate::infrastructure_core::SupplementalAttributeAssociation;
use crate::investments::{PortfolioFinancialData, RequirementAssociation};
use crate::operations::{
    CombinedCycleAssociation, PlantAssociation, ServiceAssociation, TradingHubAssociation,
    VoltageControlAssociation,
};
use crate::schema_version::{
    check_schema_version_for, current_schema_version, message, SchemaVersionOutcome,
};
use crate::timeseries::TimeSeriesAssociation;

/// A JSON object whose key order is preserved.
pub type JsonObject = Map<String, Value>;

/// Why a document could not be read or written.
#[derive(Debug)]
pub enum DocumentError {
    Io(std::io::Error),
    Json(serde_json::Error),
    /// The JSON parsed, but breaks a constraint the schema states.
    Invalid(String),
    /// The document's `schema_version` is not readable by this crate. `document`
    /// is the raw stamp, `null` when absent.
    Version {
        outcome: SchemaVersionOutcome,
        reader: String,
        document: Value,
    },
    /// A `schema_version = source` write could not be done. `paths` lists every
    /// JSON path the source version's strict bundle rejects.
    SourceVersion {
        message: String,
        paths: Vec<String>,
    },
}

impl fmt::Display for DocumentError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(f, "{error}"),
            Self::Json(error) => write!(f, "{error}"),
            Self::Invalid(message) => write!(f, "{message}"),
            Self::Version {
                outcome,
                reader,
                document,
            } => write!(f, "{}", message(*outcome, reader, document)),
            Self::SourceVersion { message, .. } => write!(f, "{message}"),
        }
    }
}

impl std::error::Error for DocumentError {}

impl From<std::io::Error> for DocumentError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}

impl From<serde_json::Error> for DocumentError {
    fn from(error: serde_json::Error) -> Self {
        Self::Json(error)
    }
}

/// A required key whose value may be `null`. Plain `Option` would also accept
/// the key being absent; deserializing through this makes absence an error, as
/// it is in the Python and TypeScript packages.
fn required_nullable<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(deserializer)
}

fn validate_ext(ext: &Option<JsonObject>) -> Result<(), DocumentError> {
    if let Some(ext) = ext {
        for (key, value) in ext {
            if !value.is_object() {
                return Err(DocumentError::Invalid(format!(
                    "ext[{key:?}] must be an object"
                )));
            }
        }
    }
    Ok(())
}

/// A whole serialized power system: components bucketed by type name, the
/// association tables linking them, and the name of the HDF5 sidecar holding
/// time series values. Mirrors `Core/SystemDocument.json`.
///
/// Fields are declared in sorted key order: that is the order they are written,
/// after `schema_version`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SystemDocument {
    /// The schema version the document was read at, or this crate's for a new
    /// one. Not serialized: `schema_version` is stamped on write.
    #[serde(skip, default = "current_owned")]
    pub source_schema_version: String,
    /// Links a CombinedCycleBlock plant to a CT or CA unit and the HRSG it feeds
    /// into or receives from.
    pub combined_cycle_associations: Vec<CombinedCycleAssociation>,
    /// Components grouped by type name, e.g. `{"ACBus": [...]}`. Keys are the
    /// referenced schema's `title` and are written in sorted order.
    pub components: BTreeMap<String, Vec<JsonObject>>,
    /// Optional free-text description of the system.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    /// Source data no schema field claims, keyed by the stringified component
    /// id it belongs to.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ext: Option<JsonObject>,
    /// Nominal system frequency. Units: Hz. Must be positive.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub frequency: Option<f64>,
    /// Optional system name.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    /// Links a power plant supplemental attribute to a generating unit and the
    /// group it belongs to within the plant.
    pub plant_associations: Vec<PlantAssociation>,
    /// Links a service to one component that contributes to it.
    pub service_associations: Vec<ServiceAssociation>,
    /// Links each plain supplemental attribute to the entity it describes.
    pub supplemental_attribute_associations: Vec<SupplementalAttributeAssociation>,
    /// Supplemental attributes in one flat array, not bucketed by type.
    pub supplemental_attributes: Vec<JsonObject>,
    /// Time series metadata rows. Values themselves never appear here.
    pub time_series_associations: Vec<TimeSeriesAssociation>,
    /// Basename of the HDF5 sidecar holding time series values, or `None` when
    /// the system has no time series. The key itself is required.
    #[serde(deserialize_with = "required_nullable")]
    pub time_series_storage_file: Option<String>,
    /// Links a trading hub to one associated entity. Added after the other
    /// association arrays, so older documents omit it; written only when non-empty.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub trading_hub_associations: Vec<TradingHubAssociation>,
    /// Links a voltage control group to one member device. Added after the other
    /// association arrays, so older documents omit it; written only when non-empty.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub voltage_control_associations: Vec<VoltageControlAssociation>,
}

impl SystemDocument {
    /// The schema version the document was read at (`D`), or this crate's for a
    /// document built in memory.
    pub fn get_source_schema_version(&self) -> &str {
        &self.source_schema_version
    }

    /// Checks the constraints the schema states beyond shape.
    pub fn validate(&self) -> Result<(), DocumentError> {
        if let Some(frequency) = self.frequency {
            if frequency.is_nan() || frequency <= 0.0 {
                return Err(DocumentError::Invalid(format!(
                    "frequency must be greater than 0, got {frequency}"
                )));
            }
        }
        validate_ext(&self.ext)
    }
}

/// A whole serialized investment portfolio: candidate technologies, regional
/// aggregations, policy requirements, and the names of the sidecar files holding
/// the base power system and time series values. Mirrors
/// `Investments/PortfolioDocument.json`.
///
/// Fields are declared in sorted key order: that is the order they are written,
/// after `schema_version`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PortfolioDocument {
    /// The schema version the document was read at, or this crate's for a new
    /// one. Not serialized: `schema_version` is stamped on write.
    #[serde(skip, default = "current_owned")]
    pub source_schema_version: String,
    /// Qualified type name of the regional aggregation the portfolio groups its
    /// regions by. Resolved by the consumer; not a component in the document.
    pub aggregation: String,
    /// Basename of the sidecar holding the base power system this portfolio
    /// expands, or `None` when it has none. The key itself is required.
    #[serde(deserialize_with = "required_nullable")]
    pub base_system_file: Option<String>,
    /// Components grouped by type name. Keys are written in sorted order.
    pub components: BTreeMap<String, Vec<JsonObject>>,
    /// Optional identifier of the source the portfolio data was drawn from.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub data_source: Option<String>,
    /// Optional free-text description of the portfolio.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    /// Source data no schema field claims, keyed by the stringified component
    /// id it belongs to.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ext: Option<JsonObject>,
    /// Portfolio-wide financial parameters.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub financial_data: Option<PortfolioFinancialData>,
    /// Investment decisions produced by solving the portfolio; carried opaquely.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub investment_schedule: Option<JsonObject>,
    /// Optional portfolio name.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    /// Links each policy requirement to one member subject to it.
    pub requirements_associations: Vec<RequirementAssociation>,
    /// Links each supplemental attribute to the entity it describes.
    pub supplemental_attribute_associations: Vec<SupplementalAttributeAssociation>,
    /// Supplemental attributes in one flat array, not bucketed by type.
    pub supplemental_attributes: Vec<JsonObject>,
    /// Time series metadata rows. Values themselves never appear here.
    pub time_series_associations: Vec<TimeSeriesAssociation>,
    /// Basename of the HDF5 sidecar holding time series values, or `None` when
    /// the portfolio has no time series. The key itself is required.
    #[serde(deserialize_with = "required_nullable")]
    pub time_series_storage_file: Option<String>,
}

impl PortfolioDocument {
    /// The schema version the document was read at (`D`), or this crate's for a
    /// document built in memory.
    pub fn get_source_schema_version(&self) -> &str {
        &self.source_schema_version
    }

    /// Checks the constraints the schema states beyond shape.
    pub fn validate(&self) -> Result<(), DocumentError> {
        validate_ext(&self.ext)
    }
}

const DEFAULT_INDENT: usize = 2;

fn current_owned() -> String {
    current_schema_version().to_owned()
}

/// Which `schema_version` a write stamps.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum SchemaVersionTarget {
    /// This crate's version. Cannot fail on version grounds.
    #[default]
    Current,
    /// The version the document was read at. When that is older than this crate's,
    /// the encoded document is validated against that version's strict bundle and
    /// the write fails, listing every offending path, if it holds anything newer.
    /// Needs the `source-version` cargo feature.
    Source,
}

trait Container: Serialize + DeserializeOwned {
    /// File name of the strict bundle in `bundles/<version>/`.
    #[cfg_attr(not(feature = "source-version"), allow(dead_code))]
    const BUNDLE: &'static str;

    fn validate(&self) -> Result<(), DocumentError>;
    fn source(&self) -> &str;
    fn set_source(&mut self, version: String);
}

impl Container for SystemDocument {
    const BUNDLE: &'static str = "SystemDocument.json";

    fn validate(&self) -> Result<(), DocumentError> {
        SystemDocument::validate(self)
    }

    fn source(&self) -> &str {
        &self.source_schema_version
    }

    fn set_source(&mut self, version: String) {
        self.source_schema_version = version;
    }
}

impl Container for PortfolioDocument {
    const BUNDLE: &'static str = "PortfolioDocument.json";

    fn validate(&self) -> Result<(), DocumentError> {
        PortfolioDocument::validate(self)
    }

    fn source(&self) -> &str {
        &self.source_schema_version
    }

    fn set_source(&mut self, version: String) {
        self.source_schema_version = version;
    }
}

/// The directory holding `bundles/<version>/` as shipped with this crate.
fn default_bundles() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("bundles")
}

fn parse_for<T: Container>(reader: &str, text: &str) -> Result<T, DocumentError> {
    let mut raw: Value = serde_json::from_str(text)?;
    let outcome = check_schema_version_for(reader, &raw)?;
    if !outcome.is_readable() {
        return Err(DocumentError::Version {
            outcome,
            reader: reader.to_owned(),
            document: raw.get("schema_version").cloned().unwrap_or(Value::Null),
        });
    }
    let stamp = match raw
        .as_object_mut()
        .and_then(|object| object.remove("schema_version"))
    {
        Some(Value::String(stamp)) => stamp,
        _ => unreachable!("a readable document carries a string schema_version"),
    };
    let mut doc: T = serde_json::from_value(raw)?;
    doc.set_source(stamp);
    doc.validate()?;
    Ok(doc)
}

#[cfg(feature = "source-version")]
fn check_source<T: Container>(
    bundles: &Path,
    tree: &Value,
    source: &str,
    reader: &str,
) -> Result<(), DocumentError> {
    let bundle = bundles.join(source).join(T::BUNDLE);
    if !bundle.is_file() {
        return Err(DocumentError::SourceVersion {
            message: format!(
                "no strict bundle for schema {source} at {}; cannot write it without the \
                 bundle, write with SchemaVersionTarget::Current to stamp schema {reader}",
                bundle.display()
            ),
            paths: Vec::new(),
        });
    }
    let violations = crate::schema_version::bundle_violations(&bundle, tree)?;
    if violations.is_empty() {
        return Ok(());
    }
    let mut message = format!(
        "document cannot be written at schema {source}: {} path(s) are not valid there:",
        violations.len()
    );
    for violation in &violations {
        message.push_str("\n  ");
        message.push_str(violation);
    }
    message.push_str(&format!(
        "\nwrite with SchemaVersionTarget::Current to stamp schema {reader}"
    ));
    Err(DocumentError::SourceVersion {
        message,
        paths: violations,
    })
}

#[cfg(not(feature = "source-version"))]
fn check_source<T: Container>(
    _bundles: &Path,
    _tree: &Value,
    source: &str,
    reader: &str,
) -> Result<(), DocumentError> {
    Err(DocumentError::SourceVersion {
        message: format!(
            "writing schema {source} for a reader at schema {reader} needs the cargo feature \
             `source-version` (jsonschema); enable it or write with SchemaVersionTarget::Current"
        ),
        paths: Vec::new(),
    })
}

fn encode<T: Container>(
    reader: &str,
    bundles: &Path,
    doc: &T,
    target: SchemaVersionTarget,
    indent: usize,
) -> Result<String, DocumentError> {
    doc.validate()?;
    let Value::Object(body) = serde_json::to_value(doc)? else {
        unreachable!("documents serialize as objects");
    };
    let stamp = match target {
        SchemaVersionTarget::Current => reader,
        SchemaVersionTarget::Source => doc.source(),
    };
    if stamp != reader {
        let outcome = check_schema_version_for(reader, &json!({ "schema_version": stamp }))?;
        if !outcome.is_readable() {
            return Err(DocumentError::Version {
                outcome,
                reader: reader.to_owned(),
                document: Value::String(stamp.to_owned()),
            });
        }
    }
    let mut tree = JsonObject::new();
    tree.insert("schema_version".to_owned(), Value::String(stamp.to_owned()));
    tree.extend(body);
    let tree = Value::Object(tree);
    if stamp != reader {
        check_source::<T>(bundles, &tree, stamp, reader)?;
    }
    let indent_bytes = vec![b' '; indent];
    let formatter = serde_json::ser::PrettyFormatter::with_indent(&indent_bytes);
    let mut buffer = Vec::new();
    let mut serializer = serde_json::Serializer::with_formatter(&mut buffer, formatter);
    tree.serialize(&mut serializer)?;
    let mut text = String::from_utf8(buffer).expect("serde_json emits UTF-8");
    text.push('\n');
    Ok(text)
}

fn refuse_overwrite(dst: &Path, force: bool) -> Result<(), DocumentError> {
    if !force && dst.exists() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::AlreadyExists,
            format!("{} exists; pass force to overwrite it", dst.display()),
        )
        .into());
    }
    Ok(())
}

/// Parses a `SystemDocument` from JSON text and validates it. Fails with
/// [`DocumentError::Version`] unless `schema_version` is `current` or `upgradable`.
pub fn parse_document(text: &str) -> Result<SystemDocument, DocumentError> {
    parse_for(current_schema_version(), text)
}

/// [`parse_document`] for an explicit reader version.
#[doc(hidden)]
pub fn parse_document_for(reader: &str, text: &str) -> Result<SystemDocument, DocumentError> {
    parse_for(reader, text)
}

/// Reads a `SystemDocument` from a JSON file.
pub fn read_document(path: impl AsRef<Path>) -> Result<SystemDocument, DocumentError> {
    parse_document(&fs::read_to_string(path)?)
}

/// Renders `doc` as JSON with two-space indentation and a trailing newline,
/// stamped with this crate's schema version.
pub fn document_to_string(doc: &SystemDocument) -> Result<String, DocumentError> {
    document_to_string_with_indent(doc, DEFAULT_INDENT)
}

/// Renders `doc` as JSON with `indent` spaces per level and a trailing newline,
/// stamped with this crate's schema version.
pub fn document_to_string_with_indent(
    doc: &SystemDocument,
    indent: usize,
) -> Result<String, DocumentError> {
    encode(
        current_schema_version(),
        &default_bundles(),
        doc,
        SchemaVersionTarget::Current,
        indent,
    )
}

/// Writes `doc` to `path`, with `components` keys sorted for deterministic
/// output; the schema requires the same. [`SchemaVersionTarget::Source`] looks
/// for strict bundles in this crate's `bundles/` directory; use
/// [`write_document_with_bundles`] when that directory is not where the crate was
/// built.
pub fn write_document(
    doc: &SystemDocument,
    path: impl AsRef<Path>,
    target: SchemaVersionTarget,
) -> Result<(), DocumentError> {
    write_document_with_bundles(doc, path, target, default_bundles())
}

/// [`write_document`] reading strict bundles from `bundles/<version>/` under
/// `bundles`.
pub fn write_document_with_bundles(
    doc: &SystemDocument,
    path: impl AsRef<Path>,
    target: SchemaVersionTarget,
    bundles: impl AsRef<Path>,
) -> Result<(), DocumentError> {
    write_document_for(current_schema_version(), bundles, doc, path, target)
}

/// [`write_document_with_bundles`] for an explicit reader version.
#[doc(hidden)]
pub fn write_document_for(
    reader: &str,
    bundles: impl AsRef<Path>,
    doc: &SystemDocument,
    path: impl AsRef<Path>,
    target: SchemaVersionTarget,
) -> Result<(), DocumentError> {
    let text = encode(reader, bundles.as_ref(), doc, target, DEFAULT_INDENT)?;
    fs::write(path, text)?;
    Ok(())
}

/// Reads `src` and writes it to `dst` stamped with this crate's schema version.
/// Only `current` and `upgradable` documents succeed. An existing `dst` is an
/// error unless `force`.
pub fn upgrade_document(
    src: impl AsRef<Path>,
    dst: impl AsRef<Path>,
    force: bool,
) -> Result<(), DocumentError> {
    refuse_overwrite(dst.as_ref(), force)?;
    write_document(&read_document(src)?, dst, SchemaVersionTarget::Current)
}

/// Parses a `PortfolioDocument` from JSON text and validates it. Same version
/// rules as [`parse_document`].
pub fn parse_portfolio_document(text: &str) -> Result<PortfolioDocument, DocumentError> {
    parse_for(current_schema_version(), text)
}

/// [`parse_portfolio_document`] for an explicit reader version.
#[doc(hidden)]
pub fn parse_portfolio_document_for(
    reader: &str,
    text: &str,
) -> Result<PortfolioDocument, DocumentError> {
    parse_for(reader, text)
}

/// Reads a `PortfolioDocument` from a JSON file.
pub fn read_portfolio_document(path: impl AsRef<Path>) -> Result<PortfolioDocument, DocumentError> {
    parse_portfolio_document(&fs::read_to_string(path)?)
}

/// Renders `doc` as JSON with two-space indentation and a trailing newline,
/// stamped with this crate's schema version.
pub fn portfolio_document_to_string(doc: &PortfolioDocument) -> Result<String, DocumentError> {
    encode(
        current_schema_version(),
        &default_bundles(),
        doc,
        SchemaVersionTarget::Current,
        DEFAULT_INDENT,
    )
}

/// Writes `doc` to `path`. Same rules as [`write_document`].
pub fn write_portfolio_document(
    doc: &PortfolioDocument,
    path: impl AsRef<Path>,
    target: SchemaVersionTarget,
) -> Result<(), DocumentError> {
    write_portfolio_document_with_bundles(doc, path, target, default_bundles())
}

/// [`write_portfolio_document`] reading strict bundles from `bundles/<version>/`
/// under `bundles`.
pub fn write_portfolio_document_with_bundles(
    doc: &PortfolioDocument,
    path: impl AsRef<Path>,
    target: SchemaVersionTarget,
    bundles: impl AsRef<Path>,
) -> Result<(), DocumentError> {
    write_portfolio_document_for(current_schema_version(), bundles, doc, path, target)
}

/// [`write_portfolio_document_with_bundles`] for an explicit reader version.
#[doc(hidden)]
pub fn write_portfolio_document_for(
    reader: &str,
    bundles: impl AsRef<Path>,
    doc: &PortfolioDocument,
    path: impl AsRef<Path>,
    target: SchemaVersionTarget,
) -> Result<(), DocumentError> {
    let text = encode(reader, bundles.as_ref(), doc, target, DEFAULT_INDENT)?;
    fs::write(path, text)?;
    Ok(())
}

/// Reads the portfolio at `src` and writes it to `dst`. Same rules as
/// [`upgrade_document`].
pub fn upgrade_portfolio_document(
    src: impl AsRef<Path>,
    dst: impl AsRef<Path>,
    force: bool,
) -> Result<(), DocumentError> {
    refuse_overwrite(dst.as_ref(), force)?;
    write_portfolio_document(
        &read_portfolio_document(src)?,
        dst,
        SchemaVersionTarget::Current,
    )
}
