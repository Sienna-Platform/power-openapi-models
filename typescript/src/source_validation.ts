/**
 * Hand-written (NOT generated): validation of an encoded document against the
 * strict bundle of an older schema release, for `writeDocument(...,
 * { schemaVersion: "source" })`. `ajv` is an optional peer dependency, loaded
 * on first use so the default install does not need it. Node only.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

// Resolved on use: import.meta.url is not a file URL in a browser bundle of the
// root entry, which must still load.
function defaultBundlesDir(): string {
  return fileURLToPath(new URL("../bundles/", import.meta.url));
}

interface AjvError {
  instancePath: string;
  message?: string;
  params: Record<string, unknown>;
}

interface AjvInstance {
  compile(schema: unknown): {
    (data: unknown): boolean;
    errors?: AjvError[] | null;
  };
}

type AjvConstructor = new (opts: Record<string, unknown>) => AjvInstance;

function loadAjv(specifier: string): AjvConstructor {
  const require = createRequire(import.meta.url);
  let mod: { default?: AjvConstructor } & AjvConstructor;
  try {
    mod = require(specifier);
  } catch (cause) {
    throw new Error(
      `writing with schemaVersion "source" to an older schema needs the optional ` +
        `peer dependency "${specifier}" (npm install ajv); it could not be loaded. ` +
        `Use schemaVersion "current" to skip validation.`,
      { cause },
    );
  }
  return mod.default ?? mod;
}

function describe(e: AjvError): string {
  const extra = e.params.additionalProperty;
  const path =
    typeof extra === "string" ? `${e.instancePath}/${extra}` : e.instancePath;
  return `${path === "" ? "/" : path}: ${e.message ?? "invalid"}`;
}

/**
 * Throws, listing every offending JSON path, unless `tree` is valid under the
 * `documentName` bundle of schema `version`.
 */
export function validateAgainstBundle(
  tree: unknown,
  documentName: string,
  version: string,
  reader: string,
  bundlesDir: string | undefined,
  ajvSpecifier: string,
): void {
  const Ajv = loadAjv(ajvSpecifier);
  const bundlePath = join(
    bundlesDir ?? defaultBundlesDir(),
    version,
    `${documentName}.json`,
  );
  let bundle: unknown;
  try {
    bundle = JSON.parse(readFileSync(bundlePath, "utf-8"));
  } catch (cause) {
    throw new Error(
      `no strict bundle for schema ${version} at ${bundlePath}; cannot write ` +
        `schemaVersion "source" without it`,
      { cause },
    );
  }
  // Bundles carry vendor keywords (x-unit, discriminator) and date-time
  // formats; ajv's strict mode would reject the schema over them.
  const validate = new Ajv({
    allErrors: true,
    strict: false,
    validateFormats: false,
  }).compile(bundle);
  if (validate(tree)) {
    return;
  }
  const lines = [...new Set((validate.errors ?? []).map(describe))].sort();
  throw new Error(
    `document is not valid under schema ${version} (reader is ${reader}); ` +
      `${lines.length} problem(s):\n` +
      lines.map((l) => `  ${l}`).join("\n") +
      `\nsave with schemaVersion: "current" to stamp ${reader} instead`,
  );
}
