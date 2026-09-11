# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — Unreleased

First release.

### Added

- Typed pydantic v2 models for the Sienna power system data format, generated
  from SiennaSchemas.
- Six generated modules: `infrastructure_core`, `core`, `operations`,
  `investments`, `dynamics`, `timeseries`, plus the hand-written `document`
  module (`SystemDocument`, `read_document`, `write_document`).
- PEP 561 `py.typed` marker; the package ships as fully typed.
- `__version__` and `__schema_version__` for runtime provenance.

[0.1.0]: https://github.com/Sienna-Platform/power-openapi-models/releases/tag/v0.1.0
