//! Hand-written (NOT generated): the type of every `format: date-time` field.
//!
//! The schemas say RFC 3339, which requires an offset, and `chrono` alone rejects
//! `2024-01-01T00:00:00`. Real producers write timestamps without an offset, so all
//! three packages (Python, TypeScript, Rust) accept one. A timestamp is kept as
//! written: no offset gives [`Timestamp::Zoneless`], and an offset gives
//! [`Timestamp::Offset`] with that offset. The crate does not assume a zone; a
//! series' `time_reference` says how to read its timestamps. Anything else -- a date
//! with no time, or text that is not a timestamp -- is rejected.
//!
//! `codegen/rust/gen` (`lenient_timestamps`) gives the generated fields this type.

use std::fmt;

use chrono::{DateTime, FixedOffset, NaiveDateTime, SecondsFormat};
use serde::{de, Deserialize, Deserializer, Serialize, Serializer};

/// A timestamp as written: an instant with its offset, or a wall clock.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Timestamp {
    /// Written with `Z` or a UTC offset. Keeps that offset.
    Offset(DateTime<FixedOffset>),
    /// Written with no offset. A wall clock, which names no instant.
    Zoneless(NaiveDateTime),
}

/// Parses an RFC 3339 timestamp, or the same without an offset.
pub fn parse(text: &str) -> Result<Timestamp, String> {
    if let Ok(with_offset) = DateTime::parse_from_rfc3339(text) {
        return Ok(Timestamp::Offset(with_offset));
    }
    let has_time = matches!(text.as_bytes().get(10), Some(b'T' | b't'));
    if has_time {
        if let Ok(naive) = text.parse::<NaiveDateTime>() {
            return Ok(Timestamp::Zoneless(naive));
        }
    }
    Err(format!(
        "{text:?} is not a timestamp: expected RFC 3339, with or without an offset"
    ))
}

/// The wire form: an offset (`Z` for UTC) only when one was written.
impl fmt::Display for Timestamp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Timestamp::Offset(at) => f.write_str(&at.to_rfc3339_opts(SecondsFormat::AutoSi, true)),
            Timestamp::Zoneless(clock) => write!(f, "{}", clock.format("%Y-%m-%dT%H:%M:%S%.f")),
        }
    }
}

impl Serialize for Timestamp {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for Timestamp {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let text = String::deserialize(deserializer)?;
        parse(&text).map_err(de::Error::custom)
    }
}
