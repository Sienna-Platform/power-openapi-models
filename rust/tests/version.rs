//! Provenance: the crate reports the schema pin the repo is generated from.

use std::fs;
use std::path::PathBuf;

use power_openapi_models::{SCHEMA_VERSION, VERSION};

fn root(file: &str) -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join(file);
    fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

#[test]
fn schema_version_matches_the_repo_pin() {
    assert_eq!(SCHEMA_VERSION, root(".schema-version").trim());
    assert!(SCHEMA_VERSION.starts_with('v'), "{SCHEMA_VERSION:?}");
}

#[test]
fn version_matches_the_other_packages() {
    let package_json: serde_json::Value =
        serde_json::from_str(&root("typescript/package.json")).unwrap();
    assert_eq!(VERSION, package_json["version"].as_str().unwrap());
}
