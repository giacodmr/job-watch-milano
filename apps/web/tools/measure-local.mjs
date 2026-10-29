// Optional local benchmark: ephemeral D1, no persistent DB or remote binding.
import { readFile, readdir, stat } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { build } from "esbuild";
import { convertV4MiniflareOptions, Miniflare } from "miniflare";
const app = resolve(dirname(fileURLToPath(import.meta.url)), "..");
let runtime;
try {
  const { values } = parseArgs({ options: { file: { type: "string" } } });
  const file = resolve(
    values.file || resolve(app, ".local-sync/snapshot.json"),
  );
  if ((await stat(file)).size > 32 * 1024 * 1024)
    throw new Error("BUNDLE_TOO_LARGE");
  const input = JSON.parse(await readFile(file, "utf8"));
  const built = await build({
    entryPoints: [resolve(app, "worker/data/importer.ts")],
    bundle: true,
    write: false,
    format: "esm",
    platform: "node",
  });
  const { importSnapshot } = await import(
    "data:text/javascript;base64," +
      Buffer.from(built.outputFiles[0].text).toString("base64")
  );
  runtime = new Miniflare(
    convertV4MiniflareOptions({
      modules: true,
      script: 'export default {fetch(){return new Response("local")}}',
      cf: false,
      compatibilityDate: "2026-10-29",
      d1Databases: { DB: "measurement" },
    }),
  );
  const db = await runtime.getD1Database("DB");
  for (const migration of (await readdir(resolve(app, "migrations")))
    .filter((f) => f.endsWith(".sql"))
    .sort()) {
    for (const sql of (
      await readFile(resolve(app, "migrations", migration), "utf8")
    ).split("-- statement-breakpoint"))
      if (sql.trim()) await db.prepare(sql).run();
  }
  const cold = await importSnapshot(db, input, {
    expectedRevision: 0,
    verifyAdvance: async () => true,
    maxRowsWritten: 500000,
  });
  const replay = await importSnapshot(db, input, {
    expectedRevision: 1,
    verifyAdvance: async () => true,
  });
  console.log(
    JSON.stringify({
      cold,
      replay,
      persistentDatabase: false,
      productionAccess: false,
    }),
  );
} catch (error) {
  console.error(
    JSON.stringify({
      error: /^[A-Z][A-Z0-9_]+$/.test(error?.message || "")
        ? error.message
        : "LOCAL_MEASUREMENT_FAILED",
      productionAccess: false,
    }),
  );
  process.exitCode = 1;
} finally {
  await runtime?.dispose();
}
