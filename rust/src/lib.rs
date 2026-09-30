#![doc = include_str!("../README.md")]

pub mod core;
pub mod document;
pub mod dynamics;
pub mod generated;
pub mod infrastructure_core;
pub mod investments;
pub mod operations;
pub mod timeseries;
pub mod timestamp;

/// This crate's version.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

const RAW_SCHEMA_VERSION: &str = include_str!("../schema-version");

/// The SiennaSchemas release every type here is generated from.
pub const SCHEMA_VERSION: &str = RAW_SCHEMA_VERSION.trim_ascii_end();
