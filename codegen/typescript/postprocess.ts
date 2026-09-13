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
import { join } from "node:path";

const SRC_DIR = "typescript/src";

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
  return entry.preambleConsts.map((c) => c.line + "\n").join("") + entry.body;
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

  const dupCounts: Record<string, number> = {};
  for (const domain of domains) {
    const { content, rewritten } = results.get(domain)!;
    writeFileSync(join(SRC_DIR, domain, "models.ts"), content);
    writeFileSync(join(SRC_DIR, domain, "index.ts"), "export * from './models';\n");
    dupCounts[domain] = rewritten.length;
    if (rewritten.length > 0) {
      console.log(`  De-duplicated ${domain}/models.ts: ${rewritten.length} (${rewritten.join(", ")})`);
    }
  }

  const total = Object.values(dupCounts).reduce((a, b) => a + b, 0);
  console.log(`  Total duplicates resolved: ${total}`);
  for (const domain of domains) {
    console.log(`    ${domain}: ${dupCounts[domain]}`);
  }
}

main();
