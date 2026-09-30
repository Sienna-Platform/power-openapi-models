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
//! Writing follows the Python package's rules: top-level keys and `components`
//! keys sorted, everything else in input order, a trailing newline, and an
//! omitted optional field stays omitted. Optional fields that Python defaults
//! (`trading_hub_associations`, `ext`) are `Option`s here for that reason:
//! `None` means "the input did not carry it", so read then write reproduces a
//! document byte for byte. The one exception is a row type with schema
//! defaults (`PortfolioFinancialData`'s three rates), which serde cannot tell
//! apart from explicit values and so writes out.

use std::collections::BTreeMap;
use std::fmt;
use std::fs;
use std::path::Path;

use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{Map, Value};

use crate::infrastructure_core::SupplementalAttributeAssociation;
use crate::investments::{PortfolioFinancialData, RequirementAssociation};
use crate::operations::{
    CombinedCycleAssociation, PlantAssociation, ServiceAssociation, TradingHubAssociation,
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
}

impl fmt::Display for DocumentError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(f, "{error}"),
            Self::Json(error) => write!(f, "{error}"),
            Self::Invalid(message) => write!(f, "{message}"),
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
/// Fields are declared in sorted key order: that is the order they are written.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SystemDocument {
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
    /// association arrays, so older documents omit it.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub trading_hub_associations: Option<Vec<TradingHubAssociation>>,
}

impl SystemDocument {
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
/// Fields are declared in sorted key order: that is the order they are written.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PortfolioDocument {
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
    /// Checks the constraints the schema states beyond shape.
    pub fn validate(&self) -> Result<(), DocumentError> {
        validate_ext(&self.ext)
    }
}

const DEFAULT_INDENT: usize = 2;

fn render<T: Serialize>(doc: &T, indent: usize) -> Result<String, DocumentError> {
    let indent_bytes = vec![b' '; indent];
    let formatter = serde_json::ser::PrettyFormatter::with_indent(&indent_bytes);
    let mut buffer = Vec::new();
    let mut serializer = serde_json::Serializer::with_formatter(&mut buffer, formatter);
    doc.serialize(&mut serializer)?;
    let mut text = String::from_utf8(buffer).expect("serde_json emits UTF-8");
    text.push('\n');
    Ok(text)
}

/// Parses a `SystemDocument` from JSON text and validates it.
pub fn parse_document(text: &str) -> Result<SystemDocument, DocumentError> {
    let doc: SystemDocument = serde_json::from_str(text)?;
    doc.validate()?;
    Ok(doc)
}

/// Reads a `SystemDocument` from a JSON file.
pub fn read_document(path: impl AsRef<Path>) -> Result<SystemDocument, DocumentError> {
    parse_document(&fs::read_to_string(path)?)
}

/// Renders `doc` as JSON with two-space indentation and a trailing newline.
pub fn document_to_string(doc: &SystemDocument) -> Result<String, DocumentError> {
    document_to_string_with_indent(doc, DEFAULT_INDENT)
}

/// Renders `doc` as JSON with `indent` spaces per level and a trailing newline.
pub fn document_to_string_with_indent(
    doc: &SystemDocument,
    indent: usize,
) -> Result<String, DocumentError> {
    doc.validate()?;
    render(doc, indent)
}

/// Writes `doc` to `path`, with `components` keys sorted for deterministic
/// output; the schema requires the same.
pub fn write_document(doc: &SystemDocument, path: impl AsRef<Path>) -> Result<(), DocumentError> {
    fs::write(path, document_to_string(doc)?)?;
    Ok(())
}

/// Parses a `PortfolioDocument` from JSON text and validates it.
pub fn parse_portfolio_document(text: &str) -> Result<PortfolioDocument, DocumentError> {
    let doc: PortfolioDocument = serde_json::from_str(text)?;
    doc.validate()?;
    Ok(doc)
}

/// Reads a `PortfolioDocument` from a JSON file.
pub fn read_portfolio_document(path: impl AsRef<Path>) -> Result<PortfolioDocument, DocumentError> {
    parse_portfolio_document(&fs::read_to_string(path)?)
}

/// Renders `doc` as JSON with two-space indentation and a trailing newline.
pub fn portfolio_document_to_string(doc: &PortfolioDocument) -> Result<String, DocumentError> {
    doc.validate()?;
    render(doc, DEFAULT_INDENT)
}

/// Writes `doc` to `path`. Same rules as [`write_document`].
pub fn write_portfolio_document(
    doc: &PortfolioDocument,
    path: impl AsRef<Path>,
) -> Result<(), DocumentError> {
    fs::write(path, portfolio_document_to_string(doc)?)?;
    Ok(())
}
