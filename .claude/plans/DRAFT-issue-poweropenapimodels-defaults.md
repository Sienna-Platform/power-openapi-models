# DRAFT — not posted

Target repo: `Sienna-Platform/PowerOpenAPIModels`

Post with:

```bash
gh issue create --repo Sienna-Platform/PowerOpenAPIModels \
  --title "Decode does not materialize schema defaults: same document loads to different values in Julia and Python" \
  --body-file .claude/plans/DRAFT-issue-poweropenapimodels-defaults.md
```

(Strip this header block before posting, or move the body to its own file.)

---

## Summary

A document that omits an optional field with a schema `default` loads to a
different effective value in Julia than in Python. Julia leaves the field
`ABSENT`; Python (via `datamodel-code-generator`) materializes the schema
default. 290 fields across the generated packages are affected.

This is the same class of divergence `PATCHES.md` documents against the old Java
`openapi-generator` julia-client. That file states the move to OpenAPI.jl 1.0's
native generator resolved it:

> This repository moved to OpenAPI.jl 1.0's native pure-Julia generator (see
> `scripts/generate_native.jl`), which does real JSON-Schema validation at
> decode/encode time instead of the Java generator's hand-patched defaults — the
> divergence documented below no longer applies here.

The reproduction below shows it still applies.

## Reproduction

`Dynamics/DynamicGeneratorComponent/SEXS.json` declares `V_ref` optional with
`default: 1.0`. Decode a document that omits it:

```julia
using Pkg
Pkg.activate(; temp=true)
Pkg.develop([
  Pkg.PackageSpec(path="InfrastructureCoreOpenAPIModels.jl"),
  Pkg.PackageSpec(path="PowerCoreOpenAPIModels.jl"),
  Pkg.PackageSpec(path="PowerDynamicsOpenAPIModels.jl"),
])
using PowerDynamicsOpenAPIModels
const M = PowerDynamicsOpenAPIModels

doc = Dict{String,Any}("id"=>1, "Ta_Tb"=>0.1, "Tb"=>1.0, "K"=>10.0, "Te"=>0.5,
           "V_lim"=>Dict{String,Any}("min"=>0.0, "max"=>5.0))
obj = M._decode(M.SEXS, doc)
@show obj.v_ref
@show M._encode(obj)
```

Actual:

```
Julia decoded V_ref  = ABSENT
round-trip encode    = {"id":1,"Ta_Tb":0.1,"Tb":1.0,"K":10.0,"Te":0.5,
                        "V_lim":{"max":5.0,"min":0.0}}
```

The same document in Python:

```python
>>> from power_openapi_models.dynamics.models import SEXS
>>> SEXS(id=1, Ta_Tb=0.1, Tb=1.0, K=10.0, Te=0.5,
...      V_lim={"min": 0.0, "max": 5.0}).V_ref
1.0
```

So:

| | Julia | Python |
|---|---|---|
| `V_ref` after decoding a document that omits it | `ABSENT` | `1.0` |
| Re-encoded document | key omitted | key present, `1.0` |

A consumer reading the field gets a different value in each language, and a
Python→Julia→Python round trip is not the identity.

## Scope

290 fields. A sample:

```
AGC.initial_ace             Julia=ABSENT  Python=0.0
Area.load_response          Julia=ABSENT  Python=0.0
Area.peak_active_power      Julia=ABSENT  Python=0.0
```

Full list reproducible with, in `power-openapi-models`:

```bash
python3 scripts/check_cross_language.py --julia ../PowerOpenAPIModels
```

## Note on how this was found

The cross-language check in `power-openapi-models` had been passing vacuously:
it matched `Base.@kwdef mutable struct` while this repo's generator emits
`Base.@kwdef struct`, so it parsed **zero** Julia structs, compared zero types,
and printed "Surfaces agree" with exit 0. That check has been fixed and now
guards against reporting agreement when nothing was compared.

## Not a bug — recorded so it is not re-reported

Julia snake_cases struct field names (`ta_tb`) while `_decode`/`_encode` use the
schema key (`Ta_Tb`). The wire format is correct and documents round-trip. An
earlier read of this as a casing bug was wrong.

## Open question

Is materializing defaults on decode the right fix, or is `ABSENT` deliberate —
distinguishing "absent" from "explicitly set to the default", which pydantic
cannot do? If `ABSENT` is intended, the divergence is in Python materializing
eagerly, and the two generators need an agreed contract either way. That
decision likely belongs upstream in OpenAPI.jl rather than in this repo's
`scripts/generate_native.jl`.
