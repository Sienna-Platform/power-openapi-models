import { readFileSync } from "node:fs";

/** Reader version baked into the bundle: `schema-version` minus its leading `v`. */
export const define = {
  __SCHEMA_VERSION__: JSON.stringify(
    readFileSync(new URL("./schema-version", import.meta.url), "utf-8")
      .trim()
      .replace(/^v/, ""),
  ),
};
