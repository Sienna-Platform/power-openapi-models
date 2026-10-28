//! Hand-written (NOT generated): the types of `format: date-time` and
//! `format: date-time-local` fields.
//!
//! chrono parses more than RFC 3339: its serde impl for `DateTime` accepts a space or a
//! lowercase `t` as the separator, nine fractional digits, an offset without a colon, and
//! a trailing newline. The schemas allow only the RFC 3339 forms, with uppercase `T` and
//! `Z` and at most three fractional digits. These types parse the same forms as the
//! schema `pattern`, and write at most milliseconds, with `Z` for a zero offset.
//!
//! - [`OffsetDateTime`]: `date-time`, with `Z` or a UTC offset. It keeps the offset.
//! - [`LocalDateTime`]: `date-time-local`, with no offset. A wall clock, which names no
//!   instant.
//! - [`Timestamp`]: a field that takes either form, such as a series' `initial_timestamp`.
//!
//! `codegen/rust/gen` (`rfc3339_timestamps`) gives the generated fields these types.

use std::fmt;
use std::str::FromStr;

use chrono::{DateTime, FixedOffset, NaiveDateTime, Timelike};
use serde::{de, Deserialize, Deserializer, Serialize, Serializer};

/// An RFC 3339 `date-time`: a timestamp with `Z` or a UTC offset.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct OffsetDateTime(pub DateTime<FixedOffset>);

/// An RFC 3339 `date-time-local`: a timestamp with no offset, a wall clock.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct LocalDateTime(pub NaiveDateTime);

/// A field that takes either RFC 3339 form. The text decides which.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Timestamp {
    Offset(OffsetDateTime),
    Local(LocalDateTime),
}

/// `YYYY-MM-DDTHH:MM:SS`, then an optional `.` and 1 to 3 digits. Returns the length of
/// that clock prefix, or `None` when `text` does not start with one.
fn clock_len(text: &[u8]) -> Option<usize> {
    const SHAPE: &[u8; 19] = b"dddd-dd-ddTdd:dd:dd";
    if text.len() < SHAPE.len() {
        return None;
    }
    for (byte, want) in text.iter().zip(SHAPE) {
        let ok = match want {
            b'd' => byte.is_ascii_digit(),
            other => byte == other,
        };
        if !ok {
            return None;
        }
    }
    if text.get(19) != Some(&b'.') {
        return Some(19);
    }
    let digits = text[20..].iter().take_while(|b| b.is_ascii_digit()).count();
    if digits == 0 || digits > 3 {
        return None;
    }
    Some(20 + digits)
}

/// `Z`, or `+HH:MM` / `-HH:MM`.
fn is_offset(text: &[u8]) -> bool {
    match text {
        b"Z" => true,
        [sign, h1, h2, b':', m1, m2] => {
            matches!(sign, b'+' | b'-') && [h1, h2, m1, m2].iter().all(|b| b.is_ascii_digit())
        }
        _ => false,
    }
}

fn parse_local(text: &str) -> Result<NaiveDateTime, String> {
    NaiveDateTime::parse_from_str(text, "%Y-%m-%dT%H:%M:%S%.f")
        .map_err(|e| format!("{text:?} is not an RFC 3339 timestamp: {e}"))
}

fn parse_offset(text: &str) -> Result<DateTime<FixedOffset>, String> {
    DateTime::parse_from_rfc3339(text)
        .map_err(|e| format!("{text:?} is not an RFC 3339 date-time: {e}"))
}

impl FromStr for Timestamp {
    type Err = String;

    fn from_str(text: &str) -> Result<Self, String> {
        let Some(end) = clock_len(text.as_bytes()) else {
            return Err(format!(
                "{text:?} is not an RFC 3339 timestamp: expected YYYY-MM-DDTHH:MM:SS \
                 with at most 3 fractional digits"
            ));
        };
        let rest = &text.as_bytes()[end..];
        if rest.is_empty() {
            return parse_local(text).map(|t| Timestamp::Local(LocalDateTime(t)));
        }
        if is_offset(rest) {
            return parse_offset(text).map(|t| Timestamp::Offset(OffsetDateTime(t)));
        }
        Err(format!(
            "{text:?} is not an RFC 3339 timestamp: expected no offset, `Z`, or `+HH:MM`/`-HH:MM`"
        ))
    }
}

impl FromStr for OffsetDateTime {
    type Err = String;

    fn from_str(text: &str) -> Result<Self, String> {
        match text.parse::<Timestamp>()? {
            Timestamp::Offset(t) => Ok(t),
            Timestamp::Local(_) => Err(format!("{text:?} has no offset; a date-time needs one")),
        }
    }
}

impl FromStr for LocalDateTime {
    type Err = String;

    fn from_str(text: &str) -> Result<Self, String> {
        match text.parse::<Timestamp>()? {
            Timestamp::Local(t) => Ok(t),
            Timestamp::Offset(_) => Err(format!(
                "{text:?} has an offset; a date-time-local has none"
            )),
        }
    }
}

/// `YYYY-MM-DDTHH:MM:SS`, plus `.mmm` when the value has a sub-second part.
fn write_clock(f: &mut fmt::Formatter<'_>, clock: &NaiveDateTime) -> fmt::Result {
    write!(f, "{}", clock.format("%Y-%m-%dT%H:%M:%S"))?;
    if clock.nanosecond() != 0 {
        write!(f, ".{:03}", clock.nanosecond() / 1_000_000)?;
    }
    Ok(())
}

impl fmt::Display for OffsetDateTime {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write_clock(f, &self.0.naive_local())?;
        let seconds = self.0.offset().local_minus_utc();
        if seconds == 0 {
            return f.write_str("Z");
        }
        let sign = if seconds < 0 { '-' } else { '+' };
        let minutes = seconds.abs() / 60;
        write!(f, "{sign}{:02}:{:02}", minutes / 60, minutes % 60)
    }
}

impl fmt::Display for LocalDateTime {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write_clock(f, &self.0)
    }
}

impl fmt::Display for Timestamp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Timestamp::Offset(t) => t.fmt(f),
            Timestamp::Local(t) => t.fmt(f),
        }
    }
}

/// Serialization fails for a sub-millisecond part, which no schema form can hold.
fn checked_precision<E: serde::ser::Error>(clock: &NaiveDateTime) -> Result<(), E> {
    if clock.nanosecond() % 1_000_000 != 0 {
        return Err(E::custom(format!(
            "{clock} has a sub-millisecond part; the schema allows at most 3 fractional digits"
        )));
    }
    Ok(())
}

impl Serialize for OffsetDateTime {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        checked_precision(&self.0.naive_local())?;
        serializer.collect_str(self)
    }
}

impl Serialize for LocalDateTime {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        checked_precision(&self.0)?;
        serializer.collect_str(self)
    }
}

impl Serialize for Timestamp {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self {
            Timestamp::Offset(t) => t.serialize(serializer),
            Timestamp::Local(t) => t.serialize(serializer),
        }
    }
}

fn deserialize_text<'de, D, T>(deserializer: D) -> Result<T, D::Error>
where
    D: Deserializer<'de>,
    T: FromStr<Err = String>,
{
    let text = String::deserialize(deserializer)?;
    text.parse().map_err(de::Error::custom)
}

impl<'de> Deserialize<'de> for OffsetDateTime {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserialize_text(deserializer)
    }
}

impl<'de> Deserialize<'de> for LocalDateTime {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserialize_text(deserializer)
    }
}

impl<'de> Deserialize<'de> for Timestamp {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserialize_text(deserializer)
    }
}
