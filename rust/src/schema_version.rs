//! Hand-written (NOT generated): the schema-version reader rule from SiennaSchemas'
//! `docs/VERSIONING.md`, and the strict-bundle check behind `schema_version = source`.
//!
//! Counterpart of the Python, TypeScript and Julia packages; all agree on the shared
//! vectors in `versioning/cases.json`.

use std::cmp::Ordering;
use std::fmt;

use serde_json::Value;

use crate::document::DocumentError;

/// How a document's `schema_version` relates to the reader's.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SchemaVersionOutcome {
    Missing,
    Malformed,
    Incompatible,
    Newer,
    Upgradable,
    Current,
}

impl SchemaVersionOutcome {
    /// Whether a reader decodes the document.
    pub fn is_readable(self) -> bool {
        matches!(self, Self::Upgradable | Self::Current)
    }
}

impl fmt::Display for SchemaVersionOutcome {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Missing => "missing",
            Self::Malformed => "malformed",
            Self::Incompatible => "incompatible",
            Self::Newer => "newer",
            Self::Upgradable => "upgradable",
            Self::Current => "current",
        })
    }
}

/// Components stay digit strings: the pattern forbids leading zeros, so ordering by
/// (length, text) is numeric ordering without a size limit.
#[derive(PartialEq, Eq)]
struct Version<'a> {
    numbers: [&'a str; 3],
    prerelease: Option<&'a str>,
}

impl Version<'_> {
    fn line(&self) -> String {
        let [major, minor, _] = self.numbers;
        if major == "0" {
            format!("0.{minor}")
        } else {
            major.to_owned()
        }
    }

    fn key(&self) -> [(usize, &str); 3] {
        self.numbers.map(|n| (n.len(), n))
    }
}

fn number(part: &str) -> Option<&str> {
    if part.is_empty() || (part.len() > 1 && part.starts_with('0')) {
        return None;
    }
    if !part.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    Some(part)
}

/// `^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?$`
fn parse(text: &str) -> Option<Version<'_>> {
    let (core, prerelease) = match text.split_once('-') {
        Some((core, pre)) => (core, Some(pre)),
        None => (text, None),
    };
    if let Some(pre) = prerelease {
        if pre.is_empty()
            || !pre
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'-')
        {
            return None;
        }
    }
    let mut parts = core.split('.');
    let numbers = [
        number(parts.next()?)?,
        number(parts.next()?)?,
        number(parts.next()?)?,
    ];
    if parts.next().is_some() {
        return None;
    }
    Some(Version {
        numbers,
        prerelease,
    })
}

fn known(text: &str) -> Version<'_> {
    parse(text).unwrap_or_else(|| panic!("schema version {text:?} is not a version"))
}

/// The schema version this crate reads and writes: [`crate::SCHEMA_VERSION`] without
/// its leading `v`.
pub fn current_schema_version() -> &'static str {
    let version = crate::SCHEMA_VERSION;
    version.strip_prefix('v').unwrap_or(version)
}

/// Applies the reader rule to the raw parsed document, before any decode. A
/// non-object root is a [`DocumentError::Invalid`], as reading it is.
pub fn check_schema_version(raw: &Value) -> Result<SchemaVersionOutcome, DocumentError> {
    check_schema_version_for(current_schema_version(), raw)
}

/// [`check_schema_version`] for an explicit reader version. Panics when `reader` is
/// not a version.
#[doc(hidden)]
pub fn check_schema_version_for(
    reader: &str,
    raw: &Value,
) -> Result<SchemaVersionOutcome, DocumentError> {
    let Some(object) = raw.as_object() else {
        return Err(DocumentError::Invalid(
            "document must be a JSON object".to_owned(),
        ));
    };
    let Some(stamp) = object.get("schema_version") else {
        return Ok(SchemaVersionOutcome::Missing);
    };
    let Some(document) = stamp.as_str().and_then(parse) else {
        return Ok(SchemaVersionOutcome::Malformed);
    };
    let reader = known(reader);
    if (document.prerelease.is_some() || reader.prerelease.is_some()) && document != reader {
        return Ok(SchemaVersionOutcome::Incompatible);
    }
    if document.line() != reader.line() {
        return Ok(SchemaVersionOutcome::Incompatible);
    }
    Ok(match document.key().cmp(&reader.key()) {
        Ordering::Greater => SchemaVersionOutcome::Newer,
        Ordering::Less => SchemaVersionOutcome::Upgradable,
        Ordering::Equal => SchemaVersionOutcome::Current,
    })
}

/// The canonical text for an error outcome. `document` is the raw `schema_version`
/// value (`null` when absent).
pub(crate) fn message(outcome: SchemaVersionOutcome, reader: &str, document: &Value) -> String {
    let text = document.as_str().unwrap_or_default();
    match outcome {
        SchemaVersionOutcome::Missing => "document has no schema_version: it predates \
            versioning; re-export it with a current producer (psy5 bundles: PowerSystemsUpdater)"
            .to_owned(),
        SchemaVersionOutcome::Malformed => {
            format!("document schema_version {document} is not a valid version")
        }
        SchemaVersionOutcome::Incompatible => {
            let (d, r) = (known(text), known(reader));
            if d.prerelease.is_some() || r.prerelease.is_some() {
                format!(
                    "document written by schema {text} cannot be read by schema {reader}: \
                     dev builds read only their own output"
                )
            } else {
                format!(
                    "document written by schema {text} (line {}) cannot be read by schema \
                     {reader} (line {}): documents do not cross compatibility lines; \
                     migrating between lines is a separate upgrade tool's job \
                     (psy5 bundles: PowerSystemsUpdater)",
                    d.line(),
                    r.line()
                )
            }
        }
        SchemaVersionOutcome::Newer => format!(
            "document written by schema {text}; this reader understands up to {reader}; \
             update the model package to one built from >= {text}"
        ),
        SchemaVersionOutcome::Upgradable | SchemaVersionOutcome::Current => {
            unreachable!("{outcome} is not an error")
        }
    }
}

/// Every instance path in `tree` that the bundle at `bundle` rejects, as
/// `/json/pointer: reason`. An unexpected property is reported at its own path.
#[cfg(feature = "source-version")]
pub(crate) fn bundle_violations(
    bundle: &std::path::Path,
    tree: &Value,
) -> Result<Vec<String>, crate::document::DocumentError> {
    use crate::document::DocumentError;
    let fail = |message: String| DocumentError::SourceVersion {
        message,
        paths: Vec::new(),
    };
    let text = std::fs::read_to_string(bundle)
        .map_err(|e| fail(format!("strict bundle {}: {e}", bundle.display())))?;
    let schema: Value = serde_json::from_str(&text)
        .map_err(|e| fail(format!("strict bundle {}: {e}", bundle.display())))?;
    let validator = jsonschema::draft7::new(&schema)
        .map_err(|e| fail(format!("strict bundle {}: {e}", bundle.display())))?;

    let mut violations = Vec::new();
    for error in validator.iter_errors(tree) {
        leaves(&error, &mut violations);
    }
    violations.sort();
    violations.dedup();
    Ok(violations)
}

/// Pushes the offending `/json/pointer: reason` entries under one error. A failed
/// `anyOf`/`oneOf` descends into its closest branch, the one with the fewest leaves.
#[cfg(feature = "source-version")]
fn leaves(error: &jsonschema::ValidationError<'_>, out: &mut Vec<String>) {
    use jsonschema::error::ValidationErrorKind;

    match error.kind() {
        ValidationErrorKind::AnyOf { context } | ValidationErrorKind::OneOfNotValid { context } => {
            let mut closest: Option<Vec<String>> = None;
            for branch in context {
                let mut found = Vec::new();
                for inner in branch {
                    leaves(inner, &mut found);
                }
                if closest.as_ref().is_none_or(|best| found.len() < best.len()) {
                    closest = Some(found);
                }
            }
            match closest {
                Some(found) if !found.is_empty() => out.extend(found),
                _ => out.push(format!("{}: {error}", error.instance_path())),
            }
        }
        ValidationErrorKind::AdditionalProperties { unexpected } => {
            let at = error.instance_path().to_string();
            for property in unexpected {
                out.push(format!("{at}/{property}: unknown property"));
            }
        }
        _ => out.push(format!("{}: {error}", error.instance_path())),
    }
}
