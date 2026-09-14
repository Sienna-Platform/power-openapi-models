/**
 * Executes every fenced ```ts block in README.md.
 *
 * The counterpart of python/tests/test_readme.py, and for the same reason: a
 * README example that no longer runs is worse than no example, because a
 * reader trusts it. A block that is meant to illustrate something without
 * running (pseudo-code, a deliberate error) must be fenced as ```text
 * instead.
 *
 * Blocks import the package by its PUBLISHED name. That specifier does not
 * resolve inside this repo -- the package is not installed into itself -- so
 * each block is rewritten to the equivalent `../src/...` path before running.
 * The rewrite is the only edit made; if a block needs anything else changed
 * to run, the block is wrong.
 */
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterAll, describe, expect, it } from "vitest";

const PACKAGE_NAME = "@sienna-platform/power-openapi-models";
const TMP_DIR = join(import.meta.dirname, "..", ".readme-tmp");

/** `.../core` -> `../src/core`; the bare package -> `../src/index`. */
function rewriteImports(code: string): string {
  return code
    .replace(new RegExp(`"${PACKAGE_NAME}/([\\w/]+)"`, "g"), '"../src/$1"')
    .replace(new RegExp(`"${PACKAGE_NAME}"`, "g"), '"../src/index"');
}

function extractTsBlocks(markdown: string): string[] {
  const blocks: string[] = [];
  const fence = /^```ts\n([\s\S]*?)^```$/gm;
  let match: RegExpExecArray | null;
  while ((match = fence.exec(markdown)) !== null) blocks.push(match[1]);
  return blocks;
}

const readme = readFileSync(join(import.meta.dirname, "..", "README.md"), "utf8");
const blocks = extractTsBlocks(readme);

describe("README.md examples", () => {
  afterAll(() => rmSync(TMP_DIR, { recursive: true, force: true }));

  it("has ts blocks to check at all", () => {
    // Guards against a rewrite of the fence style silently emptying this
    // suite -- the same "passed because it checked nothing" failure mode the
    // cross-language gate had.
    expect(blocks.length).toBeGreaterThan(4);
  });

  blocks.forEach((block, index) => {
    it(`block ${index + 1} runs`, async () => {
      mkdirSync(TMP_DIR, { recursive: true });
      const file = join(TMP_DIR, `block-${index + 1}.ts`);
      writeFileSync(file, rewriteImports(block));
      await expect(import(/* @vite-ignore */ file)).resolves.toBeDefined();
    });
  });
});
