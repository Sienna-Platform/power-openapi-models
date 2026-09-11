"""Guards on the package's public surface.

These encode defects found before the 0.1.0 pre-release: `timeseries` was
absent from the top-level namespace, the package shipped no PEP 561 marker,
there was no `__version__`/`__schema_version__`, and a generated alias
(`<Base><N>`) can leak into a module's namespace when the code generator
cannot resolve an anonymous inline schema to a named component.
"""

import importlib
import pathlib

import pytest

MODULES = [
    "infrastructure_core",
    "core",
    "operations",
    "investments",
    "dynamics",
    "timeseries",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_reachable_from_top_level(name):
    """Every domain module is imported by the package root and listed in __all__."""
    import power_openapi_models

    assert hasattr(power_openapi_models, name), (
        f"power_openapi_models.{name} is not reachable after importing the package"
    )
    assert name in power_openapi_models.__all__


def test_py_typed_marker_is_present():
    """PEP 561: without this file, installed consumers get no type checking."""
    import power_openapi_models

    root = pathlib.Path(power_openapi_models.__file__).parent
    assert (root / "py.typed").is_file()


def test_version_metadata():
    import power_openapi_models

    assert power_openapi_models.__version__ == "0.1.0"
    assert isinstance(power_openapi_models.__schema_version__, str)
    assert power_openapi_models.__schema_version__


@pytest.mark.parametrize("name", MODULES)
def test_no_digit_suffix_alias_classes(name):
    """A `<Base><N>` class whose `<Base>` also exists is a codegen alias leak.

    datamodel-codegen materializes an anonymous copy of an inline schema at a
    reference site it cannot resolve to a named component, then disambiguates
    with a numeric suffix. The copies fragment the API: a value built at one
    site is not the type another site expects. Two upstream cures, never an
    edit here:

    - a genuine, distinctly-named schema colliding with another by property
      name (e.g. two different enums both called "ControlMode") needs its own
      named `$defs` entry in the SiennaSchemas source, so each gets a real
      name instead of a generator-assigned suffix;
    - a pure wrapper (`class <Base><N>(RootModel[<Base>]): root: <Base>`,
      e.g. `UnitSystem1`) should be collapsed by `--collapse-root-models`
      (see the Makefile) or, failing that, a `scripts/postprocess.py` pass.

    There is no generator-config workaround for this -- name the schema
    properly at the source instead.

    Keyed on the base existing, so a genuine name like `SteamTurbineGov1`
    is not flagged.
    """
    models = importlib.import_module(f"power_openapi_models.{name}.models")
    names = {n for n in dir(models) if not n.startswith("_")}
    leaked = [n for n in sorted(names) if n[-1].isdigit() and n.rstrip("0123456789") in names]
    assert not leaked, (
        f"{name}: generated alias classes {leaked} -- give each a named "
        f"$defs entry in SiennaSchemas, or collapse it in "
        f"scripts/postprocess.py if it is a pure RootModel wrapper"
    )
