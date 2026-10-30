// Node-only laboratory helpers. Never imported by the Worker or browser.
import { readFile, readdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { canonical, sha256 } from '../shared/canonical';
import { z } from 'zod';
export type Scope = 'catalog' | 'personal' | 'v1';
const app = resolve(import.meta.dirname, '..');
const ident = (s: string) => {
  if (!/^[a-z][a-z0-9_]*$/.test(s)) throw Error('UNSUPPORTED_SCHEMA_IDENTIFIER');
  return '"'+s+'"';
};
async function schemaRows(db: D1Database) {
  return (await db.prepare("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT GLOB '_*' AND name NOT GLOB 'sqlite_*' ORDER BY type,name")
    .all<{type:string;name:string;sql:string}>()).results;
}
export async function migrationSources(scope: Scope) {
  const dir = scope === 'v1' ? resolve(app,'migrations') : resolve(app,'model-c',scope,'migrations');
  const sources = [];
  for (const name of (await readdir(dir)).filter(n=>/^\d{4}_.*\.sql$/.test(n)).sort()) {
    const sql = await readFile(resolve(dir,name),'utf8');
    sources.push({name,sha256:await sha256(sql),statements:sql.split('-- statement-breakpoint').filter(s=>s.trim())});
  }
  return sources;
}
/** Hash-locked additive migrations; no Wrangler binding or persistent path. */
export async function applySchema(db: D1Database, scope: Scope) {
  if (!['catalog','personal','v1'].includes(scope)) throw Error('INVALID_SCHEMA_SCOPE');
  const schema = await schemaRows(db);
  const exists = (name: string) => schema.some(s=>s.name===name);
  if (scope!=='v1' && exists('schema_metadata')) throw Error('V1_DATABASE_REFUSED');
  if (scope==='v1' && exists('model_c_schema')) throw Error('WRONG_DATABASE_SCOPE');
  if (scope!=='v1' && exists('model_c_schema') && (await db.prepare('SELECT scope FROM model_c_schema WHERE id=1').first('scope'))!==scope.toUpperCase()) throw Error('WRONG_DATABASE_SCOPE');
  if (exists('model_c_migrations') && scope!=='v1' && !exists('model_c_schema')) throw Error('INCOMPLETE_SCHEMA');
  let rowsWritten=0, applied=0;
  const sources=await migrationSources(scope);
  for (const m of sources) {
    const previous = (await schemaRows(db)).some(s=>s.name==='model_c_migrations')
      ? await db.prepare('SELECT sha256 FROM model_c_migrations WHERE name=?').bind(m.name).first('sha256') : null;
    if (previous!==null) { if (previous!==m.sha256) throw Error('MIGRATION_HASH_MISMATCH'); continue; }
    const statements=[db.prepare('CREATE TABLE IF NOT EXISTS model_c_migrations (name TEXT PRIMARY KEY NOT NULL,sha256 TEXT NOT NULL CHECK(length(sha256)=64))'),
      ...m.statements.map(sql=>db.prepare(sql)),
      db.prepare('INSERT INTO model_c_migrations(name,sha256) VALUES (?,?)').bind(m.name,m.sha256)];
    for (const r of await db.batch(statements)) rowsWritten+=r.meta.rows_written??0;
    applied++;
  }
  return {scope,applied,rowsWritten};
}
const value = z.union([z.string(),z.number().finite(),z.null()]);
const backupDataSchema = z.strictObject({
  format:z.literal('job-watch-synthetic-d1/1'),scope:z.enum(['catalog','personal','v1']),
  schemaDigest:z.string().regex(/^[a-f0-9]{64}$/),
  tables:z.array(z.strictObject({name:z.string(),columns:z.array(z.string()),rows:z.array(z.array(value))})),
});
const backupSchema = z.strictObject({data:backupDataSchema,sha256:z.string().regex(/^[a-f0-9]{64}$/)});
export type SyntheticBackup = z.infer<typeof backupSchema>;
/** Bounded synthetic snapshot, not a production backup API. No credentials/path input. */
export async function captureSynthetic(db: D1Database, scope: Scope): Promise<SyntheticBackup> {
  const schema=await schemaRows(db), tables=[];
  let count=0;
  for (const t of schema.filter(s=>s.type==='table')) {
    const columns=(await db.prepare('PRAGMA table_info('+ident(t.name)+')').all<{name:string}>()).results.map(c=>c.name);
    const rows=(await db.prepare('SELECT * FROM '+ident(t.name)+' LIMIT 1001').all()).results
      .map(r=>columns.map(c=>value.parse(r[c]))).sort((a,b)=>canonical(a)<canonical(b)?-1:canonical(a)>canonical(b)?1:0);
    count+=rows.length;if(count>1000)throw Error('SYNTHETIC_BACKUP_LIMIT');
    tables.push({name:t.name,columns,rows});
  }
  const data=backupDataSchema.parse({format:'job-watch-synthetic-d1/1',scope,schemaDigest:await sha256(canonical(schema)),tables});
  return {data,sha256:await sha256(canonical(data))};
}
/** Restore ONLY to a new, empty ephemeral database, never over an existing DB. */
export async function restoreSynthetic(db: D1Database, scope: Scope, input: unknown) {
  const backup=backupSchema.parse(input);
  if (backup.data.scope!==scope) throw Error('WRONG_BACKUP_SCOPE');
  if (backup.sha256!==await sha256(canonical(backup.data))) throw Error('BACKUP_INTEGRITY_FAILED');
  if ((await schemaRows(db)).length) throw Error('RESTORE_TARGET_NOT_EMPTY');
  const setup=await applySchema(db,scope);
  const expected=await captureSynthetic(db,scope), schema=await schemaRows(db);
  if (expected.data.schemaDigest!==backup.data.schemaDigest ||
      canonical(expected.data.tables.map(t=>[t.name,t.columns]))!==canonical(backup.data.tables.map(t=>[t.name,t.columns]))) throw Error('BACKUP_SCHEMA_MISMATCH');
  if (canonical(expected.data.tables.find(t=>t.name==='model_c_migrations')?.rows) !== canonical(backup.data.tables.find(t=>t.name==='model_c_migrations')?.rows)) throw Error('BACKUP_MIGRATION_MISMATCH');
  const triggers=schema.filter(s=>s.type==='trigger');
  // An offline snapshot contains terminal states. State-transition triggers are
  // reinstated in the SAME transaction after the data, never disabled on a live DB.
  const statements=[...triggers.map(t=>db.prepare('DROP TRIGGER '+ident(t.name))),db.prepare('PRAGMA defer_foreign_keys=ON'),
    ...backup.data.tables.map(t=>db.prepare('DELETE FROM '+ident(t.name)))];
  let count=0;
  for (const t of backup.data.tables) for (const row of t.rows) {
    if(row.length!==t.columns.length || ++count>1000)throw Error('INVALID_SYNTHETIC_BACKUP');
    statements.push(db.prepare('INSERT INTO '+ident(t.name)+' ('+t.columns.map(ident).join(',')+') VALUES ('+row.map(()=>'?').join(',')+')').bind(...row));
  }
  statements.push(...triggers.map(t=>db.prepare(t.sql)));
  const results=await db.batch(statements);
  if ((await db.prepare('PRAGMA foreign_key_check').all()).results.length) throw Error('RESTORE_FOREIGN_KEY_FAILURE');
  if (await db.prepare('PRAGMA quick_check').first('quick_check')!=='ok')throw Error('RESTORE_INTEGRITY_FAILED');
  if ((await captureSynthetic(db,scope)).sha256!==backup.sha256)throw Error('RESTORE_CONTENT_MISMATCH');
  return {scope,verified:true,schemaRowsWritten:setup.rowsWritten,restoreBatchRowsWritten:results.reduce((n,r)=>n+(r.meta.rows_written??0),0)};
}
