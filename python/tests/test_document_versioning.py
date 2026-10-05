"""Schema-version stamp, reader rule, write targets and canonical encoding of the
document containers. The reader-rule vectors are the shipped fixtures/versioning/cases.json;
the strict bundles are built from the SiennaSchemas checkout (SIENNA_SCHEMAS_DIR, default the
sibling ../SiennaSchemas).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from power_openapi_models import _versioning, document
from power_openapi_models.document import (
    PortfolioDocument,
    SchemaVersionError,
    SystemDocument,
    check_schema_version,
    get_source_schema_version,
)

SCHEMAS_DIR = Path(
    os.environ.get(
        "SIENNA_SCHEMAS_DIR", str(Path(__file__).resolve().parents[2].parent / "SiennaSchemas")
    )
)
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
R = _versioning.READER_VERSION
# A reader one patch ahead of the shipped one: the only way to get a `D < R` pair on
# one line when the shipped version is the first release of its line.
NEWER_READER = "0.1.1"


def _next_line(version):
    major, minor, _ = _parts(version)
    return f"0.{minor + 1}.0" if major == 0 else f"{major + 1}.0.0"


def _bump_patch(version):
    major, minor, patch = _parts(version)
    return f"{major}.{minor}.{patch + 1}"


SYSTEM = {
    "components": {"ACBus": [{"id": 1, "name": "bus1", "available": True, "number": 1}]},
    "supplemental_attributes": [],
    "supplemental_attribute_associations": [],
    "plant_associations": [],
    "combined_cycle_associations": [],
    "service_associations": [],
    "time_series_associations": [],
    "time_series_storage_file": None,
}
PORTFOLIO = {
    "aggregation": "Area",
    "components": {
        "Area": [{"id": 1, "name": "area1", "base_power": 100.0, "power_units": "NATURAL_UNITS"}]
    },
    "supplemental_attributes": [],
    "supplemental_attribute_associations": [],
    "requirements_associations": [],
    "time_series_associations": [],
    "base_system_file": None,
    "time_series_storage_file": None,
}
KINDS = {
    "system": (
        SystemDocument,
        SYSTEM,
        "SystemDocument",
        document.read_document,
        document.write_document,
        document.upgrade_document,
        "ACBus",
    ),
    "portfolio": (
        PortfolioDocument,
        PORTFOLIO,
        "PortfolioDocument",
        document.read_portfolio_document,
        document.write_portfolio_document,
        document.upgrade_portfolio_document,
        "Area",
    ),
}


@pytest.fixture(params=KINDS)
def kind(request):
    return KINDS[request.param]


def _parts(version):
    major, minor, patch = (int(n) for n in version.split("-")[0].split("."))
    return major, minor, patch


def _line(version):
    major, minor, _ = _parts(version)
    return f"0.{minor}" if major == 0 else str(major)


def _cases():
    path = FIXTURES / "versioning" / "cases.json"
    if not path.is_file():
        pytest.fail(f"{path} not found; run `make sync-bundles` from a release tarball")
    return json.loads(path.read_text())["cases"]


def pytest_generate_tests(metafunc):
    if "case" in metafunc.fixturenames:
        metafunc.parametrize("case", _cases(), ids=lambda c: f"{c['reader']}-{c['outcome']}")


def test_shared_vectors(case):
    outcome = _versioning._classify(case["document"], case["reader"])
    assert outcome == case["outcome"]
    if outcome in ("upgradable", "current"):
        assert _versioning._check(case["document"], case["reader"]) == outcome
        return
    with pytest.raises(SchemaVersionError) as caught:
        _versioning._check(case["document"], case["reader"])
    assert caught.value.outcome == outcome
    assert caught.value.reader == case["reader"]
    assert str(caught.value) == case["expected_message"]


def test_check_is_pure_and_returns_every_outcome():
    assert check_schema_version({"components": {}}) == "missing"
    assert check_schema_version({"schema_version": "v1"}) == "malformed"
    assert check_schema_version({"schema_version": _bump_patch(R)}) == "newer"


def test_check_uses_shipped_version():
    assert check_schema_version({"schema_version": R}) == "current"


def test_stamp_is_a_required_property_defaulted_on_construction(kind, tmp_path):
    cls, minimal, *_ = kind
    assert cls.model_fields["schema_version"].default_factory() == R
    assert get_source_schema_version(cls(**minimal)) == R


@pytest.mark.parametrize(
    "stamp, outcome",
    [
        (None, "missing"),
        (f"{R}-rc.1", "incompatible"),
        (f"{_next_line(R)}", "incompatible"),
        (_bump_patch(R), "newer"),
    ],
)
def test_read_rejects_before_unknown_keys(kind, tmp_path, stamp, outcome):
    _, minimal, _, read, *_ = kind
    raw = {**minimal, "key_from_the_future": []}
    if stamp is not None:
        raw["schema_version"] = stamp
    path = tmp_path / "doc.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(SchemaVersionError) as caught:
        read(path)
    assert caught.value.outcome == outcome


def test_roundtrip_stamps_reader_version_first(kind, tmp_path):
    cls, minimal, _, read, write, *_ = kind
    path = tmp_path / "doc.json"
    write(cls(**minimal), path)
    assert next(iter(json.loads(path.read_text()))) == "schema_version"
    assert json.loads(path.read_text())["schema_version"] == R
    assert get_source_schema_version(read(path)) == R


def test_read_records_source_version_without_serializing_it(kind, tmp_path):
    cls, minimal, _, read, write, *_ = kind
    src = tmp_path / "old.json"
    src.write_text(json.dumps({"schema_version": "0.1.0", **minimal}))
    doc = document._read(cls, src, reader=NEWER_READER)
    assert get_source_schema_version(doc) == "0.1.0"
    out = tmp_path / "out.json"
    write(doc, out)
    assert "source_schema_version" not in out.read_text()
    assert json.loads(out.read_text())["schema_version"] == R


def test_canonical_encoding_omits_absent_null_and_default(tmp_path):
    doc = SystemDocument(
        **SYSTEM,
        name=None,
        trading_hub_associations=[],
    )
    path = tmp_path / "doc.json"
    document.write_document(doc, path)
    written = json.loads(path.read_text())
    for omitted in ("name", "trading_hub_associations"):
        assert omitted not in written
    assert written["time_series_storage_file"] is None


def test_canonical_encoding_keeps_set_values(tmp_path):
    doc = SystemDocument(**SYSTEM, name="sys", ext={"1": {"k": "v"}})
    path = tmp_path / "doc.json"
    document.write_document(doc, path)
    written = json.loads(path.read_text())
    assert written["name"] == "sys"
    assert written["ext"] == {"1": {"k": "v"}}


def test_financial_rates_are_always_written(tmp_path):
    doc = PortfolioDocument(
        **{**PORTFOLIO, "financial_data": {"id": 5, "base_year": 2020, "discount_rate": 0.0}},
    )
    doc.financial_data.interest_rate = 0.123
    path = tmp_path / "doc.json"
    document.write_portfolio_document(doc, path)
    data = json.loads(path.read_text())["financial_data"]
    assert data == {
        "id": 5,
        "base_year": 2020,
        "discount_rate": 0.0,
        "inflation_rate": 0.0,
        "interest_rate": 0.123,
    }


def test_financial_data_rewrite_is_byte_stable(tmp_path):
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    first.write_text(
        json.dumps(
            {
                **PORTFOLIO,
                "schema_version": R,
                "financial_data": {
                    "id": 5,
                    "base_year": 2020,
                    "discount_rate": 0.0,
                    "interest_rate": 0.123,
                },
            }
        )
    )
    mid = tmp_path / "m.json"
    document.write_portfolio_document(document.read_portfolio_document(first), mid)
    document.write_portfolio_document(document.read_portfolio_document(mid), second)
    assert mid.read_text() == second.read_text()


def test_ext_the_document_carries_is_written_back(tmp_path):
    path = tmp_path / "doc.json"
    document.write_document(SystemDocument(**SYSTEM, ext={}), path)
    assert json.loads(path.read_text())["ext"] == {}
    document.write_document(SystemDocument(**SYSTEM), path)
    assert "ext" not in json.loads(path.read_text())


@pytest.mark.parametrize("text", ["[]", "3", "null", '"x"'])
def test_non_object_root_is_a_format_error_not_missing(kind, tmp_path, text):
    _, _, _, read, *_ = kind
    path = tmp_path / "doc.json"
    path.write_text(text)
    with pytest.raises(ValidationError):
        read(path)
    with pytest.raises(ValidationError):
        check_schema_version(json.loads(text))


def test_prune_drops_null_optionals_only():
    class Row(BaseModel):
        a: int | None
        b: int | None = None

    row = Row(a=None, b=None)
    dumped = {"a": None, "b": None}
    document._prune([row], [dumped])
    assert dumped == {"a": None}


@pytest.fixture(scope="module")
def bundles(tmp_path_factory):
    pytest.importorskip("jsonschema")
    script = SCHEMAS_DIR / "scripts" / "build_bundles.py"
    if not script.is_file():
        pytest.fail(f"{script} not found; set SIENNA_SCHEMAS_DIR to a SiennaSchemas checkout")
    out = tmp_path_factory.mktemp("bundles")
    subprocess.run(
        [sys.executable, str(script), "--root", str(SCHEMAS_DIR), "--version", "0.1.0",
         "--out", str(out)],
        check=True,
    )  # fmt: skip
    return out


def _source_write(cls, minimal, bundle_name, path, bundles, **extra):
    doc = cls(schema_version="0.1.0", **{**minimal, **extra})
    document._write(
        doc,
        path,
        indent=2,
        bundle_name=bundle_name,
        schema_version="source",
        reader=NEWER_READER,
        bundle_dir=bundles,
    )


def test_source_write_keeps_older_stamp_when_nothing_newer_is_used(kind, tmp_path, bundles):
    cls, minimal, bundle_name, *_ = kind
    path = tmp_path / "doc.json"
    _source_write(cls, minimal, bundle_name, path, bundles)
    assert json.loads(path.read_text())["schema_version"] == "0.1.0"


def test_source_write_lists_every_offending_path(kind, tmp_path, bundles):
    cls, minimal, bundle_name, _, _, _, row_type = kind
    row = minimal["components"][row_type][0]
    components = {row_type: [{**row, "bogus": 1}, {**row, "id": 2, "name": "n2", "other": 2}]}
    with pytest.raises(ValueError) as caught:
        _source_write(
            cls, minimal, bundle_name, tmp_path / "doc.json", bundles, components=components
        )
    message = str(caught.value)
    assert f"/components/{row_type}/0/bogus" in message
    assert f"/components/{row_type}/1/other" in message
    assert 'schema_version="current"' in message
    assert not (tmp_path / "doc.json").exists()


def test_source_write_with_missing_bundle_names_the_path(kind, tmp_path):
    pytest.importorskip("jsonschema")
    cls, minimal, bundle_name, *_ = kind
    empty = tmp_path / "none"
    with pytest.raises(FileNotFoundError, match="0.1.0"):
        _source_write(cls, minimal, bundle_name, tmp_path / "doc.json", empty)


def test_source_write_without_validator_names_the_extra(kind, tmp_path, monkeypatch):
    cls, minimal, bundle_name, *_ = kind
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(ImportError, match=r"power-openapi-models\[source-version\]"):
        _source_write(cls, minimal, bundle_name, tmp_path / "doc.json", tmp_path)


def test_source_write_equal_to_reader_needs_no_validator(kind, tmp_path, monkeypatch):
    cls, minimal, _, _, write, *_ = kind
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    path = tmp_path / "doc.json"
    write(cls(**minimal), path, schema_version="source")
    assert json.loads(path.read_text())["schema_version"] == R


def test_source_write_refuses_a_stamp_the_reader_cannot_read(kind, tmp_path):
    cls, minimal, bundle_name, *_ = kind
    doc = cls(schema_version="0.1.9", **minimal)
    with pytest.raises(SchemaVersionError):
        document._write(
            doc, tmp_path / "doc.json", indent=2, bundle_name=bundle_name,
            schema_version="source", reader=NEWER_READER,
        )  # fmt: skip


def test_write_rejects_unknown_target(kind, tmp_path):
    cls, minimal, _, _, write, *_ = kind
    with pytest.raises(ValueError, match="'current' or 'source'"):
        write(cls(**minimal), tmp_path / "doc.json", schema_version="latest")


def test_upgrade_restamps_and_refuses_to_overwrite(kind, tmp_path):
    cls, minimal, _, read, _, upgrade, _ = kind
    src = tmp_path / "src.json"
    src.write_text(json.dumps({"schema_version": R, **minimal}))
    dst = tmp_path / "dst.json"
    upgrade(src, dst)
    assert json.loads(dst.read_text())["schema_version"] == R
    with pytest.raises(FileExistsError):
        upgrade(src, dst)
    upgrade(src, dst, force=True)


def test_upgrade_rejects_newer_document(kind, tmp_path):
    _, minimal, _, _, _, upgrade, _ = kind
    src = tmp_path / "src.json"
    src.write_text(json.dumps({"schema_version": _bump_patch(R), **minimal}))
    with pytest.raises(SchemaVersionError):
        upgrade(src, tmp_path / "dst.json")


def test_source_write_reports_unknown_keys_in_union_rows_only(tmp_path, bundles):
    rows = [
        {"id": 1, "identifier": "a", "outage_status": 1.0, "zzz": 1},
        {"id": 2, "outage_status": 1.0, "yyy": 1},
        {"id": 3, "outage_status": 1.0},
    ]
    with pytest.raises(ValueError) as caught:
        _source_write(
            SystemDocument,
            SYSTEM,
            "SystemDocument",
            tmp_path / "doc.json",
            bundles,
            supplemental_attributes=rows,
        )
    paths = {
        line.strip().split(": ")[0]
        for line in str(caught.value).splitlines()
        if line.startswith("  /")
    }
    assert paths == {"/supplemental_attributes/0/zzz", "/supplemental_attributes/1/yyy"}
