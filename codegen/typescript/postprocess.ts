#!/usr/bin/env node
/**
 * Post-process orval's generated zod models to remove cross-domain
 * duplication -- approach A from the multi-language packaging design.
 *
 * Mirrors codegen/python/postprocess.py's dedupe_core_against_infrastructure_core
 * in both algorithm and failure mode, generalized from one pair of domains
 * to the full precedence chain:
 *
 *   infrastructure_core -> core -> {operations, investments, dynamics, timeseries}
 *
 * Why duplication exists at all: orval's `externalRefs` allowlist controls
 * which files a spec's `$ref`s may read, but (unlike datamodel-codegen's
 * `--external-ref-mapping`, which the Python side uses for the same
 * problem) orval has no ref-to-module mapping. A domain spec that reaches
 * into Core/common.json or openapi-core.json's own types therefore gets
 * its own top-level copy of every such schema. This script finds those
 * copies, verifies each is byte-identical to its canonical owner's, and
 * rewrites it into a re-export -- refusing to guess when a "duplicate"
 * isn't actually identical.
 *
 * Each domain's generated typescript/src/<domain>/models.ts has a
 * consistent shape (verified against orval 8.32.0's zod client output):
 *
 *   [zero or more single-line helper consts, e.g. `export const
 *   fooDefault = \`BAR\`;` or a `.min()`/`.max()` bound]
 *   export const SchemaName = zod...(...)
 *
 *   export type SchemaName = zod.input<typeof SchemaName>;
 *   export type SchemaNameOutput = zod.output<typeof SchemaName>;
 *
 * repeated for every component schema, after a banner comment + `import *
 * as zod from 'zod';` header. `_parseModelsFile` locates each schema by its
 * trailing `export type X = zod.input<typeof X>; export type XOutput = ...`
 * pair (the one line shape that never varies) and searches backward for
 * that schema's own `export const X = ` to split off its helper-const
 * preamble, then verifies the parsed pieces reconstruct the original file
 * byte-for-byte -- if they don't, a formatting assumption broke and this
 * refuses to guess silently.
 */
import { readdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname, resolve } from "node:path";
import { DOMAIN_SPECS } from "./domains";

/**
 * One parse per schema file, keyed by resolved path. `Core/common.json` is
 * reached by dozens of `$ref`s; without this it was re-read and re-parsed on
 * every hop. Mirrors `_schema_json_cache` in codegen/python/postprocess.py.
 */
const schemaJsonCache = new Map<string, unknown>();

function loadSchemaJson(filePath: string): unknown {
  const key = resolve(filePath);
  let doc = schemaJsonCache.get(key);
  if (doc === undefined) {
    doc = JSON.parse(readFileSync(key, "utf8"));
    schemaJsonCache.set(key, doc);
  }
  return doc;
}

const SRC_DIR = "typescript/src";

// Same default the Makefile's SCHEMA_DIR uses (see codegen/typescript/gen-orval-config.ts),
// so running this file directly still finds a sibling checkout. Unlike
// gen-orval-config.ts -- whose OWN output is a config file living inside
// typescript/, one directory deeper -- this script runs with the repo root
// as cwd (invoked as `npx tsx codegen/typescript/postprocess.ts` from the
// Makefile), so a relative SCHEMA_DIR needs no extra `../` adjustment here.
const SCHEMA_DIR = process.env.SCHEMA_DIR ?? "../SiennaSchemas";

// Precedence order for canonical schema ownership -- earlier domains win.
// The remaining four domains are a tied, ownerless group: none of them owns
// schemas for any other (verified: no schema name is shared between two of
// them outside this owner pool).
const OWNER_PRECEDENCE = ["infrastructure_core", "core"] as const;

interface PreambleConst {
  ident: string;
  line: string;
}

interface Entry {
  name: string;
  /** preamble + `export const Name = ...` + blank line + the type-pair, verbatim */
  raw: string;
  /** `export const Name = ...` through the type-pair, verbatim -- `raw` minus the preamble */
  body: string;
  preambleConsts: PreambleConst[];
}

// ---------------------------------------------------------------------------
// Acronym schema titles -- orval PascalCases an ALL-CAPS schema `title`
// (AGC -> Agc, SEXS -> Sexs; verified against orval 8.32.0), while
// datamodel-codegen keeps the title verbatim as the Python class name, and a
// SiennaSchemas document's `components` section is keyed by that same
// title. Renaming the TypeScript export back to the schema's own title
// keeps both packages' identifiers for the same schema identical.
// ---------------------------------------------------------------------------

/** Every domain spec's `components.schemas` keys -- the titles Python's class
 * names already match verbatim -- plus an upper-cased lookup index so an
 * orval-mangled name can be traced back to the one title it mangled,
 * without hand-listing which titles are affected.
 */
function loadCanonicalSchemaNames(schemaDir: string): {
  names: ReadonlySet<string>;
  byUpper: ReadonlyMap<string, string[]>;
} {
  const names = new Set<string>();
  for (const specName of DOMAIN_SPECS) {
    const specPath = join(schemaDir, specName);
    if (!existsSync(specPath)) continue;
    const spec = loadSchemaJson(specPath) as any;
    for (const name of Object.keys(spec?.components?.schemas ?? {})) {
      names.add(name);
    }
  }
  const byUpper = new Map<string, string[]>();
  for (const name of names) {
    const upper = name.toUpperCase();
    const list = byUpper.get(upper);
    if (list) list.push(name);
    else byUpper.set(upper, [name]);
  }
  return { names, byUpper };
}

function lowerFirst(s: string): string {
  return s.length === 0 ? s : s[0].toLowerCase() + s.slice(1);
}

/** Global word-boundary rename of one identifier to another within `text`. */
function renameIdent(text: string, oldIdent: string, newIdent: string): string {
  return text.replace(new RegExp(`\\b${oldIdent}\\b`, "g"), newIdent);
}

/**
 * Rewrites one entry's exported name (and everything derived from it) from
 * `oldName` to `newName`: the `export const`/type-pair pair, any preamble
 * `*Default` const whose camelCase prefix embeds the old name (e.g.
 * `agcInitialAceDefault` -> `aGCInitialAceDefault` for `Agc` -> `AGC`), and
 * the `NameOutput` type alias -- renamed as one literal token first since
 * `\bAgc\b` alone does not match inside `AgcOutput` (no word boundary
 * between the `c` and the `O`).
 */
function renameEntry(entry: Entry, oldName: string, newName: string): Entry {
  const oldPrefix = lowerFirst(oldName);
  const newPrefix = lowerFirst(newName);
  const preambleConsts = entry.preambleConsts.map((c) => {
    if (!c.ident.startsWith(oldPrefix)) return c;
    const newIdent = newPrefix + c.ident.slice(oldPrefix.length);
    return { ident: newIdent, line: renameIdent(c.line, c.ident, newIdent) };
  });

  const renameText = (text: string): string => {
    let out = text;
    entry.preambleConsts.forEach((c, i) => {
      if (c.ident !== preambleConsts[i].ident) out = renameIdent(out, c.ident, preambleConsts[i].ident);
    });
    out = out.split(`${oldName}Output`).join(`${newName}Output`);
    out = renameIdent(out, oldName, newName);
    return out;
  };

  return { name: newName, raw: renameText(entry.raw), body: renameText(entry.body), preambleConsts };
}

/**
 * Renames every entry in `parsed` whose name is absent from the schema's
 * own title set but whose upper-cased form matches exactly one title --
 * i.e. an orval acronym-mangled name, never a guess: an orval-synthesized
 * name with no schema title at all (an anonymous oneOf branch) has no
 * upper-cased match and is left alone, and an ambiguous match (more than
 * one title sharing the same upper-cased form) is left alone rather than
 * picking one.
 *
 * Runs before ownership/dedup computation in `main`, so a renamed owner's
 * cross-domain `export { NewName } from '../owner/models';` line -- which
 * `rewriteDomain` generates from `entry.name`, not read back off disk --
 * already carries the corrected name with no separate cross-domain pass
 * needed.
 */
function renameAcronymEntries(
  parsed: ParsedFile,
  canonicalNames: ReadonlySet<string>,
  byUpper: ReadonlyMap<string, string[]>,
): { parsed: ParsedFile; renames: ReadonlyMap<string, string> } {
  const renames = new Map<string, string>();
  const entries = parsed.entries.map((entry) => {
    if (canonicalNames.has(entry.name)) return entry;
    const candidates = byUpper.get(entry.name.toUpperCase());
    if (!candidates || candidates.length !== 1 || candidates[0] === entry.name) return entry;
    const newName = candidates[0];
    renames.set(entry.name, newName);
    return renameEntry(entry, entry.name, newName);
  });
  return { parsed: { ...parsed, entries }, renames };
}

/**
 * Text used to decide whether two domains' copies of a schema are "the
 * same": the schema's own declaration plus its type pair, plus its preamble
 * consts in source order -- but not the incidental blank-line spacing
 * between entries, which varies with what precedes an entry in a given
 * file and carries no meaning of its own (confirmed: `core/models.ts` and
 * `infrastructure_core/models.ts` emit byte-identical `UnitSystem` bodies
 * but different leading blank-line counts, an orval formatting accident,
 * not a real divergence).
 */
function normalizedText(entry: Entry): string {
  return canonicalizeSingletonEnums(
    entry.preambleConsts.map((c) => c.line + "\n").join("") + entry.body,
  );
}

/**
 * Rewrite `zod.enum(['X'])` to `zod.literal("X")`.
 *
 * Orval renders a single-valued schema enum either way depending on whether
 * that schema also appears as a discriminated-union member elsewhere in the
 * *importing project's own* spec -- so the same `$ref` (e.g.
 * `Core/common.json#/$defs/StorageCost`) comes out as `zod.enum(['STORAGE'])`
 * in `core` and `zod.literal("STORAGE")` in `operations`. It is a rendering
 * difference in the generator, not a difference in the schema.
 *
 * The two forms are interchangeable, verified rather than assumed:
 *   - runtime: both accept only "X" and reject everything else, returning the
 *     same value ('STORAGE', 'storage', 'THERMAL', '', 1, null, undefined, {}
 *     all agree)
 *   - types:  `zod.input` of each is mutually assignable, i.e. the same type
 *
 * Deliberately narrow: ONLY a one-element enum collapses. A two-element enum
 * is a real difference and must still fail loudly, which is the whole contract
 * of this comparator.
 */
function canonicalizeSingletonEnums(text: string): string {
  return text.replace(/zod\.enum\(\[\s*'([^']*)'\s*\]\)/g, (_m, value) => `zod.literal("${value}")`);
}

interface ParsedFile {
  header: string;
  entries: Entry[];
  tail: string;
}

const TYPE_PAIR_RE = /^export type (\w+) = zod\.input<typeof \1>;\nexport type \1Output = zod\.output<typeof \1>;\n/gm;
const PREAMBLE_LINE_RE = /^export const (\w+) = [^\n]*;$/gm;
const HEADER_END_RE = /^export const /m;

function domainNames(): string[] {
  return readdirSync(SRC_DIR, { withFileTypes: true })
    .filter((e) => e.isDirectory() && existsSync(join(SRC_DIR, e.name, "models.ts")))
    .map((e) => e.name)
    .sort();
}

function parsePreambleConsts(path: string, ownerName: string, text: string): PreambleConst[] {
  const consts: PreambleConst[] = [];
  PREAMBLE_LINE_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = PREAMBLE_LINE_RE.exec(text))) {
    consts.push({ ident: m[1], line: m[0] });
  }
  const remainder = text.replace(PREAMBLE_LINE_RE, "").trim();
  if (remainder.length > 0) {
    throw new Error(
      `${path}: unexpected content in ${ownerName}'s preamble (helper consts before its own ` +
        `schema declaration) -- expected only single-line "export const X = ...;" statements ` +
        `separated by blank lines. Got:\n${text}`,
    );
  }
  return consts;
}

function parseModelsFile(path: string): ParsedFile {
  const content = readFileSync(path, "utf8");

  const headerMatch = HEADER_END_RE.exec(content);
  if (!headerMatch) {
    throw new Error(`${path}: no top-level "export const" found -- expected at least one schema.`);
  }
  const headerEnd = headerMatch.index;

  const entries: Entry[] = [];
  let cursor = headerEnd;
  TYPE_PAIR_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = TYPE_PAIR_RE.exec(content))) {
    const name = match[1];
    const typePairEnd = TYPE_PAIR_RE.lastIndex;
    const ownConstMarker = `export const ${name} = `;
    const ownConstStart = content.indexOf(ownConstMarker, cursor);
    if (ownConstStart === -1 || ownConstStart >= match.index) {
      throw new Error(`${path}: could not locate "${ownConstMarker}" before its type-pair for ${name}.`);
    }
    const preambleConsts = parsePreambleConsts(path, name, content.slice(cursor, ownConstStart));
    entries.push({
      name,
      raw: content.slice(cursor, typePairEnd),
      body: content.slice(ownConstStart, typePairEnd),
      preambleConsts,
    });
    cursor = typePairEnd;
  }
  if (entries.length === 0) {
    throw new Error(`${path}: found no schema type-pairs (export type X = zod.input<typeof X>; ...).`);
  }

  const header = content.slice(0, headerEnd);
  const tail = content.slice(cursor);
  const reconstructed = header + entries.map((e) => e.raw).join("") + tail;
  if (reconstructed !== content) {
    throw new Error(
      `${path}: parser could not fully account for the file's content -- reconstruction differs ` +
        `from the original. A formatting assumption broke; refusing to guess.`,
    );
  }
  return { header, entries, tail };
}

function referencedElsewhere(fullContent: string, entryRaw: string, ident: string): boolean {
  const withoutEntry = fullContent.replace(entryRaw, "");
  return new RegExp(`\\b${ident}\\b`).test(withoutEntry);
}

/** A plain prefix/suffix-trimmed line diff -- enough to show what differs without a dependency. */
function renderDiff(nameA: string, textA: string, nameB: string, textB: string): string {
  const linesA = textA.split("\n");
  const linesB = textB.split("\n");
  let start = 0;
  while (start < linesA.length && start < linesB.length && linesA[start] === linesB[start]) start++;
  let endA = linesA.length;
  let endB = linesB.length;
  while (endA > start && endB > start && linesA[endA - 1] === linesB[endB - 1]) {
    endA--;
    endB--;
  }
  const out: string[] = [`--- ${nameA}`, `+++ ${nameB}`];
  for (const l of linesA.slice(start, endA)) out.push(`-${l}`);
  for (const l of linesB.slice(start, endB)) out.push(`+${l}`);
  return out.join("\n");
}

interface Mismatch {
  domain: string;
  owner: string;
  name: string;
  diff: string;
}

/**
 * Computes domain's post-processed content. Never writes anything and never
 * exits: a mismatch is appended to `mismatches` and that entry is left
 * untouched in the returned content, so a single pass over all six domains
 * can surface every mismatch in the tree at once instead of stopping at the
 * first. The caller decides what an accumulated `mismatches` means (see
 * `main`: any mismatch anywhere aborts the whole run before anything is
 * written -- never guess which side wins).
 */
function rewriteDomain(
  domain: string,
  parsed: ParsedFile,
  ownerOf: ReadonlyMap<string, string>,
  ownerEntries: ReadonlyMap<string, ReadonlyMap<string, Entry>>,
  mismatches: Mismatch[],
): { content: string; rewritten: string[] } {
  const fullOriginal = parsed.header + parsed.entries.map((e) => e.raw).join("") + parsed.tail;
  const parts: string[] = [parsed.header];
  const rewritten: string[] = [];

  for (const entry of parsed.entries) {
    const owner = ownerOf.get(entry.name);
    if (owner && owner !== domain) {
      const ownerEntry = ownerEntries.get(owner)!.get(entry.name)!;
      if (normalizedText(ownerEntry) !== normalizedText(entry)) {
        mismatches.push({
          domain,
          owner,
          name: entry.name,
          diff: renderDiff(
            `${owner}/models.ts`,
            normalizedText(ownerEntry),
            `${domain}/models.ts`,
            normalizedText(entry),
          ),
        });
        parts.push(entry.raw);
        continue;
      }
      for (const c of entry.preambleConsts) {
        if (referencedElsewhere(fullOriginal, entry.raw, c.ident)) {
          parts.push(c.line + "\n");
        }
      }
      parts.push(`export { ${entry.name} } from '../${owner}/models';\n`);
      parts.push(`export type { ${entry.name}Output } from '../${owner}/models';\n\n`);
      rewritten.push(entry.name);
    } else {
      parts.push(entry.raw);
    }
  }
  parts.push(parsed.tail);

  // *Default consts are load-bearing (feed real .default(...) calls) but are
  // not meant to be public surface -- drop only the `export` keyword so they
  // keep working as plain module-local consts. Applied last, over the whole
  // rewritten file, so it also catches a Default const that survived a
  // duplicate's deletion because something else in the file still uses it.
  const content = parts.join("").replace(/^export const (\w+Default) = /gm, "const $1 = ");
  return { content, rewritten };
}

/**
 * Targeted fixes for defects orval introduces that the schema cannot express.
 * The Python side keeps the same kind of pipeline in
 * `codegen/python/postprocess.py`; each fix here is one function with a
 * docstring naming the generator behaviour it works around.
 *
 * Returns the fixed text and the number of substitutions made.
 */
function applyGeneratorFixes(
  content: string,
  resolvedSchemas: ReadonlyMap<string, ResolvedSchema>,
  schemaDefaults: ReadonlyMap<string, Readonly<Record<string, unknown>>>,
): [string, number, string[]] {
  let fixes = 0;
  let out = content;
  let stripped: string[];

  [out, fixes] = fixEmptyArrayDefaults(out, fixes);
  [out, fixes] = fixMissingCostCurvePowerUnits(out, fixes);
  [out, fixes] = restoreDroppedSchemaDefaults(out, schemaDefaults, fixes);
  [out, fixes, stripped] = stripUndeclaredTopLevelDefaults(out, resolvedSchemas, fixes);

  return [out, fixes, stripped];
}

/**
 * Annotate `const xDefault = [];` so it does not infer `any[]`.
 *
 * A schema `default: []` renders as a bare empty array literal, which under
 * `--strict` is an implicit `any[]` and fails `noImplicitAny` at both the
 * declaration and the use site. `never[]` is assignable to whatever element
 * type the consuming `zod.array(...)` expects, so it types correctly without
 * asserting an element type the schema never stated.
 *
 * Affects the outage models' `monitored_components` (FixedForcedOutage,
 * GeometricDistributionForcedOutage, PlannedOutage).
 */
function fixEmptyArrayDefaults(content: string, fixes: number): [string, number] {
  let count = 0;
  const out = content.replace(/^const (\w*Default) = \[\];$/gm, (_m, name) => {
    count += 1;
    return `const ${name}: never[] = [];`;
  });
  return [out, fixes + count];
}

/**
 * Restore `power_units` in composite defaults that embed a `CostCurve`.
 *
 * `CostCurve.power_units` is BOTH schema-`required` and schema-`default:
 * NATURAL_UNITS` (Core/common.json). orval honours the required-list when it
 * builds the zod object but drops the default when it renders an enclosing
 * literal, so a composite default such as `sourceOperationCostDefault` emits
 * `import_offer_curves`/`export_offer_curves` without `power_units` and no
 * longer satisfies the very schema it is the default for.
 *
 * This is the TypeScript analogue of the Python side's
 * `fix_required_fields_with_schema_defaults`, and restores the same value both the
 * bundled spec and the Julia side already agree on.
 *
 * Recognition is deliberately narrow: an object literal that OPENS with the
 * CostCurve marker field `"variable_cost_type": "COST"`. This runs before
 * prettier, so it must match orval's raw emission -- one line, keys quoted --
 * not the formatted result.
 */
function fixMissingCostCurvePowerUnits(content: string, fixes: number): [string, number] {
  let count = 0;
  const out = content.replace(
    /\{ "variable_cost_type": "COST" as const,/g,
    (match) => {
      count += 1;
      return `{ "power_units": "NATURAL_UNITS" as const,` + match.slice(1);
    },
  );
  return [out, fixes + count];
}

// ---------------------------------------------------------------------------
// Dropped schema defaults -- orval sometimes emits `.optional()` (or neither
// `.optional()` nor `.default()` at all, for a schema-required-with-default
// property such as `CostCurve.power_units`) for a property the schema
// itself declares a `default` for, with no `.default(...)` call anywhere to
// materialize it -- an omitted field then loads as `undefined` in
// TypeScript where pydantic (and Julia) materialize the schema default.
// Restored generally, from every property's own schema node under
// $SCHEMA_DIR, never from a hardcoded field list -- see
// `restoreDroppedSchemaDefaults` below.
// ---------------------------------------------------------------------------

/** A `$ref`'s resolution context: the document it would resolve a bare
 * `#/...` fragment against, and the directory a file-qualified `$ref`
 * resolves relative to. */
interface RefContext {
  doc: unknown;
  dir: string;
}

/**
 * Resolves a `$ref` string to its target node plus the context any FURTHER
 * `$ref` inside that target must resolve against -- needed because a nested
 * `$ref` can be either file-qualified and relative to ITS OWN file (e.g.
 * `TwoTerminalLCCLine.json`'s own
 * `"../../Core/common.json#/$defs/LossCurve"`, relative to
 * `Operations/Branch/`, not $SCHEMA_DIR), or a same-document fragment with
 * no file part at all (`"#/$defs/InputOutputCurve"`, common.json referring
 * to one of its own `$defs`), which must resolve against the CURRENT
 * document rather than trying to re-read a nonexistent empty-string file.
 * Threading `{doc, dir}` through every hop (rather than just `dir`) is what
 * lets `materializeDefault` keep resolving correctly arbitrarily deep.
 */
function resolveRef(ref: string, ctx: RefContext): { node: unknown; ctx: RefContext } {
  const [filePart, fragment] = ref.split("#");
  let doc = ctx.doc;
  let dir = ctx.dir;
  if (filePart) {
    const filePath = join(ctx.dir, filePart);
    doc = loadSchemaJson(filePath);
    dir = dirname(filePath);
  }
  let node: any = doc;
  if (fragment) {
    for (const part of fragment.split("/").filter(Boolean)) {
      node = node?.[part];
    }
  }
  return { node, ctx: { doc, dir } };
}

const MAX_MATERIALIZE_DEPTH = 20;

/**
 * Fully materializes a schema default the way pydantic's `validate_default`
 * does at runtime (see `codegen/python/postprocess.py`'s
 * `fix_required_fields_with_schema_defaults`, whose `default_factory=lambda:
 * X.model_validate(...)` runs the SAME raw literal default through the real
 * model): a nested object's OWN properties are walked, and any property the
 * literal default omits but that itself carries a schema default (e.g.
 * `RenewableGenerationCost.curtailment_cost`'s default omits `power_units`,
 * relying on `CostCurve.power_units`'s own default) is filled in --
 * recursively, since a filled-in property can itself be a $ref'd object with
 * further omitted-but-defaulted properties of its own. A plain scalar (no
 * `properties` on its resolved schema) or an already-fully-specified object
 * is returned unchanged, so this is a no-op for the common case and only
 * does work where a raw literal default is genuinely incomplete.
 */
function materializeDefault(node: unknown, ctx: RefContext, value: unknown, depth = 0): unknown {
  if (depth > MAX_MATERIALIZE_DEPTH) {
    throw new Error(`materializeDefault: exceeded depth ${MAX_MATERIALIZE_DEPTH} -- suspect a $ref cycle`);
  }
  let resolved: any = node;
  let curCtx = ctx;
  if (resolved && typeof resolved === "object" && typeof resolved.$ref === "string") {
    const r = resolveRef(resolved.$ref, curCtx);
    resolved = r.node;
    curCtx = r.ctx;
  }
  const properties = resolved?.properties;
  if (!properties || typeof properties !== "object" || value === null || typeof value !== "object" || Array.isArray(value)) {
    return value;
  }
  const obj = value as Record<string, unknown>;
  const result: Record<string, unknown> = {};
  for (const [propName, propNode] of Object.entries(properties as Record<string, any>)) {
    if (propName in obj) {
      result[propName] = materializeDefault(propNode, curCtx, obj[propName], depth + 1);
    } else if (propNode && typeof propNode === "object" && "default" in propNode) {
      result[propName] = materializeDefault(propNode, curCtx, propNode.default, depth + 1);
    }
  }
  return result;
}

/** One top-level schema's resolved shape -- shared by both directions of the
 * schema-default fix (`restoreDroppedSchemaDefaults` inserts a dropped one,
 * `stripUndeclaredTopLevelDefaults` removes an invented one), so both read
 * off the exact same resolution instead of re-implementing `$ref`
 * resolution twice. */
interface ResolvedSchema {
  properties: Record<string, unknown>;
  required: Set<string>;
  ctx: RefContext;
}

/**
 * Maps every top-level schema name (a domain spec's `components.schemas`
 * key, same as `loadCanonicalSchemaNames`) to its resolved `properties`,
 * `required` list, and `$ref` context -- resolving the one level of `$ref`
 * every `components.schemas` entry is (verified: every current entry is a
 * bare `$ref`, never inline -- same fact the Makefile documents for the
 * Python side). A name already seen from an earlier domain in
 * `DOMAIN_SPECS` is left alone -- every domain that shares a name resolves
 * to the same underlying schema file, so the first hit is as good as any.
 */
function resolveTopLevelSchemas(schemaDir: string): Map<string, ResolvedSchema> {
  const result = new Map<string, ResolvedSchema>();
  for (const specName of DOMAIN_SPECS) {
    const specPath = join(schemaDir, specName);
    if (!existsSync(specPath)) continue;
    const spec = loadSchemaJson(specPath) as any;
    const schemas = spec?.components?.schemas ?? {};
    const specCtx: RefContext = { doc: spec, dir: schemaDir };
    for (const [name, node] of Object.entries(schemas as Record<string, any>)) {
      if (result.has(name)) continue;
      const ref = node?.$ref;
      const { node: resolved, ctx } = typeof ref === "string" ? resolveRef(ref, specCtx) : { node, ctx: specCtx };
      const properties = (resolved as any)?.properties;
      if (!properties || typeof properties !== "object") continue;
      const required = new Set<string>(
        Array.isArray((resolved as any)?.required) ? (resolved as any).required : [],
      );
      result.set(name, { properties, required, ctx });
    }
  }
  return result;
}

/**
 * Maps every top-level schema name to the `{propertyName: default}` pairs
 * its own resolved schema declares. Only properties that actually carry a
 * schema-level `default` are kept; the rest of a schema's properties are
 * irrelevant to this fix (see `stripUndeclaredTopLevelDefaults` for the
 * mirror-image question, which needs the full property/required sets
 * `resolveTopLevelSchemas` returns instead of just this filtered view).
 */
function buildSchemaPropertyDefaults(
  resolved: ReadonlyMap<string, ResolvedSchema>,
): Map<string, Record<string, unknown>> {
  const result = new Map<string, Record<string, unknown>>();
  for (const [name, { properties, ctx }] of resolved) {
    const defaults: Record<string, unknown> = {};
    for (const [propName, propNode] of Object.entries(properties as Record<string, any>)) {
      if (propNode && typeof propNode === "object" && "default" in propNode) {
        defaults[propName] = materializeDefault(propNode, ctx, (propNode as any).default);
      }
    }
    if (Object.keys(defaults).length > 0) result.set(name, defaults);
  }
  return result;
}

// --- Minimal bracket/string-aware text scanning, enough to locate one field's
// own top-level modifier chain without a full zod-call-chain parser. Mirrors
// scripts/check_cross_language.py's `_ts_mask_strings` / `_ts_matching_bracket`
// / `_ts_split_top_level_spans` / `_ts_parse_call_chain` (same algorithm,
// ported rather than shared, since that script is Python and out of this
// agent's scope). ---

const WHITESPACE = new Set([" ", "\t", "\r", "\n"]);
const OPENERS = new Set(["(", "{", "["]);
const CLOSERS = new Set([")", "}", "]"]);
const IDENT_RE = /[$A-Za-z_][$A-Za-z0-9_]*/y;
// A field key, quoted or bare: orval's raw (pre-prettier) output quotes every
// object key (`"power_units": zod...`); prettier later drops quotes it
// doesn't need. This runs before prettier, so both spellings must match.
const FIELD_KEY_RE = /^\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|([A-Za-z_$][A-Za-z0-9_$]*))\s*:\s*/s;

/** Boolean-per-character mask marking positions inside a JS string/template
 * literal, so a bracket scan can skip a stray `(`/`{`/`,` inside one of this
 * file's long `.describe("...")` prose strings. */
function maskStrings(text: string): Uint8Array {
  const mask = new Uint8Array(text.length);
  let quote: string | null = null;
  let i = 0;
  const n = text.length;
  while (i < n) {
    const c = text[i];
    if (quote !== null) {
      mask[i] = 1;
      if (c === "\\" && i + 1 < n) {
        mask[i + 1] = 1;
        i += 2;
        continue;
      }
      if (c === quote) quote = null;
      i += 1;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      quote = c;
      mask[i] = 1;
    }
    i += 1;
  }
  return mask;
}

/** Index of the bracket matching `text[openPos]`, one shared depth counter
 * across `([{` -- safe since mismatched nesting is a TypeScript syntax error
 * in generated code -- skipping masked (string) characters. */
function matchingBracket(text: string, mask: Uint8Array, openPos: number): number {
  let depth = 0;
  for (let i = openPos; i < text.length; i++) {
    if (!mask[i]) {
      const c = text[i];
      if (OPENERS.has(c)) depth += 1;
      else if (CLOSERS.has(c)) {
        depth -= 1;
        if (depth === 0) return i;
      }
    }
  }
  throw new Error(`unbalanced brackets from index ${openPos}`);
}

/** `[start, end)` spans of `text[from:to)` split on depth-0, unmasked commas. */
function splitTopLevelSpans(text: string, mask: Uint8Array, from: number, to: number): Array<[number, number]> {
  const spans: Array<[number, number]> = [];
  let depth = 0;
  let start = from;
  for (let i = from; i < to; i++) {
    if (mask[i]) continue;
    const c = text[i];
    if (OPENERS.has(c)) depth += 1;
    else if (CLOSERS.has(c)) depth -= 1;
    else if (c === "," && depth === 0) {
      spans.push([start, i]);
      start = i + 1;
    }
  }
  if (start < to && text.slice(start, to).trim()) spans.push([start, to]);
  return spans;
}

interface ChainCall {
  name: string;
  dotIndex: number;
  argsStart: number;
  argsEnd: number;
}

/** Parses a `zod` method chain starting at `text[pos:]` (leading whitespace
 * tolerated): `calls[0]` is the core type call (`object`/`enum`/`union`/...),
 * everything after a modifier (`describe`/`optional`/`default`/...). Returns
 * the parsed calls and the position right after the last one, so a caller
 * with no matching modifier at all still gets a usable insertion point. */
function parseCallChain(text: string, mask: Uint8Array, pos: number): { calls: ChainCall[]; end: number } {
  const n = text.length;
  while (pos < n && WHITESPACE.has(text[pos])) pos++;
  IDENT_RE.lastIndex = pos;
  const head = IDENT_RE.exec(text);
  if (!head || head[0] !== "zod") {
    throw new Error(`expected a zod expression at index ${pos}: ${text.slice(pos, pos + 60)}`);
  }
  pos = IDENT_RE.lastIndex;
  const calls: ChainCall[] = [];
  while (true) {
    let j = pos;
    while (j < n && WHITESPACE.has(text[j])) j++;
    if (j >= n || text[j] !== ".") return { calls, end: pos };
    const dotIndex = j;
    j += 1;
    while (j < n && WHITESPACE.has(text[j])) j++;
    IDENT_RE.lastIndex = j;
    const m = IDENT_RE.exec(text);
    if (!m) return { calls, end: pos };
    const nameParts = [m[0]];
    j = IDENT_RE.lastIndex;
    // A namespace access (`zod.iso.datetime(...)`, zod v4's date/time family)
    // chains bare identifiers before the parens appear; fold them into one
    // dotted call name rather than misreading `iso` as a paren-less call.
    while (true) {
      let k = j;
      while (k < n && WHITESPACE.has(text[k])) k++;
      if (k >= n || text[k] !== ".") break;
      let k2 = k + 1;
      while (k2 < n && WHITESPACE.has(text[k2])) k2++;
      IDENT_RE.lastIndex = k2;
      const m2 = IDENT_RE.exec(text);
      if (!m2) break;
      nameParts.push(m2[0]);
      j = IDENT_RE.lastIndex;
    }
    while (j < n && WHITESPACE.has(text[j])) j++;
    if (j >= n || text[j] !== "(") return { calls, end: pos };
    const close = matchingBracket(text, mask, j);
    calls.push({ name: nameParts.join("."), dotIndex, argsStart: j + 1, argsEnd: close });
    pos = close + 1;
  }
}

/** `[innerStart, innerEnd)` of `text`'s outermost `openChar ... matching-close`
 * pair starting at or after `start` (leading whitespace tolerated), or null
 * if `text[start:]` doesn't open with `openChar`. */
function bracketedBodyAbs(text: string, mask: Uint8Array, start: number, openChar: string): [number, number] | null {
  let i = start;
  while (i < text.length && WHITESPACE.has(text[i])) i++;
  if (i >= text.length || text[i] !== openChar) return null;
  const close = matchingBracket(text, mask, i);
  return [i + 1, close];
}

/**
 * The `.object({...})` call that actually declares a schema's direct
 * properties, whether it is `calls[0]` directly (the common shape) or
 * buried inside one or more `.and(...)` calls -- orval's rendering of an
 * `allOf` schema, e.g. `zod.unknown().and(zod.unknown()).and(zod.object({
 * ... }))` for `EmissionsData` (its schema composes over two placeholder
 * branches before the real object). Recurses into every `.and(...)`
 * argument's own chain and keeps the LAST object found, mirroring
 * `allOf`'s own semantics: a later branch's properties are the ones that
 * end up on the merged object. Returns null for a schema with no direct
 * object shape at all (an enum, a bare union, ...), which simply has no
 * top-level fields for this fix to restore a default onto.
 */
function findObjectCall(content: string, mask: Uint8Array, calls: ChainCall[]): ChainCall | null {
  if (calls.length > 0 && calls[0].name === "object") return calls[0];
  let found: ChainCall | null = null;
  for (const call of calls) {
    if (call.name !== "and") continue;
    let nested: { calls: ChainCall[]; end: number };
    try {
      nested = parseCallChain(content, mask, call.argsStart);
    } catch {
      continue;
    }
    const inner = findObjectCall(content, mask, nested.calls);
    if (inner !== null) found = inner;
  }
  return found;
}

function jsKeyLiteral(key: string): string {
  return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(key) ? key : JSON.stringify(key);
}

/**
 * Renders a JSON schema default as a TS literal usable directly as a
 * `.default(...)` argument. `nested` (true for anything inside an object/
 * array literal, false for the literal passed straight to `.default(...)`)
 * controls `as const`: a bare literal argument is already contextually
 * typed by `.default`'s own parameter type, but a fresh object/array
 * literal's own properties infer widened types (`string`, `number`) unless
 * pinned -- and a narrower type is always assignable where a wider one
 * (`zod.number()`, not a literal) is expected, so applying `as const`
 * uniformly to every nested leaf is always safe, never just where orval's
 * own renderer happens to need it.
 */
function renderDefaultValue(value: unknown, nested: boolean): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") {
    const lit = JSON.stringify(value);
    return nested ? `${lit} as const` : lit;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return nested ? `${value} as const` : `${value}`;
  }
  if (Array.isArray(value)) {
    return `[${value.map((v) => renderDefaultValue(v, true)).join(", ")}]`;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${jsKeyLiteral(k)}: ${renderDefaultValue(v, true)}`)
      .join(", ");
    return `{ ${entries} }`;
  }
  throw new Error(`renderDefaultValue: unsupported default value ${JSON.stringify(value)}`);
}

/**
 * Restores a property's schema `default` when orval drops it entirely.
 *
 * Scoped to each top-level schema's OWN direct properties (`zod.object({
 * ... })`'s immediate field list) -- never a nested property several
 * objects deep -- because that is exactly what both `python_default_value`
 * (pydantic's `model_fields`) and `_ts_field_info` in
 * scripts/check_cross_language.py compare; a property nested inside a
 * union branch or an inlined `$ref`'d sub-object is invisible to that
 * comparison either way, on both language sides, so fixing only the direct
 * fields is not a narrowing of the fix -- it is the fix matching what is
 * actually checked.
 *
 * For each top-level `export const Name = zod.object({ ... })` whose name
 * has schema-declared property defaults (`schemaDefaults`), every direct
 * field is checked for an existing `.default(...)` in its OWN modifier
 * chain (not a `.default(...)` belonging to some nested sub-schema deeper
 * inside the same field's value, e.g. a discriminant inside a `zod.union`
 * branch -- `parseCallChain` only walks calls chained directly off the
 * field's own top-level expression). A field with no default of its own
 * gets one inserted right before its `.describe(...)` call if present
 * (matching where orval itself places `.default(...)` when it does emit
 * one), else at the end of its chain.
 *
 * The rendered value is the schema's own literal `default`, never a
 * type's OWN default resolved one level deeper for a key the literal
 * itself omits (e.g. `RenewableGenerationCost.curtailment_cost`'s schema
 * default omits `power_units`, relying on `CostCurve.power_units`'s own
 * default) -- because that is exactly the same raw value
 * `python_default_value` reads for the same field (pydantic's declared
 * `default=`, not a materialized-and-dumped instance), so matching it
 * verbatim is what makes the two sides agree, not an approximation of it.
 */
function restoreDroppedSchemaDefaults(
  content: string,
  schemaDefaults: ReadonlyMap<string, Readonly<Record<string, unknown>>>,
  fixes: number,
): [string, number] {
  const mask = maskStrings(content);
  const edits: Array<{ at: number; text: string }> = [];

  const headerRe = /^export const (\w+) = /gm;
  let headerMatch: RegExpExecArray | null;
  while ((headerMatch = headerRe.exec(content))) {
    const name = headerMatch[1];
    const defaults = schemaDefaults.get(name);
    if (!defaults) continue;
    const valueStart = headerRe.lastIndex;
    if (content.slice(valueStart, valueStart + 3) !== "zod") continue;

    let chain: { calls: ChainCall[]; end: number };
    try {
      chain = parseCallChain(content, mask, valueStart);
    } catch {
      continue;
    }
    const objCall = findObjectCall(content, mask, chain.calls);
    if (objCall === null) continue;
    const bodyBounds = bracketedBodyAbs(content, mask, objCall.argsStart, "{");
    if (bodyBounds === null) continue;
    const [bodyStart, bodyEnd] = bodyBounds;

    for (const [start, end] of splitTopLevelSpans(content, mask, bodyStart, bodyEnd)) {
      const fieldText = content.slice(start, end);
      const keyMatch = FIELD_KEY_RE.exec(fieldText);
      if (!keyMatch) continue;
      // Orval's raw (pre-prettier) output quotes every key (`"power_units":
      // ...`); prettier later drops the quotes where they're not needed.
      // This runs before prettier, so both spellings must be recognized.
      const fieldName = keyMatch[1] ?? keyMatch[2] ?? keyMatch[3];
      if (!(fieldName in defaults)) continue;
      const valuePos = start + keyMatch[0].length;

      let fieldChain: { calls: ChainCall[]; end: number };
      try {
        fieldChain = parseCallChain(content, mask, valuePos);
      } catch {
        continue;
      }
      if (fieldChain.calls.some((c) => c.name === "default")) continue;

      const describeCall = [...fieldChain.calls].reverse().find((c) => c.name === "describe");
      const insertAt = describeCall ? describeCall.dotIndex : fieldChain.end;
      const rendered = renderDefaultValue(defaults[fieldName], false);
      edits.push({ at: insertAt, text: `.default(${rendered})\n` });
    }
  }

  // Applied last-to-first so an earlier edit's insertion never shifts a
  // later-in-the-loop-but-earlier-in-the-file edit's already-computed offset.
  edits.sort((a, b) => b.at - a.at);
  let out = content;
  for (const edit of edits) {
    out = out.slice(0, edit.at) + edit.text + out.slice(edit.at);
  }
  return [out, fixes + edits.length];
}

// ---------------------------------------------------------------------------
// Invented schema defaults -- the mirror-image defect. orval sometimes
// synthesizes a top-level `.default(...)` for a property whose OWN schema
// node carries no `default` at all, apparently by composing the property's
// referenced type's sub-properties' own defaults (verified:
// `FuelCurve.startup_fuel_offtake` -- Core/common.json's property node is a
// bare `{"$ref": "#/$defs/InputOutputCurve"}`, no sibling `default`, and
// `startup_fuel_offtake` is not in FuelCurve's `required` list -- gets
// `.default(fuelCurveStartupFuelOfftakeDefault)` anyway, a value composed
// from InputOutputCurve's own `curve_type`/`function_data` defaults). Python
// has no such default either (a plain `None`, since the property is
// optional and datamodel-codegen renders no default for it) -- so the
// invented TypeScript default is the divergence, not a real difference.
// Restored generally, from every property's own schema node under
// $SCHEMA_DIR, never from a hardcoded field list -- see
// `stripUndeclaredTopLevelDefaults` below.
// ---------------------------------------------------------------------------

/**
 * Strips a field's own top-level `.default(...)` call when the schema
 * declares no default for that property, replacing it with `.optional()` so
 * the field's requiredness is unchanged (a field with neither `.default()`
 * nor `.optional()`/`.nullish()` is REQUIRED under zod, and stripping the
 * default outright would silently flip this property from optional to
 * required). `.optional()` is exactly what orval itself emits for every
 * other true optional-with-no-default field in the same file (e.g.
 * `FuelCurve.input_at_zero: zod.number().optional()`), so this matches the
 * generator's own convention rather than inventing a new one.
 *
 * Exactly the mirror of `restoreDroppedSchemaDefaults`: same top-level-const
 * -> `zod.object({...})` -> per-field walk, same `parseCallChain`/
 * `findObjectCall`/`bracketedBodyAbs`/`splitTopLevelSpans` machinery, same
 * `ResolvedSchema` lookup (`resolveTopLevelSchemas`) -- just acting when a
 * field's own top-level chain HAS a `.default(...)` the schema does not
 * assert, instead of when it's missing one the schema does.
 *
 * Narrow by construction, so this cannot balloon into a broad rewrite: a
 * field is only touched when (a) its enclosing top-level const resolves to
 * a known schema, (b) that schema's own `properties[fieldName]` node
 * exists and carries no `default` of its own, (c) `fieldName` is not in
 * that schema's `required` list (a schema-required field with no default
 * is a different, pre-existing problem `fix_required_fields_with_schema_
 * defaults`'s TypeScript analogue would need to solve, not this fix's job),
 * and (d) the field's own TOP-LEVEL modifier chain (never a nested one --
 * `parseCallChain` only walks calls chained directly off the field's own
 * value expression, so a real schema default several levels down inside
 * the same field's value, e.g. `InputOutputCurve.curve_type`'s own `const`/
 * `default`, is untouched) already has a `.default(...)` call to remove.
 *
 * Returns the fixed text, the running fix count, and the list of
 * `type.field` names actually stripped, so the caller can report exactly
 * what changed rather than just a count -- if this fires on more than the
 * one known instance, that is a signal to stop and look, not to trust the
 * count blindly.
 */
function stripUndeclaredTopLevelDefaults(
  content: string,
  resolvedSchemas: ReadonlyMap<string, ResolvedSchema>,
  fixes: number,
): [string, number, string[]] {
  const mask = maskStrings(content);
  const edits: Array<{ start: number; end: number; text: string }> = [];
  const stripped: string[] = [];
  const orphanCandidates: string[] = [];

  const headerRe = /^export const (\w+) = /gm;
  let headerMatch: RegExpExecArray | null;
  while ((headerMatch = headerRe.exec(content))) {
    const name = headerMatch[1];
    const schema = resolvedSchemas.get(name);
    if (!schema) continue;
    const valueStart = headerRe.lastIndex;
    if (content.slice(valueStart, valueStart + 3) !== "zod") continue;

    let chain: { calls: ChainCall[]; end: number };
    try {
      chain = parseCallChain(content, mask, valueStart);
    } catch {
      continue;
    }
    const objCall = findObjectCall(content, mask, chain.calls);
    if (objCall === null) continue;
    const bodyBounds = bracketedBodyAbs(content, mask, objCall.argsStart, "{");
    if (bodyBounds === null) continue;
    const [bodyStart, bodyEnd] = bodyBounds;

    for (const [start, end] of splitTopLevelSpans(content, mask, bodyStart, bodyEnd)) {
      const fieldText = content.slice(start, end);
      const keyMatch = FIELD_KEY_RE.exec(fieldText);
      if (!keyMatch) continue;
      const fieldName = keyMatch[1] ?? keyMatch[2] ?? keyMatch[3];
      const propNode = schema.properties[fieldName];
      if (!propNode || typeof propNode !== "object") continue;
      if ("default" in (propNode as Record<string, unknown>)) continue;
      if (schema.required.has(fieldName)) continue;
      const valuePos = start + keyMatch[0].length;

      let fieldChain: { calls: ChainCall[]; end: number };
      try {
        fieldChain = parseCallChain(content, mask, valuePos);
      } catch {
        continue;
      }
      const defaultCall = fieldChain.calls.find((c) => c.name === "default");
      if (!defaultCall) continue;

      edits.push({ start: defaultCall.dotIndex, end: defaultCall.argsEnd + 1, text: ".optional()" });
      stripped.push(`${name}.${fieldName}`);
      // orval always renders a `.default(...)` call's argument as a bare
      // reference to a module-local `*Default` const (verified: every
      // current `.default(...)` in this generated tree, scalar or
      // composite, names one -- never an inline literal) -- so a plain
      // identifier match here is the const to check for orphaning below,
      // and anything else (which would mean that convention broke) is
      // simply left alone rather than guessed at.
      const argsText = content.slice(defaultCall.argsStart, defaultCall.argsEnd).trim();
      if (/^\w+Default$/.test(argsText)) orphanCandidates.push(argsText);
    }
  }

  // Applied last-to-first, same reason as `restoreDroppedSchemaDefaults`.
  edits.sort((a, b) => b.start - a.start);
  let out = content;
  for (const edit of edits) {
    out = out.slice(0, edit.start) + edit.text + out.slice(edit.end);
  }
  out = removeOrphanedDefaultConsts(out, orphanCandidates);
  return [out, fixes + edits.length, stripped];
}

/**
 * Deletes a module-local `const identDefault = ...;` declaration once
 * stripping its one `.default(identDefault)` reference (see
 * `stripUndeclaredTopLevelDefaults`) leaves it unreferenced anywhere else in
 * the file -- these `*Default` consts otherwise linger as dead code with no
 * remaining purpose. Checked by counting `\bident\b` occurrences left in the
 * already-edited content: exactly one means only the declaration itself
 * remains; more means it is still used somewhere (another field's default,
 * or nested inside a composite default this fix didn't touch) and is left
 * alone. The declaration's own end is found by scanning for the first
 * bracket-depth-0, unmasked `;` after `const ident = ` -- the same kind of
 * scan `_ts_find_top_level_semicolon` does on the Python side of this repo
 * -- since a composite default's own literal can itself contain semicolon-
 * free but multi-line object/array literals.
 */
function removeOrphanedDefaultConsts(content: string, candidates: readonly string[]): string {
  let out = content;
  for (const ident of candidates) {
    const usesRe = new RegExp(`\\b${ident}\\b`, "g");
    if ((out.match(usesRe) ?? []).length !== 1) continue;
    const declRe = new RegExp(`^const ${ident} = `, "m");
    const declMatch = declRe.exec(out);
    if (!declMatch) continue;
    const mask = maskStrings(out);
    let semiIdx: number;
    try {
      semiIdx = findTopLevelSemicolonFrom(out, mask, declMatch.index + declMatch[0].length);
    } catch {
      continue;
    }
    let end = semiIdx + 1;
    if (out[end] === "\n") end += 1;
    out = out.slice(0, declMatch.index) + out.slice(end);
  }
  return out;
}

/** Index of the first depth-0, unmasked `;` at or after `start`. */
function findTopLevelSemicolonFrom(text: string, mask: Uint8Array, start: number): number {
  let depth = 0;
  for (let i = start; i < text.length; i++) {
    if (mask[i]) continue;
    const c = text[i];
    if (OPENERS.has(c)) depth += 1;
    else if (CLOSERS.has(c)) depth -= 1;
    else if (c === ";" && depth === 0) return i;
  }
  throw new Error(`unterminated statement starting at ${start}`);
}

function main(): void {
  const domains = domainNames();
  const parsedByDomain = new Map<string, ParsedFile>();
  for (const domain of domains) {
    parsedByDomain.set(domain, parseModelsFile(join(SRC_DIR, domain, "models.ts")));
  }

  for (const owner of OWNER_PRECEDENCE) {
    if (!parsedByDomain.has(owner)) {
      throw new Error(`Expected an owner domain "${owner}" under ${SRC_DIR}, but it was not generated.`);
    }
  }

  // Acronym schema titles, before ownership/dedup: renaming an entry's
  // `name` here is what a later `export { NewName } from '../owner/models';`
  // cross-domain re-export line (generated below from `entry.name`, not
  // read back off disk) automatically picks up -- see `renameAcronymEntries`.
  const { names: canonicalNames, byUpper } = loadCanonicalSchemaNames(SCHEMA_DIR);
  for (const domain of domains) {
    const { parsed, renames } = renameAcronymEntries(parsedByDomain.get(domain)!, canonicalNames, byUpper);
    parsedByDomain.set(domain, parsed);
    for (const [oldName, newName] of renames) {
      console.log(`  Renamed ${domain}/models.ts: ${oldName} -> ${newName} (schema title)`);
    }
  }

  // Canonical ownership: earlier domains in OWNER_PRECEDENCE win. A name
  // already claimed by an earlier owner domain is a duplicate everywhere
  // else, including in a later owner domain (core's own copy of an
  // infrastructure_core type).
  const ownerOf = new Map<string, string>();
  const ownerEntries = new Map<string, ReadonlyMap<string, Entry>>();
  for (const owner of OWNER_PRECEDENCE) {
    const entries = parsedByDomain.get(owner)!.entries;
    const byName = new Map(entries.map((e) => [e.name, e] as const));
    ownerEntries.set(owner, byName);
    for (const entry of entries) {
      if (!ownerOf.has(entry.name)) ownerOf.set(entry.name, owner);
    }
  }

  // Computed for every domain before anything is written: a mismatch
  // anywhere must abort the whole run, never leave some domains rewritten
  // and others not.
  const mismatches: Mismatch[] = [];
  const results = new Map<string, { content: string; rewritten: string[] }>();
  for (const domain of domains) {
    results.set(domain, rewriteDomain(domain, parsedByDomain.get(domain)!, ownerOf, ownerEntries, mismatches));
  }

  if (mismatches.length > 0) {
    for (const m of mismatches) {
      console.error(
        `postprocess.ts: ${m.domain}/models.ts and ${m.owner}/models.ts both define ${m.name} ` +
          `but their bodies differ -- refusing to guess which one wins.\n\n${m.diff}\n`,
      );
    }
    console.error(
      `postprocess.ts: ${mismatches.length} duplicate schema(s) differ between domains. ` +
        `Nothing was written. See the diffs above.`,
    );
    process.exit(1);
  }

  const resolvedSchemas = resolveTopLevelSchemas(SCHEMA_DIR);
  const schemaDefaults = buildSchemaPropertyDefaults(resolvedSchemas);

  const dupCounts: Record<string, number> = {};
  const fixCounts: Record<string, number> = {};
  const strippedDefaults: string[] = [];
  for (const domain of domains) {
    const { content: deduped, rewritten } = results.get(domain)!;
    const [content, fixes, stripped] = applyGeneratorFixes(deduped, resolvedSchemas, schemaDefaults);
    fixCounts[domain] = fixes;
    strippedDefaults.push(...stripped);
    writeFileSync(join(SRC_DIR, domain, "models.ts"), content);
    writeFileSync(join(SRC_DIR, domain, "index.ts"), "export * from './models';\n");
    dupCounts[domain] = rewritten.length;
    if (rewritten.length > 0) {
      console.log(`  De-duplicated ${domain}/models.ts: ${rewritten.length} (${rewritten.join(", ")})`);
    }
  }
  if (strippedDefaults.length > 0) {
    console.log(
      `  Stripped ${strippedDefaults.length} invented default(s) the schema does not declare: ` +
        `${strippedDefaults.join(", ")}`,
    );
  }

  const total = Object.values(dupCounts).reduce((a, b) => a + b, 0);
  console.log(`  Total duplicates resolved: ${total}`);
  for (const domain of domains) {
    console.log(`    ${domain}: ${dupCounts[domain]}`);
  }
}

main();
