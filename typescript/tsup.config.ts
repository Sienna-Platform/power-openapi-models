import { defineConfig } from "tsup";

export default defineConfig({
  entry: {
    index: "src/index.ts",
    infrastructure_core: "src/infrastructure_core/index.ts",
    core: "src/core/index.ts",
    operations: "src/operations/index.ts",
    investments: "src/investments/index.ts",
    dynamics: "src/dynamics/index.ts",
    timeseries: "src/timeseries/index.ts",
    document: "src/document.ts",
  },
  format: ["esm", "cjs"],
  dts: true,
  sourcemap: true,
  clean: true,
  splitting: true,
});
