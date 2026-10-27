//! `format: date-time` fields accept a timestamp with or without an offset and keep
//! it as written, as the Python and TypeScript packages do. See `src/timestamp.rs`.

use chrono::{FixedOffset, NaiveDate, TimeZone};
use power_openapi_models::generated::{DataSource, SingleTimeSeries};
use power_openapi_models::timestamp::{self, Timestamp};
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

fn initial(timestamp: &str) -> Result<Timestamp, serde_json::Error> {
    serde_json::from_value::<SingleTimeSeries>(series(timestamp)).map(|s| s.initial_timestamp)
}

fn midnight() -> chrono::NaiveDateTime {
    NaiveDate::from_ymd_opt(2024, 1, 1)
        .unwrap()
        .and_hms_opt(0, 0, 0)
        .unwrap()
}

#[test]
fn naive_timestamp_stays_zoneless() {
    assert_eq!(
        initial("2024-01-01T00:00:00").unwrap(),
        Timestamp::Zoneless(midnight())
    );
}

#[test]
fn naive_fractional_seconds() {
    let Timestamp::Zoneless(clock) = initial("2024-01-01T00:00:00.250").unwrap() else {
        panic!("expected a zoneless timestamp");
    };
    assert_eq!(clock.and_utc().timestamp_subsec_millis(), 250);
}

#[test]
fn z_and_offsets_are_kept() {
    let Timestamp::Offset(z) = initial("2024-01-01T00:00:00Z").unwrap() else {
        panic!("expected an offset");
    };
    assert_eq!(z.offset().local_minus_utc(), 0);
    let Timestamp::Offset(plus) = initial("2024-01-01T02:00:00+02:00").unwrap() else {
        panic!("expected an offset");
    };
    assert_eq!(plus.offset().local_minus_utc(), 2 * 3600);
    assert_eq!(
        plus,
        FixedOffset::east_opt(0)
            .unwrap()
            .from_utc_datetime(&midnight())
    );
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
fn round_trip_keeps_the_spelling() {
    for written in [
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00.250",
        "2024-01-01T00:00:00Z",
        "2024-01-01T02:00:00+02:00",
        "2024-01-01T00:00:00-07:00",
    ] {
        let parsed: SingleTimeSeries = serde_json::from_value(series(written)).unwrap();
        assert_eq!(
            serde_json::to_value(&parsed).unwrap()["initial_timestamp"],
            written
        );
    }
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
        Some(Some(Timestamp::Zoneless(
            NaiveDate::from_ymd_opt(2024, 2, 1)
                .unwrap()
                .and_hms_opt(0, 0, 0)
                .unwrap()
        )))
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
