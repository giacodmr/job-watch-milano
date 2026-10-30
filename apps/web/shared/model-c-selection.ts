import { z } from 'zod';
import { canonical, sha256 } from './canonical';
import { validateBundle } from './snapshot';
import type { SnapshotRow } from './snapshot';

export const selectionContract = 'job-watch-model-c/1' as const;
const id = z.string().regex(/^job:[a-f0-9]{64}$/);
const identitySchema = z.strictObject({ jobId: id, companyId: z.string().min(1), originJobKey: z.string().min(1) });
const aliasSchema = z.strictObject({ key: z.string().min(1), jobId: id });
export const identityLedgerSchema = z.strictObject({
  identities: z.array(identitySchema), mappings: z.array(aliasSchema),
});
export type IdentityLedger = z.infer<typeof identityLedgerSchema>;
const contextSchema = z.strictObject({
  identities: z.discriminatedUnion('mode', [
    z.strictObject({ mode: z.literal('first-v1-bootstrap') }),
    z.strictObject({ mode: z.literal('confirmed-ledger'), ledger: identityLedgerSchema, expectedDigest: z.string().regex(/^[a-f0-9]{64}$/) }),
  ]),
  // These are already reconciled ACTIVE references, not a history to reorder here.
  personalReferences: z.array(z.strictObject({ jobId: id, kind: z.enum(['SAVED', 'APPLICATION', 'DISMISSED']) })),
});
export type SelectionContext = z.input<typeof contextSchema>;
type Job = Extract<SnapshotRow, { kind: 'job' }>;
const open = (j: Job) => ['NEW', 'STILL_OPEN', 'UPDATED'].includes(j.lifecycle);
const positive = (j: Job) => ['INTERESTED', 'TO_REVIEW', 'APPLIED'].includes(j.effectiveDecision ?? '');
const by = <T>(key: (row: T) => string) => (a: T, b: T) => key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0;
export class SelectionError extends Error {}
export async function selectionContextDigest(input: SelectionContext) {
  const context = contextSchema.parse(input);
  if (context.identities.mode === 'confirmed-ledger') {
    context.identities.ledger.identities.sort(by(r => r.jobId));
    context.identities.ledger.mappings.sort(by(r => r.key));
  }
  context.personalReferences.sort(by(r => r.jobId + '\0' + r.kind));
  return sha256(canonical(context));
}

/** Pure selection, not an importer or a second implementation of Python policy. */
export async function selectModelC(input: unknown, rawContext: SelectionContext) {
  const bundle = await validateBundle(input), context = contextSchema.parse(rawContext);
  const identities = new Map<string, z.infer<typeof identitySchema>>();
  const mappings = new Map<string, string>();
  if (context.identities.mode === 'confirmed-ledger') {
    const normalized = { identities: [...context.identities.ledger.identities].sort(by(r => r.jobId)), mappings: [...context.identities.ledger.mappings].sort(by(r => r.key)) };
    if (await sha256(canonical(normalized)) !== context.identities.expectedDigest) throw new SelectionError('LEDGER_DIGEST_MISMATCH');
    for (const item of context.identities.ledger.identities) {
      if (identities.has(item.jobId)) throw new SelectionError('DUPLICATE_LEDGER_ID');
      identities.set(item.jobId, item);
    }
    for (const item of context.identities.ledger.mappings) {
      if (mappings.has(item.key) || !identities.has(item.jobId)) throw new SelectionError('INVALID_LEDGER_MAPPING');
      mappings.set(item.key, item.jobId);
    }
    for (const item of identities.values()) {
      if (mappings.get(item.originJobKey) !== item.jobId) throw new SelectionError('MISSING_ORIGIN_MAPPING');
    }
  }
  const rows = bundle.chunks.flat(), jobs = rows.filter((r): r is Job => r.kind === 'job');
  const observed = new Map<string, string>();
  for (const job of jobs) {
    const keys = [job.jobKey, ...job.aliases];
    const found = new Set(keys.map(k => mappings.get(k)).filter((v): v is string => v !== undefined));
    if (found.size > 1) throw new SelectionError('AMBIGUOUS_LEDGER_IDENTITY');
    const jobId = [...found][0] ?? 'job:' + await sha256(job.companyId + '\0' + job.jobKey);
    const known = identities.get(jobId);
    if (known && known.companyId !== job.companyId) throw new SelectionError('CROSS_COMPANY_IDENTITY');
    if (observed.has(jobId)) throw new SelectionError('DUPLICATE_OBSERVED_IDENTITY');
    identities.set(jobId, known ?? { jobId, companyId: job.companyId, originJobKey: job.jobKey });
    observed.set(jobId, job.jobKey);
    for (const key of keys) mappings.set(key, jobId);
  }
  for (const ref of context.personalReferences) {
    if (!identities.has(ref.jobId)) throw new SelectionError('UNRESOLVED_PERSONAL_REFERENCE');
  }
  function events<K extends 'user' | 'semantic'>(kind: K) {
    const result = new Map<string, { eventId: string; jobId: string; observations: Extract<SnapshotRow, { kind: K }>[] }>();
    for (const row of rows) if (row.kind === kind) {
      const jobId = mappings.get(row.jobKey);
      if (!jobId) throw new SelectionError('UNRESOLVED_EVENT');
      const key = jobId + '\0' + row.resultSha256;
      const event = result.get(key) ?? { eventId: '', jobId, observations: [] };
      const payload = (value: SnapshotRow) => Object.fromEntries(Object.entries(value).filter(([name]) => !['jobKey','sourcePath','sourceSha256'].includes(name)));
      if (event.observations[0] && canonical(payload(event.observations[0])) !== canonical(payload(row))) throw new SelectionError('CONFLICTING_EVENT_FACTS');
      event.observations.push(row as Extract<SnapshotRow, { kind: K }>);
      result.set(key, event);
    }
    return result;
  }
  const user = events('user'), semantic = events('semantic');
  for (const [key, event] of user) event.eventId = 'decision:' + await sha256(key);
  for (const [key, event] of semantic) event.eventId = 'review:' + await sha256(key);
  const userJobs = new Set([...user.values()].map(e => e.jobId));
  const refs = (jobId: string) => context.personalReferences.filter(ref => ref.jobId === jobId);
  const subjects = new Map<string, { jobId: string; catalog: boolean; personal: boolean; aiQueue: boolean; lifecycle: Job['lifecycle'] | null; exclusion: 'MANUAL' | 'AUTOMATIC' | 'UNRESOLVED_PERSONAL' | null }>();
  const catalog: { jobId: string; kind: 'OPPORTUNITY' | 'AI_QUEUE' }[] = [];
  const aiQueue: { jobId: string; batch: Job['batch']; fingerprint: string | null; applyUrl: string | null; canonicalUrl: string | null; workerEligible: boolean | null; technicalStatus: string | null }[] = [];
  for (const job of jobs) {
    const jobId = mappings.get(job.jobKey)!;
    const activeRefs = refs(jobId);
    const personal = userJobs.has(jobId) || job.effectiveDecision !== null || activeRefs.length > 0;
    const manual = job.effectiveDecision === 'NOT_INTERESTED' || activeRefs.some(r => r.kind === 'DISMISSED');
    // No new timestamp/fingerprint precedence rules: if the effective choice is
    // missing despite user events, preserve the subject and fail closed on display.
    const unresolved = userJobs.has(jobId) && job.effectiveDecision === null;
    const allowed = open(job) && !manual && !unresolved;
    const queued = allowed && job.needsAnalysis === true;
    const useful = allowed && (job.reportable === true || positive(job) || queued || activeRefs.some(r => r.kind !== 'DISMISSED'));
    const automatic = job.hardExclusionReason !== null || ((job.analysisMethod ?? '').startsWith('chatgpt_semantic') && job.reportable === false);
    if (useful) catalog.push({ jobId, kind: job.reportable === true || positive(job) || activeRefs.some(r => r.kind !== 'DISMISSED') ? 'OPPORTUNITY' : 'AI_QUEUE' });
    if (queued) aiQueue.push({ jobId, batch: job.batch, fingerprint: job.fingerprint, applyUrl: job.applyUrl, canonicalUrl: job.canonicalUrl, workerEligible: job.workerEligible, technicalStatus: job.technicalStatus });
    if (useful || personal) subjects.set(jobId, { jobId, catalog: useful, personal, aiQueue: queued, lifecycle: job.lifecycle, exclusion: manual ? 'MANUAL' : unresolved ? 'UNRESOLVED_PERSONAL' : automatic ? 'AUTOMATIC' : null });
  }
  for (const ref of context.personalReferences) if (!subjects.has(ref.jobId)) {
    subjects.set(ref.jobId, { jobId: ref.jobId, catalog: false, personal: true, aiQueue: false, lifecycle: null, exclusion: refs(ref.jobId).some(r => r.kind === 'DISMISSED') ? 'MANUAL' : null });
  }
  const ledger: IdentityLedger = {
    identities: [...identities.values()].sort(by(r => r.jobId)),
    mappings: [...mappings].map(([key, jobId]) => ({ key, jobId })).sort(by(r => r.key)),
  };
  return {
    contract: selectionContract,
    personalEventPolicy: 'APPEND_ONLY_NO_DELETE_BY_ABSENCE' as const,
    selectionContextDigest: await selectionContextDigest(context),
    ledger, ledgerDigest: await sha256(canonical(ledger)),
    subjects: [...subjects.values()].sort(by(r => r.jobId)),
    catalog: catalog.sort(by(r => r.jobId)), aiQueue: aiQueue.sort(by(r => r.jobId)),
    decisions: [...user.values()].sort(by(r => r.eventId)),
    reviews: [...semantic.values()].filter(e => subjects.has(e.jobId)).sort(by(r => r.eventId)),
    // Commits, provenance and personal events do not manufacture a content revision.
    catalogContentDigest: await sha256(canonical({
      ledger, catalog: catalog.sort(by(r => r.jobId)),
      jobs: jobs.filter(j => catalog.some(c => c.jobId === mappings.get(j.jobKey))).map(({ sourcePath: _p, sourceSha256: _h, ...r }) => r).sort(by(r => r.jobKey)),
      context: rows.filter(r => r.kind === 'company' || r.kind === 'source').map(r => Object.fromEntries(Object.entries(r).filter(([k]) => !['sourcePath','sourceSha256','coveragePath','coverageSha256'].includes(k)))).sort(by(r => String(r.id))),
    })),
  };
}
