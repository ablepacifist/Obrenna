#!/usr/bin/env node
/**
 * Code generation for the Obrenna workspace.
 *
 *  shared/artifact-schema.json  (single source of truth)
 *     ├─ json-schema-to-typescript ─► frontend/src/lib/types/artifact.ts
 *     └─ (Pydantic models are hand-authored in backend/app/schemas/artifact.py and
 *         guarded against drift by tests/test_schema_drift.py — see plan)
 *
 *  backend OpenAPI  ─ openapi-typescript ─► frontend/src/lib/types/api.ts
 *     (requires the backend importable; skipped with a warning if not)
 *
 * Generated TS files ARE committed so the frontend builds without running codegen.
 */
import { execSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const typesDir = resolve(root, "frontend/src/lib/types");
const schema = resolve(root, "shared/artifact-schema.json");
const openapiJson = resolve(typesDir, "openapi.json");

const run = (cmd, opts = {}) =>
  execSync(cmd, { cwd: root, stdio: "inherit", shell: true, ...opts });

mkdirSync(typesDir, { recursive: true });

// 1) Artifact types from the JSON Schema.
console.log("• Generating frontend/src/lib/types/artifact.ts from shared/artifact-schema.json");
run(
  `npx json2ts -i "${schema}" -o "${resolve(typesDir, "artifact.ts")}" --additionalProperties false --bannerComment "/* AUTO-GENERATED from shared/artifact-schema.json — do not edit by hand. Run \\\`npm run codegen\\\`. */"`
);

// 2) API types from the backend OpenAPI document (best-effort).
const pythons = ["python", "py", "python3"];
let openapiOk = false;
for (const py of pythons) {
  try {
    console.log(`• Dumping backend OpenAPI via ${py} scripts/dump_openapi.py`);
    run(`${py} scripts/dump_openapi.py "${openapiJson}"`, { stdio: "inherit" });
    openapiOk = existsSync(openapiJson);
    if (openapiOk) break;
  } catch {
    /* try next interpreter */
  }
}

if (openapiOk) {
  console.log("• Generating frontend/src/lib/types/api.ts from backend OpenAPI");
  run(`npx openapi-typescript "${openapiJson}" -o "${resolve(typesDir, "api.ts")}"`);
  rmSync(openapiJson, { force: true });
} else {
  console.warn(
    "! Skipped api.ts generation — could not import the backend.\n" +
      "  Install backend deps (backend/.venv) and re-run `npm run codegen`."
  );
}

console.log("✓ codegen complete");
