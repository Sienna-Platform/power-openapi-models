//! Hand-written (NOT generated): how `format: date-time` fields are read and
//! written.
//!
//! The schemas say RFC 3339, which requires an offset, and `chrono` alone rejects
//! `2024-01-01T00:00:00`. Real producers write timestamps without an offset, so all
//! three packages (Python, TypeScript, Rust) accept one and read it as UTC. An
//! offset, when present, is honoured and the value is normalized to UTC. Anything
//! else -- a date with no time, or text that is not a timestamp -- is rejected.
//! Values are always written with an explicit offset (`Z`).
//!
//! `codegen/rust/gen` (`lenient_timestamps`) attaches these functions to the
//! generated fields with `#[serde(with = ...)]`.

use chrono::{DateTime, NaiveDateTime, Utc};
use serde::{de, Deserialize, Deserializer, Serialize, Serializer};

/// Parses an RFC 3339 timestamp, or the same without an offset, read as UTC.
pub fn parse(text: &str) -> Result<DateTime<Utc>, String> {
    if let Ok(with_offset) = DateTime::parse_from_rfc3339(text) {
        return Ok(with_offset.with_timezone(&Utc));
    }
    let has_time = matches!(text.as_bytes().get(10), Some(b'T' | b't'));
    if has_time {
        if let Ok(naive) = text.parse::<NaiveDateTime>() {
            return Ok(naive.and_utc());
        }
    }
    Err(format!(
        "{text:?} is not a timestamp: expected RFC 3339, with or without an offset"
    ))
}

struct Wire(DateTime<Utc>);

impl<'de> Deserialize<'de> for Wire {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let text = String::deserialize(deserializer)?;
        parse(&text).map(Wire).map_err(de::Error::custom)
    }
}

pub fn deserialize<'de, D: Deserializer<'de>>(deserializer: D) -> Result<DateTime<Utc>, D::Error> {
    Wire::deserialize(deserializer).map(|wire| wire.0)
}

pub fn serialize<S: Serializer>(value: &DateTime<Utc>, serializer: S) -> Result<S::Ok, S::Error> {
    value.serialize(serializer)
}

/// For `Option<DateTime<Utc>>` fields.
pub mod option {
    use super::*;

    pub fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Option<DateTime<Utc>>, D::Error> {
        Option::<Wire>::deserialize(deserializer).map(|wire| wire.map(|w| w.0))
    }

    pub fn serialize<S: Serializer>(
        value: &Option<DateTime<Utc>>,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        value.serialize(serializer)
    }
}

/// For `Option<Option<DateTime<Utc>>>` fields: absent is `None`, an explicit
/// `null` is `Some(None)`. Mirrors the generated `tri_state_serde`.
pub fn deserialize_tri_state<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<Option<DateTime<Utc>>>, D::Error> {
    Option::<Wire>::deserialize(deserializer).map(|wire| Some(wire.map(|w| w.0)))
}
