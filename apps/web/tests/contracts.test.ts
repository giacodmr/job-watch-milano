import { describe, expect, it } from 'vitest';
import { commandSchema, manifestSchema } from '../shared/contracts';

const base = {
  version: 1,
  commandId: '00000000-0000-4000-8000-000000000001',
  idempotencyKey: 'synthetic-command-001',
  expectedCommitSha: 'a'.repeat(40),
  expectedManifestSha256: 'b'.repeat(64),
  batch: 'jw1',
  jobKey: 'Synthetic Company::1',
  expectedFingerprint: '1234567890abcdef',
};
describe('future command input contract, no dispatch', () => {
  it('accepts supported shapes and opaque fingerprint lengths', () => {
    expect(
      commandSchema.safeParse({
        ...base,
        type: 'user_decision',
        decision: 'INTERESTED',
      }).success,
    ).toBe(true);
    expect(
      commandSchema.safeParse({
        ...base,
        type: 'request_semantic_review',
        expectedFingerprint: 'c'.repeat(64),
      }).success,
    ).toBe(true);
  });
  it('rejects unknown fields, complete JD fields and untrusted status claims', () => {
    for (const extra of [
      { jd: 'synthetic text' },
      { status: 'CONFIRMED' },
      { actor: 'impersonated' },
      { patch: { text: 'synthetic' } },
    ]) {
      expect(
        commandSchema.safeParse({
          ...base,
          type: 'user_decision',
          decision: 'INTERESTED',
          ...extra,
        }).success,
      ).toBe(false);
    }
  });
  it('requires explicit rejection category and a concrete bounded reason', () => {
    for (const reason of [
      undefined,
      'scarta',
      'non mi interessa',
      'x'.repeat(361),
    ]) {
      expect(
        commandSchema.safeParse({
          ...base,
          type: 'user_decision',
          decision: 'NOT_INTERESTED',
          rejectionReason: 'WRONG_FUNCTION',
          reason,
        }).success,
      ).toBe(false);
    }
    expect(
      commandSchema.safeParse({
        ...base,
        type: 'user_decision',
        decision: 'NOT_INTERESTED',
        rejectionReason: 'WRONG_FUNCTION',
        reason: 'La funzione richiesta è fuori dal mio obiettivo.',
      }).success,
    ).toBe(true);
    expect(
      commandSchema.safeParse({
        ...base,
        type: 'user_decision',
        decision: 'NOT_INTERESTED',
        reason: 'La funzione richiesta è fuori dal mio obiettivo.',
      }).success,
    ).toBe(false);
  });
  it('rejects unsupported batches, action types and missing concurrency evidence', () => {
    const input = { ...base, type: 'request_semantic_review' };
    for (const override of [
      { batch: 'jw5' },
      { type: 'edit_company' },
      { expectedCommitSha: '' },
      { expectedFingerprint: '' },
    ]) {
      expect(commandSchema.safeParse({ ...input, ...override }).success).toBe(
        false,
      );
    }
  });
});
describe('manifest boundary', () => {
  const manifest = {
    version: 1,
    repository: 'giacodmr/job-watch-milano',
    commitSha: 'a'.repeat(40),
    observedAt: '2026-10-29T10:00:00Z',
    files: [
      { path: 'current_jobs_jw1.json', sha256: 'b'.repeat(64), bytes: 100 },
    ],
    chunks: [{ index: 0, sha256: 'c'.repeat(64), rows: 1 }],
  };
  it('accepts pinned metadata manifests', () => {
    expect(manifestSchema.safeParse(manifest).success).toBe(true);
  });
  it('rejects artifacts, path traversal, duplicate files and sparse chunks', () => {
    for (const path of [
      '../secrets.json',
      '/job_memory_jw1.json',
      '.job_watch_bridge/requests/test.json',
      'job-watch-packet.json',
    ]) {
      expect(
        manifestSchema.safeParse({
          ...manifest,
          files: [{ ...manifest.files[0], path }],
        }).success,
      ).toBe(false);
    }
    expect(
      manifestSchema.safeParse({
        ...manifest,
        files: [...manifest.files, ...manifest.files],
      }).success,
    ).toBe(false);
    expect(
      manifestSchema.safeParse({
        ...manifest,
        chunks: [{ index: 1, sha256: 'c'.repeat(64), rows: 1 }],
      }).success,
    ).toBe(false);
  });
});
