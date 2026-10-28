//! `format: date-time` and `format: date-time-local` fields accept the RFC 3339 forms
//! only, and write the same forms. See `src/timestamp.rs`.

use chrono::{NaiveDate, Timelike};
use power_openapi_models::generated::{DataSource, SingleTimeSeries};
use power_openapi_models::timestamp::{LocalDateTime, OffsetDateTime, Timestamp};
use serde_json::{json, Value};

const NOT_RFC3339: [&str; 11] = [
    "2024-01-01",
    "not a timestamp",
    "",
    "2024-13-01T00:00:00Z",
    "2024-01-01 00:00:00Z",
    "2024-01-01t00:00:00z",
    "2024-01-01T00:00Z",
    "2024-01-01T00:00:00.123456Z",
    "2024-01-01T00:00:00+0200",
    "2024-01-01T00:00:00Z\n",
    "\u{0662}024-01-01T00:00:00Z",
];

#[test]
fn offset_form_round_trips_and_keeps_the_offset() {
    for written in [
        "2024-01-01T00:00:00Z",
        "2024-01-01T02:00:00+02:00",
        "2024-01-01T00:00:00.250-07:00",
    ] {
        let parsed: OffsetDateTime = written.parse().unwrap();
        assert_eq!(parsed.to_string(), written);
    }
    let plus: OffsetDateTime = "2024-01-01T02:00:00+02:00".parse().unwrap();
    assert_eq!(plus.0.offset().local_minus_utc(), 2 * 3600);
    let zero: OffsetDateTime = "2024-01-01T00:00:00+00:00".parse().unwrap();
    assert_eq!(zero.to_string(), "2024-01-01T00:00:00Z");
}

#[test]
fn local_form_round_trips() {
    for written in ["2024-01-01T00:00:00", "2024-01-01T00:00:00.250"] {
        let parsed: LocalDateTime = written.parse().unwrap();
        assert_eq!(parsed.to_string(), written);
    }
    let parsed: LocalDateTime = "2024-01-01T00:00:00.250".parse().unwrap();
    assert_eq!(parsed.0.nanosecond(), 250_000_000);
}

#[test]
fn either_form_is_chosen_by_the_text() {
    assert!(matches!(
        "2024-01-01T00:00:00".parse::<Timestamp>().unwrap(),
        Timestamp::Local(_)
    ));
    assert!(matches!(
        "2024-01-01T00:00:00Z".parse::<Timestamp>().unwrap(),
        Timestamp::Offset(_)
    ));
}

#[test]
fn everything_else_is_rejected() {
    for bad in NOT_RFC3339 {
        assert!(bad.parse::<Timestamp>().is_err(), "{bad:?}");
    }
    assert!("2024-01-01T00:00:00".parse::<OffsetDateTime>().is_err());
    assert!("2024-01-01T00:00:00Z".parse::<LocalDateTime>().is_err());
}

#[test]
fn sub_millisecond_values_are_not_written() {
    let clock = NaiveDate::from_ymd_opt(2024, 1, 1)
        .unwrap()
        .and_hms_nano_opt(0, 0, 0, 1)
        .unwrap();
    assert!(serde_json::to_value(LocalDateTime(clock)).is_err());
}

#[test]
fn data_source_timestamps_need_an_offset() {
    let base = json!({"id": 1, "fields": [], "retrieved_at": "2024-01-01T00:00:00Z"});
    let with = |key: &str, value: Value| {
        let mut doc = base.clone();
        doc[key] = value;
        serde_json::from_value::<DataSource>(doc)
    };
    let source = with("published_at", json!(null)).unwrap();
    assert_eq!(source.published_at, Some(None));
    assert_eq!(
        serde_json::to_value(&source).unwrap()["retrieved_at"],
        "2024-01-01T00:00:00Z"
    );
    assert!(with("retrieved_at", json!("2024-01-01T00:00:00")).is_err());
    assert!(with("published_at", json!("2024-02-01T00:00:00")).is_err());
    let absent: DataSource = serde_json::from_value(base).unwrap();
    assert_eq!(absent.published_at, None);
}

fn series(timestamp: &str) -> Value {
    json!({
        "association_id": 1, "owner_id": 2, "owner_type": "ACBus",
        "owner_category": "Component", "time_series_type": "SingleTimeSeries",
        "name": "max_active_power", "features": {}, "uri": "abc123",
        "element_type": "f64", "element_shape": [],
        "initial_timestamp": timestamp, "resolution": "PT1H", "length": 24
    })
}

fn round_trip(timestamp: &str) -> Result<Value, serde_json::Error> {
    let parsed: SingleTimeSeries = serde_json::from_value(series(timestamp))?;
    Ok(serde_json::to_value(&parsed)?["initial_timestamp"].clone())
}

#[test]
fn series_timestamp_with_an_offset() {
    assert_eq!(
        round_trip("2024-01-01T02:00:00+02:00").unwrap(),
        "2024-01-01T02:00:00+02:00"
    );
    for bad in NOT_RFC3339 {
        assert!(round_trip(bad).is_err(), "{bad:?}");
    }
}

/// Schema 0.4.0 made a series' `initial_timestamp` either RFC 3339 form.
#[test]
fn series_timestamp_without_an_offset_from_schema_0_4() {
    let mut parts = power_openapi_models::SCHEMA_VERSION
        .trim_start_matches('v')
        .split('.');
    let major: u32 = parts.next().unwrap().parse().unwrap();
    let minor: u32 = parts.next().unwrap().parse().unwrap();
    if (major, minor) < (0, 4) {
        assert!(round_trip("2024-01-01T00:00:00").is_err());
        return;
    }
    assert_eq!(
        round_trip("2024-01-01T00:00:00").unwrap(),
        "2024-01-01T00:00:00"
    );
}
