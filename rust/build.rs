//! Names the strict bundle of the release in `schema-version`, for the
//! `validate` feature's `include_str!`. The path changes with every release, so
//! it cannot be a literal.

fn main() {
    let dir = std::env::var("CARGO_MANIFEST_DIR").expect("cargo sets CARGO_MANIFEST_DIR");
    let raw = std::fs::read_to_string(format!("{dir}/schema-version")).expect("schema-version");
    let version = raw.trim().trim_start_matches('v');
    let bundle = format!("{dir}/bundles/{version}/SystemDocument.json");
    println!("cargo:rerun-if-changed=schema-version");
    println!("cargo:rerun-if-changed={bundle}");
    println!("cargo:rustc-env=POM_SYSTEM_BUNDLE={bundle}");
}
