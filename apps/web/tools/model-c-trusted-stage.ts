// M47 offline trusted projection cross-check. Does not authorize remote execution.
// Must be invoked ONLY after the caller has run verifyGitProjection against an
// approved repository and selected the complete verified bundle with selectModelC.
import {z} from 'zod';
import {canonical,sha256} from '../shared/canonical';
import {ingestRecord} from '../shared/model-c-ingestion';
import type {SnapshotBundle} from '../shared/snapshot';
import type {selectModelC} from '../shared/model-c-selection';
import {projectionProofSchema} from '../shared/projection-proof';
import type {prepareSafeRemoteBootstrapPlan} from './model-c-remote-plan';
import {auditReceivedIngestStage,StageAuditError} from './model-c-stage-attestation';

type Selected=Awaited<ReturnType<typeof selectModelC>>;
type Plan=Awaited<ReturnType<typeof prepareSafeRemoteBootstrapPlan>>;
const rejected=(code:string):never=>{throw new StageAuditError(code);};

/** The M46 v1 wire format is a deliberately reduced inventory. Its trusted
 * projection can be compared to a FULL independently replayed Git snapshot,
 * but v1 staging alone must never be promoted as a full catalog.
 * This is fail-closed when any selected job cannot be represented in v1.
 */
/** Pure checked reduction of a FULL trusted snapshot to the v1 wire inventory.
 * No data in this reduced view is ever used directly as catalog SQL payload.
 */
export function projectTrustedInventoryV1(bundle:SnapshotBundle,selected:Selected){
  const all=bundle.chunks.flat();
  const aliases=new Map(selected.ledger.mappings.map(r=>[r.key,r.jobId]));
  const chosen=new Map(selected.catalog.map(r=>[r.jobId,r]));
  const records:unknown[]=[];
  for(const row of all){
    if(row.kind==='company'){
      records.push({kind:'company',id:row.id,name:row.name,careerUrl:row.careerUrl});
    }else if(row.kind==='source'){
      records.push({kind:'source',id:row.id,companyId:row.companyId,
        atsFamily:row.family,inventoryUrl:row.inventoryUrl});
    }else if(row.kind==='job'){
      const id=aliases.get(row.jobKey);
      if(!id||!chosen.has(id))continue;
      records.push({kind:'job',id,companyId:row.companyId,
        sourceId:row.sourceId,title:row.title,location:row.location,
        lifecycle:row.lifecycle,officialUrl:row.canonicalUrl??row.applyUrl,
        fingerprint:row.fingerprint});
    }
  }
  // M46 v1 does not support closed, nullable-titled, or non-SHA fingerprint
  // vacancies. No lossy coercion is allowed to make an invalid packet fit.
  const valid=z.array(ingestRecord).safeParse(records);
  if(!valid.success)return rejected('UNREPRESENTABLE_PROJECTION_V1');
  if(valid.data.length!==records.length ||
     valid.data.filter(r=>r.kind==='job').length!==chosen.size)
    return rejected('TRUSTED_INVENTORY_INCOMPLETE');
  const ids=new Set<string>();
  for(const item of valid.data){
    const k=item.kind+':'+item.id;
    if(ids.has(k))return rejected('TRUSTED_INVENTORY_DUPLICATE');
    ids.add(k);
  }
  return valid.data;
}

export async function verifyTrustedStagingAgainstSnapshot(
  catalog:D1Database,runId:string,bundle:SnapshotBundle,selected:Selected,
  verifiedProof:unknown,trustedPlan:Plan,
){
  const receipt=await auditReceivedIngestStage(catalog,runId);
  const proof=projectionProofSchema.parse(verifiedProof);
  if(proof.observedGitCommit!==bundle.manifest.commitSha ||
     proof.sourceManifestDigest!==await sha256(canonical(bundle.manifest)))
    return rejected('TRUSTED_SOURCE_PROOF_MISMATCH');
  if(receipt.claimedCommitSha!==proof.observedGitCommit||
     receipt.claimedManifestDigest!==proof.sourceManifestDigest||
     receipt.claimedProjectionDigest!==proof.projectionInputDigest)
    return rejected('SOURCE_RECEIPT_MISMATCH');
  const {digest:planDigest,...planBody}=trustedPlan;
  if(trustedPlan.target!=='OFFLINE_REVIEW_ONLY'||
     trustedPlan.remoteExecutionAuthorized!==false||
     trustedPlan.syncRevision!==receipt.expectedRevision+1||
     trustedPlan.origin.observedCommit!==proof.observedGitCommit||
     trustedPlan.origin.manifestDigest!==proof.sourceManifestDigest||
     trustedPlan.origin.projectionDigest!==proof.projectionInputDigest||
     planDigest!==await sha256(canonical(planBody))||
     planDigest!==receipt.claimedPlanDigest)
    return rejected('TRUSTED_PLAN_MISMATCH');
  const valid=projectTrustedInventoryV1(bundle,selected);
  const expected=await sha256(canonical([...valid].sort((a,b)=>
    (a.kind+':'+a.id).localeCompare(b.kind+':'+b.id))));
  if(receipt.recordCount!==valid.length||receipt.inventoryDigest!==expected)
    return rejected('STAGED_PROJECTION_MISMATCH');
  // A successful attestation only proves the lossy packet agrees with an
  // independently verified FULL projection. It does not unlock a Worker route.
  return {status:'TRUSTED_STAGE_MATCH' as const,runId,
    expectedRevision:receipt.expectedRevision,
    packetDigest:receipt.packetDigest,inventoryDigest:expected,
    ledgerDigest:selected.ledgerDigest,
    contentDigest:selected.catalogContentDigest,
    sourceManifestDigest:proof.sourceManifestDigest,
    projectionInputDigest:proof.projectionInputDigest,
    fullGitProjectionCompared:true as const,remoteExecutionAuthorized:false as const};
}
