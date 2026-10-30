import { z } from 'zod';
import { canonical, sha256 } from './canonical';
import { selectionContract, selectionContextDigest } from './model-c-selection';
import type { SelectionContext } from './model-c-selection';
import type { SnapshotBundle } from './snapshot';

const hash = z.string().regex(/^[a-f0-9]{64}$/);
const commit = z.string().regex(/^[a-f0-9]{40}$/);
const file = z.strictObject({
  path: z.string().min(1).max(300).regex(/^[A-Za-z0-9_.\/-]+$/).refine(p => !p.startsWith('/') && !p.split('/').some(s => s === '..' || s === '.' || s === '')),
  sha256: hash, bytes: z.number().int().nonnegative(),
});
const files = z.array(file).min(1).superRefine((v, ctx) => {
  if (v.some((f, i) => i > 0 && f.path <= v[i - 1]!.path)) ctx.addIssue({ code: 'custom', message: 'SORTED_UNIQUE_PATHS_REQUIRED' });
});
export const requiredImplementationPaths = [
  'shared/canonical.ts', 'shared/contracts.ts', 'shared/model-c-selection.ts',
  'shared/projection-proof.ts', 'shared/snapshot.ts', 'tools/check-model-c.mjs',
  'tools/export_snapshot.py', 'tools/local-sync.mjs',
] as const;
export const requiredPythonPaths = ['daily_worklist.py','harden_job_watch_state.py','jd_retry.py','job_memory.py','location_policy.py','pipeline_state.py','sync_analysis_state.py'] as const;
export const projectionInputsSchema = z.strictObject({
  contract: z.literal(selectionContract),
  selectionContextDigest: hash,
  // Conservative closure: ALL tracked .py/.json/.jsonl, not only direct imports.
  sourceFiles: files,
  // Actual bytes of every shared/ and tools/ TS, MJS and Python implementation.
  implementationFiles: files,
  runtime: z.strictObject({ node: z.string().min(1).max(100), python: z.string().min(1).max(100) }),
}).superRefine((value, ctx) => {
  if (requiredPythonPaths.some(p => !value.sourceFiles.some(f => f.path === p)) ||
      requiredImplementationPaths.some(p => !value.implementationFiles.some(f => f.path === p))) {
    ctx.addIssue({ code: 'custom', message: 'INCOMPLETE_CODE_PROOF' });
  }
});
export type ProjectionInputs = z.infer<typeof projectionInputsSchema>;

/** A hash binds these claims; the Git adapter must verify completeness and bytes. */
export async function projectionInputDigest(input: unknown) {
  return sha256(canonical(projectionInputsSchema.parse(input)));
}
export const projectionProofSchema = z.strictObject({
  contract: z.literal(selectionContract), observedGitCommit: commit,
  sourceManifestDigest: hash, projectionInputDigest: hash, inputs: projectionInputsSchema,
});
export async function createProjectionProof(bundle: SnapshotBundle, input: unknown, context: SelectionContext) {
  const inputs = projectionInputsSchema.parse(input);
  if (inputs.selectionContextDigest !== await selectionContextDigest(context)) throw new Error('SELECTION_CONTEXT_MISMATCH');
  // Missing archives/receipts are errors, not an excuse for a fast path.
  if (bundle.manifest.files.some(f => !inputs.sourceFiles.some(s => canonical(s) === canonical(f)))) {
    throw new Error('UNBOUND_DATA_PROOF');
  }
  return projectionProofSchema.parse({
    contract: selectionContract, observedGitCommit: bundle.manifest.commitSha,
    sourceManifestDigest: await sha256(canonical(bundle.manifest)),
    projectionInputDigest: await projectionInputDigest(inputs), inputs,
  });
}
export async function verifyProjectionProof(bundle: SnapshotBundle, input: unknown, context: SelectionContext) {
  const proof = projectionProofSchema.parse(input);
  const expected = await createProjectionProof(bundle, proof.inputs, context);
  if (canonical(proof) !== canonical(expected)) throw new Error('PROJECTION_PROOF_MISMATCH');
  return proof;
}
export const catalogObservationSchema = z.strictObject({
  contract: z.literal(selectionContract),
  observedGitCommit: commit,
  contentOrigin: z.strictObject({ commitSha: commit, sourceManifestDigest: hash }),
  catalogContentDigest: hash, projectionInputDigest: hash,
  catalogRevision: z.number().int().positive(),
});
export type CatalogObservation = z.infer<typeof catalogObservationSchema>;

/** Contract only: no checkpoint writes and no claim that Git ancestry was checked. */
export function catalogObservation(proofInput: z.input<typeof projectionProofSchema>, contentDigest: string, previous?: CatalogObservation) {
  const proof = projectionProofSchema.parse(proofInput);
  const old = previous && catalogObservationSchema.parse(previous);
  const sameContent = old?.catalogContentDigest === contentDigest;
  return catalogObservationSchema.parse({
    contract: selectionContract, observedGitCommit: proof.observedGitCommit,
    contentOrigin: sameContent ? old.contentOrigin : { commitSha: proof.observedGitCommit, sourceManifestDigest: proof.sourceManifestDigest },
    catalogContentDigest: contentDigest, projectionInputDigest: proof.projectionInputDigest,
    catalogRevision: old ? old.catalogRevision + (sameContent ? 0 : 1) : 1,
  });
}
// Equality is only a prerequisite. No remote ingestion/no-op path is activated.
export const canReuseProjection = (previous: CatalogObservation, verifiedNextInputsDigest: string) =>
  catalogObservationSchema.parse(previous).projectionInputDigest === hash.parse(verifiedNextInputsDigest);
