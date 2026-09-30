//! `format: date-time` fields accept a timestamp with no offset, read as UTC, as
//! the Python and TypeScript packages do. See `src/timestamp.rs`.

use chrono::{TimeZone, Utc};
use power_openapi_models::generated::{DataSource, SingleTimeSeries};
use power_openapi_models::timestamp;
use serde_json::{json, Value};

fn series(timestamp: &str) -> Value {
    json!({
        "association_id": 1, "owner_id": 2, "owner_type": "ACBus",
        "owner_category": "Component", "time_series_type": "SingleTimeSeries",
        "name": "max_active_power", "features": {}, "uri": "abc123",
        "element_type": "f64", "element_shape": [],
        "initial_timestamp": timestamp, "resolution": "PT1H", "length": 24
    })
}

fn initial(timestamp: &str) -> Result<chrono::DateTime<Utc>, serde_json::Error> {
    serde_json::from_value::<SingleTimeSeries>(series(timestamp)).map(|s| s.initial_timestamp)
}

#[test]
fn naive_timestamp_is_read_as_utc() {
    assert_eq!(
        initial("2024-01-01T00:00:00").unwrap(),
        Utc.with_ymd_and_hms(2024, 1, 1, 0, 0, 0).unwrap()
    );
}

#[test]
fn naive_fractional_seconds() {
    let ts = initial("2024-01-01T00:00:00.250").unwrap();
    assert_eq!(ts.timestamp_subsec_millis(), 250);
}

#[test]
fn z_and_offsets_are_honoured_and_normalized_to_utc() {
    let midnight = Utc.with_ymd_and_hms(2024, 1, 1, 0, 0, 0).unwrap();
    assert_eq!(initial("2024-01-01T00:00:00Z").unwrap(), midnight);
    assert_eq!(initial("2024-01-01T02:00:00+02:00").unwrap(), midnight);
}

#[test]
fn non_timestamps_are_still_rejected() {
    for bad in [
        "2024-01-01",
        "not a timestamp",
        "",
        "2024-13-01T00:00:00",
        "2024-01-01 00:00:00",
    ] {
        let error = initial(bad).expect_err(bad);
        assert!(
            error.to_string().contains("not a timestamp"),
            "{bad}: {error}"
        );
    }
}

#[test]
fn written_timestamp_always_carries_an_offset() {
    let parsed: SingleTimeSeries = serde_json::from_value(series("2024-01-01T00:00:00")).unwrap();
    assert_eq!(
        serde_json::to_value(&parsed).unwrap()["initial_timestamp"],
        "2024-01-01T00:00:00Z"
    );
}

#[test]
fn nullable_field_is_tri_state() {
    let base = json!({"id": 1, "fields": [], "retrieved_at": "2024-01-01T00:00:00"});
    let with = |published: Value| -> DataSource {
        let mut doc = base.clone();
        doc["published_at"] = published;
        serde_json::from_value(doc).unwrap_or_else(|e| panic!("{e}"))
    };
    let set = with(json!("2024-02-01T00:00:00"));
    assert_eq!(
        set.published_at,
        Some(Some(Utc.with_ymd_and_hms(2024, 2, 1, 0, 0, 0).unwrap()))
    );
    assert_eq!(with(json!(null)).published_at, Some(None));
    let absent: DataSource = serde_json::from_value(base).unwrap();
    assert_eq!(absent.published_at, None);
}

#[test]
fn parse_is_public_for_callers_holding_a_bare_string() {
    assert!(timestamp::parse("2024-01-01T00:00:00").is_ok());
    assert!(timestamp::parse("2024-01-01").is_err());
}
