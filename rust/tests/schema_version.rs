//! Schema-version reader rule and write targets (SiennaSchemas docs/VERSIONING.md).
//!
//! The shared vectors ship in `../fixtures/versioning`; the strict bundle builds
//! need a SiennaSchemas checkout: `SIENNA_SCHEMAS_DIR`, else a sibling of this repo.

use std::path::{Path, PathBuf};

use power_openapi_models::document::*;
use power_openapi_models::schema_version::*;
use serde_json::{json, Value};

const READER: &str = "0.1.1";
const OLDER: &str = "0.1.0";

fn schemas_dir() -> PathBuf {
    match std::env::var_os("SIENNA_SCHEMAS_DIR") {
        Some(dir) => PathBuf::from(dir),
        None => Path::new(env!("CARGO_MANIFEST_DIR")).join("../../SiennaSchemas"),
    }
}

fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("pom-version-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn system(stamp: Option<&str>) -> Value {
    let mut doc = json!({
        "components": {"ACBus": [{"id": 1, "name": "bus1", "available": true, "number": 1}]},
        "supplemental_attributes": [],
        "supplemental_attribute_associations": [],
        "plant_associations": [],
        "combined_cycle_associations": [],
        "service_associations": [],
        "time_series_associations": [],
        "time_series_storage_file": null
    });
    if let Some(stamp) = stamp {
        doc["schema_version"] = json!(stamp);
    }
    doc
}

fn portfolio(stamp: Option<&str>) -> Value {
    let mut doc = json!({
        "aggregation": "Area",
        "components": {"Area": [{"id": 1, "name": "area1", "base_power": 100.0, "power_units": "NATURAL_UNITS"}]},
        "supplemental_attributes": [],
        "supplemental_attribute_associations": [],
        "requirements_associations": [],
        "time_series_associations": [],
        "base_system_file": null,
        "time_series_storage_file": null
    });
    if let Some(stamp) = stamp {
        doc["schema_version"] = json!(stamp);
    }
    doc
}

type Parse = fn(&str, &str) -> Result<(), DocumentError>;

fn parse_system(reader: &str, text: &str) -> Result<(), DocumentError> {
    parse_document_for(reader, text).map(drop)
}

fn parse_portfolio(reader: &str, text: &str) -> Result<(), DocumentError> {
    parse_portfolio_document_for(reader, text).map(drop)
}

type Build = fn(Option<&str>) -> Value;

/// Both document kinds with a builder for a minimal document of each.
fn kinds() -> [(&'static str, Parse, Build); 2] {
    [
        ("SystemDocument", parse_system, system),
        ("PortfolioDocument", parse_portfolio, portfolio),
    ]
}

fn outcome(error: DocumentError) -> SchemaVersionOutcome {
    match error {
        DocumentError::Version { outcome, .. } => outcome,
        other => panic!("not a version error: {other}"),
    }
}

#[test]
fn shipped_reader_version_is_a_version() {
    let current = current_schema_version();
    assert_eq!(
        check_schema_version(&json!({"schema_version": current})).unwrap(),
        SchemaVersionOutcome::Current
    );
    assert!(!current.starts_with('v'));
}

#[test]
fn shared_vectors() {
    let dir = schemas_dir();
    let path = [
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../fixtures/versioning/cases.json"),
        dir.join("tests/fixtures/versioning/cases.json"),
        dir.join("versioning/cases.json"),
    ]
    .into_iter()
    .find(|path| path.is_file())
    .unwrap_or_else(|| {
        panic!(
            "no cases.json under {}; set SIENNA_SCHEMAS_DIR",
            dir.display()
        )
    });
    let cases: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let cases = cases["cases"].as_array().unwrap();
    assert!(!cases.is_empty());
    for case in cases {
        let reader = case["reader"].as_str().unwrap();
        let expected = case["outcome"].as_str().unwrap();
        let got = check_schema_version_for(reader, &case["document"]).unwrap();
        assert_eq!(
            got.to_string(),
            expected,
            "reader {reader}, document {}",
            case["document"]
        );
        if let Some(message) = case["expected_message"].as_str() {
            let error = DocumentError::Version {
                outcome: got,
                reader: reader.to_owned(),
                document: case["document"]["schema_version"].clone(),
            };
            assert_eq!(error.to_string(), message, "reader {reader}");
        }
    }
}

#[test]
fn canonical_messages() {
    let message = |reader: &str, stamp: Option<Value>| {
        let mut doc = json!({"components": {}});
        if let Some(stamp) = stamp {
            doc["schema_version"] = stamp;
        }
        parse_document_for(reader, &doc.to_string())
            .unwrap_err()
            .to_string()
    };
    assert_eq!(
        message("0.1.0", None),
        "document has no schema_version: it predates versioning; re-export it with a current \
         producer (psy5 bundles: PowerSystemsUpdater)"
    );
    assert_eq!(
        message("0.1.0", Some(json!("v0.1.0"))),
        "document schema_version \"v0.1.0\" is not a valid version"
    );
    assert_eq!(
        message("0.1.0", Some(json!(0.1))),
        "document schema_version 0.1 is not a valid version"
    );
    assert_eq!(
        message("0.1.0", Some(Value::Null)),
        "document schema_version null is not a valid version"
    );
    assert_eq!(
        message("0.1.0", Some(json!("0.1.0-3-gabc123-dirty"))),
        "document written by schema 0.1.0-3-gabc123-dirty cannot be read by schema 0.1.0: dev \
         builds read only their own output"
    );
    assert_eq!(
        message("0.1.0", Some(json!("0.2.0"))),
        "document written by schema 0.2.0 (line 0.2) cannot be read by schema 0.1.0 (line 0.1): \
         documents do not cross compatibility lines; migrating between lines is a separate \
         upgrade tool's job (psy5 bundles: PowerSystemsUpdater)"
    );
    assert_eq!(
        message("2.0.0", Some(json!("1.9.9"))),
        "document written by schema 1.9.9 (line 1) cannot be read by schema 2.0.0 (line 2): \
         documents do not cross compatibility lines; migrating between lines is a separate \
         upgrade tool's job (psy5 bundles: PowerSystemsUpdater)"
    );
    assert_eq!(
        message("0.1.0", Some(json!("0.1.5"))),
        "document written by schema 0.1.5; this reader understands up to 0.1.0; update the model \
         package to one built from >= 0.1.5"
    );
}

#[test]
fn read_rejects_bad_stamps_before_unknown_keys() {
    for (kind, parse, build) in kinds() {
        for (stamp, expected) in [
            (None, SchemaVersionOutcome::Missing),
            (Some("0.1.2"), SchemaVersionOutcome::Newer),
            (Some("0.2.0"), SchemaVersionOutcome::Incompatible),
            (Some("not a version"), SchemaVersionOutcome::Malformed),
        ] {
            let mut doc = build(stamp);
            doc["field_from_the_future"] = json!(1);
            let error = parse(READER, &doc.to_string()).expect_err(kind);
            assert_eq!(outcome(error), expected, "{kind} {stamp:?}");
        }
        let mut doc = build(Some(OLDER));
        doc["field_from_the_future"] = json!(1);
        assert!(
            matches!(parse(READER, &doc.to_string()), Err(DocumentError::Json(_))),
            "{kind}: a readable stamp still rejects unknown keys"
        );
    }
}

#[test]
fn version_error_carries_reader_and_document() {
    let error = parse_document_for("0.1.0", &system(Some("0.1.4")).to_string()).unwrap_err();
    let DocumentError::Version {
        outcome,
        reader,
        document,
    } = error
    else {
        panic!("not a version error");
    };
    assert_eq!(outcome, SchemaVersionOutcome::Newer);
    assert_eq!(reader, "0.1.0");
    assert_eq!(document, json!("0.1.4"));
}

#[test]
fn upgradable_documents_read_and_record_their_version() {
    let doc = parse_document_for(READER, &system(Some(OLDER)).to_string()).unwrap();
    assert_eq!(doc.get_source_schema_version(), OLDER);
    let doc = parse_portfolio_document_for(READER, &portfolio(Some(OLDER)).to_string()).unwrap();
    assert_eq!(doc.get_source_schema_version(), OLDER);
}

#[test]
fn new_documents_record_the_reader_version() {
    let doc: SystemDocument = serde_json::from_value(system(None)).unwrap();
    assert_eq!(doc.get_source_schema_version(), current_schema_version());
    let doc: PortfolioDocument = serde_json::from_value(portfolio(None)).unwrap();
    assert_eq!(doc.get_source_schema_version(), current_schema_version());
}

fn stamp_of(path: &Path) -> (Value, String) {
    let text = std::fs::read_to_string(path).unwrap();
    let doc: Value = serde_json::from_str(&text).unwrap();
    (doc, text)
}

#[test]
fn roundtrip_stamps_the_reader_and_keeps_the_source() {
    let dir = scratch("roundtrip");
    let doc = parse_document_for(READER, &system(Some(OLDER)).to_string()).unwrap();
    let path = dir.join("system.json");
    write_document_for(READER, &dir, &doc, &path, SchemaVersionTarget::Current).unwrap();
    let (written, text) = stamp_of(&path);
    assert_eq!(written["schema_version"], READER);
    assert!(text.starts_with("{\n  \"schema_version\""));
    assert_eq!(doc.get_source_schema_version(), OLDER);
    assert!(!text.contains("source_schema_version"));

    let doc = parse_portfolio_document_for(READER, &portfolio(Some(OLDER)).to_string()).unwrap();
    let path = dir.join("portfolio.json");
    write_portfolio_document_for(READER, &dir, &doc, &path, SchemaVersionTarget::Current).unwrap();
    assert_eq!(stamp_of(&path).0["schema_version"], READER);
}

#[test]
fn default_write_stamps_the_crate_version_and_upgrade_rewrites() {
    let dir = scratch("upgrade");
    let src = dir.join("src.json");
    let current = current_schema_version();
    std::fs::write(&src, system(Some(current)).to_string()).unwrap();
    let dst = dir.join("dst.json");
    upgrade_document(&src, &dst, false).unwrap();
    assert_eq!(stamp_of(&dst).0["schema_version"], current);
    assert!(matches!(
        upgrade_document(&src, &dst, false),
        Err(DocumentError::Io(_))
    ));
    upgrade_document(&src, &dst, true).unwrap();

    std::fs::write(&src, portfolio(Some(current)).to_string()).unwrap();
    let dst = dir.join("portfolio.json");
    upgrade_portfolio_document(&src, &dst, false).unwrap();
    assert_eq!(stamp_of(&dst).0["schema_version"], current);

    std::fs::write(&src, system(None).to_string()).unwrap();
    let error = upgrade_document(&src, dir.join("never.json"), false).unwrap_err();
    assert_eq!(outcome(error), SchemaVersionOutcome::Missing);
    assert!(!dir.join("never.json").exists());
}

#[test]
fn canonical_encoding_omits_defaulted_and_empty_properties() {
    let mut doc = system(Some(current_schema_version()));
    doc["trading_hub_associations"] = json!([]);
    doc["name"] = Value::Null;
    let text = document_to_string(&parse_document(&doc.to_string()).unwrap()).unwrap();
    let written: Value = serde_json::from_str(&text).unwrap();
    for key in ["trading_hub_associations", "name"] {
        assert!(written.get(key).is_none(), "{key}");
    }
    assert!(written["time_series_storage_file"].is_null());

    let hub = json!({"trading_hub_id": 1, "entity_id": 2});
    doc["trading_hub_associations"] = json!([hub]);
    let text = document_to_string(&parse_document(&doc.to_string()).unwrap()).unwrap();
    let written: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(written["trading_hub_associations"], json!([hub]));

    let mut doc = portfolio(Some(current_schema_version()));
    doc["financial_data"] =
        json!({"id": 5, "base_year": 2020, "discount_rate": 0.0, "interest_rate": 0.123});
    let doc = parse_portfolio_document(&doc.to_string()).unwrap();
    let written: Value =
        serde_json::from_str(&portfolio_document_to_string(&doc).unwrap()).unwrap();
    let data = written["financial_data"].as_object().unwrap();
    for key in ["discount_rate", "inflation_rate"] {
        assert_eq!(data[key], 0.0, "{key}");
    }
    assert_eq!(data["interest_rate"], 0.123);
    assert_eq!(data["base_year"], 2020);
}

#[test]
fn non_object_root_is_a_format_error_not_missing() {
    for text in ["[]", "3", "null", "\"x\""] {
        assert!(matches!(
            parse_document(text),
            Err(DocumentError::Invalid(_))
        ));
        assert!(matches!(
            parse_portfolio_document(text),
            Err(DocumentError::Invalid(_))
        ));
        let raw: Value = serde_json::from_str(text).unwrap();
        assert!(matches!(
            check_schema_version(&raw),
            Err(DocumentError::Invalid(_))
        ));
    }
}

#[cfg(feature = "source-version")]
mod source {
    use super::*;
    use std::process::Command;
    use std::sync::OnceLock;

    fn bundles() -> &'static Path {
        static BUNDLES: OnceLock<PathBuf> = OnceLock::new();
        BUNDLES.get_or_init(|| {
            let out = scratch("bundles");
            let root = schemas_dir();
            let venv = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../.venv/bin/python3");
            let python = if venv.is_file() {
                venv
            } else {
                PathBuf::from("python3")
            };
            let status = Command::new(python)
                .arg(root.join("scripts/build_bundles.py"))
                .args(["--root".as_ref(), root.as_os_str()])
                .args(["--version", OLDER])
                .args(["--out".as_ref(), out.as_os_str()])
                .status()
                .expect("run build_bundles.py");
            assert!(status.success(), "build_bundles.py failed");
            out
        })
    }

    fn violation_paths(error: DocumentError) -> Vec<String> {
        match error {
            DocumentError::SourceVersion { paths, .. } => paths,
            other => panic!("not a source-version error: {other}"),
        }
    }

    #[test]
    fn nothing_newer_is_written_at_the_source_version() {
        let dir = scratch("source-ok");
        let doc = parse_document_for(READER, &system(Some(OLDER)).to_string()).unwrap();
        let path = dir.join("system.json");
        write_document_for(READER, bundles(), &doc, &path, SchemaVersionTarget::Source).unwrap();
        assert_eq!(stamp_of(&path).0["schema_version"], OLDER);

        let doc =
            parse_portfolio_document_for(READER, &portfolio(Some(OLDER)).to_string()).unwrap();
        let path = dir.join("portfolio.json");
        write_portfolio_document_for(READER, bundles(), &doc, &path, SchemaVersionTarget::Source)
            .unwrap();
        assert_eq!(stamp_of(&path).0["schema_version"], OLDER);
    }

    #[test]
    fn every_offending_path_is_listed() {
        let dir = scratch("source-bad");
        let path = dir.join("doc.json");

        let mut text = system(Some(OLDER));
        let row = text["components"]["ACBus"][0].clone();
        text["components"]["ACBus"] = json!([row.clone(), row]);
        let mut doc = parse_document_for(READER, &text.to_string()).unwrap();
        for row in doc.components.get_mut("ACBus").unwrap() {
            row.insert("from_the_future".to_owned(), json!(1));
        }
        let error = write_document_for(READER, bundles(), &doc, &path, SchemaVersionTarget::Source)
            .unwrap_err();
        let message = error.to_string();
        let paths = violation_paths(error);
        assert_eq!(paths.len(), 2, "{paths:?}");
        assert!(
            paths[0].starts_with("/components/ACBus/0/from_the_future"),
            "{paths:?}"
        );
        assert!(
            paths[1].starts_with("/components/ACBus/1/from_the_future"),
            "{paths:?}"
        );
        assert!(
            message.contains("SchemaVersionTarget::Current"),
            "{message}"
        );
        assert!(!path.exists());

        let mut text = portfolio(Some(OLDER));
        let row = text["components"]["Area"][0].clone();
        text["components"]["Area"] = json!([row.clone(), row]);
        let mut doc = parse_portfolio_document_for(READER, &text.to_string()).unwrap();
        for row in doc.components.get_mut("Area").unwrap() {
            row.insert("from_the_future".to_owned(), json!(1));
        }
        let error = write_portfolio_document_for(
            READER,
            bundles(),
            &doc,
            &path,
            SchemaVersionTarget::Source,
        )
        .unwrap_err();
        assert_eq!(violation_paths(error).len(), 2);
    }

    #[test]
    fn unknown_keys_inside_a_union_are_listed_at_their_own_paths() {
        let dir = scratch("source-union");
        let mut text = system(Some(OLDER));
        text["supplemental_attributes"] = json!([
            {"id": 10, "geo_json": {"type": "Point", "coordinates": [0.0, 0.0]}, "future": 1},
            {"id": 11, "geo_json": {"type": "Point", "coordinates": [0.0, 0.0]}, "future": 1, "later": 2}
        ]);
        let doc = parse_document_for(READER, &text.to_string()).unwrap();
        let error = write_document_for(
            READER,
            bundles(),
            &doc,
            dir.join("doc.json"),
            SchemaVersionTarget::Source,
        )
        .unwrap_err();
        let paths = violation_paths(error);
        for want in [
            "/supplemental_attributes/0/future",
            "/supplemental_attributes/1/future",
            "/supplemental_attributes/1/later",
        ] {
            assert!(
                paths.iter().any(|p| p.starts_with(want)),
                "{want} in {paths:?}"
            );
        }
        assert_eq!(paths.len(), 3, "{paths:?}");
    }

    #[test]
    fn missing_bundle_names_the_path() {
        let empty = scratch("source-empty");
        let doc = parse_document_for(READER, &system(Some(OLDER)).to_string()).unwrap();
        let error = write_document_for(
            READER,
            &empty,
            &doc,
            empty.join("x.json"),
            SchemaVersionTarget::Source,
        )
        .unwrap_err();
        let expected = empty.join(OLDER).join("SystemDocument.json");
        let text = error.to_string();
        assert!(text.contains(&expected.display().to_string()), "{error}");
        assert!(text.contains(OLDER), "{error}");
        assert!(text.contains("SchemaVersionTarget::Current"), "{error}");
    }

    #[test]
    fn source_equal_to_reader_needs_no_bundle() {
        let empty = scratch("source-same");
        let doc = parse_document_for(OLDER, &system(Some(OLDER)).to_string()).unwrap();
        let path = empty.join("x.json");
        write_document_for(OLDER, &empty, &doc, &path, SchemaVersionTarget::Source).unwrap();
        assert_eq!(stamp_of(&path).0["schema_version"], OLDER);
    }

    #[test]
    fn source_stamp_the_reader_cannot_read_is_refused() {
        let empty = scratch("source-unreadable");
        let mut doc = parse_document_for(READER, &system(Some(OLDER)).to_string()).unwrap();
        doc.source_schema_version = "0.9.0".to_owned();
        let error = write_document_for(
            READER,
            &empty,
            &doc,
            empty.join("x.json"),
            SchemaVersionTarget::Source,
        )
        .unwrap_err();
        assert_eq!(outcome(error), SchemaVersionOutcome::Incompatible);
    }
}

#[cfg(not(feature = "source-version"))]
#[test]
fn source_write_without_the_feature_names_it() {
    let dir = scratch("no-feature");
    let doc = parse_document_for(READER, &system(Some(OLDER)).to_string()).unwrap();
    let error = write_document_for(
        READER,
        &dir,
        &doc,
        dir.join("x.json"),
        SchemaVersionTarget::Source,
    )
    .unwrap_err();
    assert!(error.to_string().contains("`source-version`"), "{error}");
    assert!(!dir.join("x.json").exists());

    let doc = parse_document_for(OLDER, &system(Some(OLDER)).to_string()).unwrap();
    write_document_for(
        OLDER,
        &dir,
        &doc,
        dir.join("x.json"),
        SchemaVersionTarget::Source,
    )
    .unwrap();
}
