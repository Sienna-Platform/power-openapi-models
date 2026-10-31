#!/usr/bin/env python3
"""Bundle the six SiennaSchemas entry specs into one self-contained OpenAPI 3.1 document.

openapi-to-rust consumes a single OpenAPI document with internal
`#/components/schemas/X` refs. The
SiennaSchemas tree is many files linked by relative external `$ref`s
(`../common.json#/$defs/ACBusType`, `Operations/Branch/Line.json`), and each of
the six specs re-lists the shared types it uses. This resolves every ref to a
definition *identity* -- (file, fragment) -- so a type reached from several
specs or files is emitted once, which is the dedup the Python and TypeScript
generators each have to do after the fact.

Output: a JSON file `{"openapi": "3.1.0", "paths": {}, "components": {"schemas":
{...}}, "x-domains": {domain: [names...]}}`. `x-domains` records which names
each spec lists in `components.schemas`, for the per-domain modules. Fails
loudly, never guesses, if two different definitions want the same exported name.

  SCHEMA_DIR=../SiennaSchemas python3 codegen/rust/bundle.py OUT.json
"""

import json
import os
import sys
from pathlib import Path

DOMAINS = {
    "infrastructure_core": "openapi-infrastructure-core.json",
    "core": "openapi-core.json",
    "operations": "openapi-operations.json",
    "investments": "openapi-investments.json",
    "dynamics": "openapi-dynamics.json",
    "timeseries": "openapi-timeseries.json",
}

# The keyword that names an inline definition. Generated types are named after
# the schema, so every definition needs a stable one.
NAME_KEYS = ("title",)


class BundleError(Exception):
    pass


def fail(message):
    raise BundleError(message)


def load(path, cache):
    if path not in cache:
        cache[path] = json.loads(path.read_text())
    return cache[path]


def split_ref(ref, current_file):
    """`(absolute file, fragment)` for a `$ref` written inside `current_file`."""
    file_part, _, fragment = ref.partition("#")
    if file_part:
        target = (current_file.parent / file_part).resolve()
    else:
        target = current_file
    return target, fragment


def pointer_get(document, fragment, where):
    node = document
    for part in [p for p in fragment.split("/") if p]:
        part = part.replace("~1", "/").replace("~0", "~")
        if part not in node:
            fail(f"{where}: unresolvable pointer #{fragment} (missing {part!r})")
        node = node[part]
    return node


class Bundler:
    def __init__(self, schema_dir):
        self.schema_dir = schema_dir.resolve()
        self.cache = {}
        self.name_of = {}  # identity -> exported name
        self.identity_of = {}  # exported name -> identity
        self.defs = {}  # exported name -> rewritten schema
        self.pending = []
        self.preferred = {}  # identity -> name a spec gave it

    def identity(self, file, fragment):
        return (str(file), fragment)

    def display(self, identity):
        file, fragment = identity
        rel = os.path.relpath(file, self.schema_dir)
        return f"{rel}#{fragment}" if fragment else rel

    def default_name(self, identity, node):
        file, fragment = identity
        if identity in self.preferred:
            return self.preferred[identity]
        for key in NAME_KEYS:
            if isinstance(node, dict) and isinstance(node.get(key), str):
                return node[key]
        if fragment:
            return fragment.rstrip("/").rsplit("/", 1)[-1]
        return Path(file).stem

    def register(self, identity):
        """Exported name for an identity, queueing its body on first sight."""
        if identity in self.name_of:
            return self.name_of[identity]
        file, fragment = identity
        document = load(Path(file), self.cache)
        node = pointer_get(document, fragment, self.display(identity))
        name = self.default_name(identity, node)
        if name in self.identity_of and self.identity_of[name] != identity:
            fail(
                f"name {name!r} is claimed by two different definitions:\n"
                f"  {self.display(self.identity_of[name])}\n"
                f"  {self.display(identity)}"
            )
        self.name_of[identity] = name
        self.identity_of[name] = identity
        self.pending.append(identity)
        return name

    def rewrite(self, node, current_file):
        if isinstance(node, list):
            return [self.rewrite(item, current_file) for item in node]
        if not isinstance(node, dict):
            return node
        out = {}
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                target, fragment = split_ref(value, current_file)
                name = self.register(self.identity(target, fragment))
                out[key] = f"#/components/schemas/{name}"
            elif key == "$schema":
                continue
            else:
                out[key] = self.rewrite(value, current_file)
        return out

    def drain(self):
        while self.pending:
            identity = self.pending.pop()
            file, fragment = identity
            document = load(Path(file), self.cache)
            node = pointer_get(document, fragment, self.display(identity))
            name = self.name_of[identity]
            body = self.rewrite(node, Path(file))
            if isinstance(body, dict):
                body.setdefault("title", name)
                if body["title"] != name:
                    fail(
                        f"{self.display(identity)}: exported as {name!r} but its "
                        f"title is {body['title']!r}"
                    )
            self.defs[name] = body

    def add_spec(self, domain, spec_name):
        path = self.schema_dir / spec_name
        spec = load(path, self.cache)
        schemas = spec.get("components", {}).get("schemas", {})
        if not schemas:
            fail(f"{spec_name}: no components.schemas -- refusing to bundle nothing")
        names = []
        for name, entry in schemas.items():
            if set(entry) != {"$ref"}:
                fail(f"{spec_name}#{name}: expected a bare $ref, got keys {sorted(entry)}")
            target, fragment = split_ref(entry["$ref"], path)
            identity = self.identity(target, fragment)
            self.preferred.setdefault(identity, name)
            if self.preferred[identity] != name:
                fail(
                    f"{self.display(identity)} is listed as both "
                    f"{self.preferred[identity]!r} and {name!r}"
                )
            names.append(name)
        return names


def bundle(schema_dir):
    b = Bundler(schema_dir)
    listed = {}
    for domain, spec in DOMAINS.items():
        listed[domain] = b.add_spec(domain, spec)
    for domain, names in listed.items():
        for name in names:
            file, fragment = split_ref(
                load(b.schema_dir / DOMAINS[domain], b.cache)["components"]["schemas"][name][
                    "$ref"
                ],
                b.schema_dir / DOMAINS[domain],
            )
            b.register(b.identity(file, fragment))
    b.drain()
    for domain, names in listed.items():
        for name in names:
            if name not in b.defs:
                fail(f"{domain}: {name!r} was listed but never bundled")
    return {
        "openapi": "3.1.0",
        "info": {"title": "PowerOpenAPIModels", "version": "0.1.0"},
        "paths": {},
        "components": {"schemas": dict(sorted(b.defs.items()))},
        "x-domains": {d: sorted(set(n)) for d, n in listed.items()},
    }


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    schema_dir = Path(os.environ.get("SCHEMA_DIR", "../SiennaSchemas"))
    try:
        result = bundle(schema_dir)
    except BundleError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    Path(sys.argv[1]).write_text(json.dumps(result, indent=1, sort_keys=False) + "\n")
    listed = sum(len(v) for v in result["x-domains"].values())
    print(
        f"bundled {len(result['components']['schemas'])} definitions "
        f"({listed} listed across 6 domains)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
