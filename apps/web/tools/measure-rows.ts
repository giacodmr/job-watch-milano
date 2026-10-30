import type { SnapshotBundle, SnapshotRow } from '../shared/snapshot';

function key(row: SnapshotRow): string {
  if (row.kind === 'job') return row.jobKey;
  if (row.kind === 'semantic' || row.kind === 'user') return row.jobKey+'\0'+row.resultSha256;
  return 'id' in row ? row.id : 'pipeline';
}

// Count observations as a multiset: equivalent events may be present in several
// source memories. A Map<eventId,row> would falsely report those duplicates as new.
export function compareRows(
  before: Pick<SnapshotBundle,'chunks'>,
  after: Pick<SnapshotBundle,'chunks'>,
  canonical: (value: unknown) => string,
) {
  const counts: Record<string,Record<string,number>> = {};
  const classifications = new Map<string,string>();
  const payload = (row: SnapshotRow) => Object.fromEntries(Object.entries(row).filter(([name]) =>
    !['sourcePath','sourceSha256','coveragePath','coverageSha256'].includes(name)));
  for (const kind of ['company','source','job','semantic','user','pipeline']) {
    const older = new Map<string,SnapshotRow[]>();
    const oldRows = before.chunks.flat().filter(row => row.kind === kind);
    for (const row of oldRows) older.set(key(row),[...(older.get(key(row)) ?? []),row]);
    const newer = after.chunks.flat().filter(row => row.kind === kind);
    const group = { before:oldRows.length, after:newer.length, added:0, removed:0,
      exactUnchanged:0, provenanceOnlyChanged:0, payloadChanged:0 };
    for (const row of newer) {
      const id = key(row), candidates = older.get(id) ?? [];
      const exact = candidates.findIndex(old => canonical(old) === canonical(row));
      const samePayload = exact >= 0 ? exact : candidates.findIndex(old => canonical(payload(old)) === canonical(payload(row)));
      let state = 'changed';
      if (!candidates.length) group.added++;
      else {
        const [old] = candidates.splice(samePayload < 0 ? 0 : samePayload,1);
        if (exact >= 0) { group.exactUnchanged++;state='exact'; }
        else if (old && canonical(payload(old)) === canonical(payload(row))) { group.provenanceOnlyChanged++;state='provenance-only'; }
        else group.payloadChanged++;
      }
      classifications.set(kind+'\0'+id,state);
    }
    group.removed = Array.from(older.values()).reduce((sum,rows) => sum+rows.length,0);
    counts[kind] = group;
  }
  return {counts,classifications};
}
