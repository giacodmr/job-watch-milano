// Independent Git-authorized publication checks for persisted v2 service ingress.
// An existing publication is replayed through the original, immutable D1 run.
import {canonical,sha256} from '../shared/canonical';
import {prepareCatalogV2Packets} from '../shared/model-c-ingestion-v2';
import type {SnapshotBundle} from '../shared/snapshot';
import type {selectModelC} from '../shared/model-c-selection';
import {projectionProofSchema} from '../shared/projection-proof';
import type {prepareSafeRemoteBootstrapPlan} from './model-c-remote-plan';
import {verifyPersistedV2AgainstTrusted} from './model-c-v2-stage-attestation';
type Selected=Awaited<ReturnType<typeof selectModelC>>;
type Plan=Awaited<ReturnType<typeof prepareSafeRemoteBootstrapPlan>>;
const deny=(s:string):never=>{throw Error(s);};
const verifiedPlan=async(plan:Plan,proof:ReturnType<typeof projectionProofSchema.parse>,
  expected:number,checkContextProjection=true)=>{
 const {digest,...body}=plan;
 if(plan.target!=='OFFLINE_REVIEW_ONLY'||plan.remoteExecutionAuthorized!==false||
   plan.syncRevision!==expected+1||
   plan.origin.observedCommit!==proof.observedGitCommit||
   plan.origin.manifestDigest!==proof.sourceManifestDigest||
   (checkContextProjection&&plan.origin.projectionDigest!==proof.projectionInputDigest)||
   digest!==await sha256(canonical(body)))deny('V2_TRUSTED_PLAN_MISMATCH');
};
export async function verifyTrustedV2Stage(db:D1Database,runId:string,
 bundle:SnapshotBundle,selected:Selected,proofInput:unknown,plan:Plan){
 const proof=projectionProofSchema.parse(proofInput);
 if(proof.observedGitCommit!==bundle.manifest.commitSha||
   proof.sourceManifestDigest!==await sha256(canonical(bundle.manifest)))
   return deny('V2_PROVENANCE_MISMATCH');
 const head=Number(await db.prepare("SELECT sync_revision FROM catalog_head WHERE scope='catalog'")
   .first('sync_revision')??0);
 await verifiedPlan(plan,proof,head);
 const expected=await prepareCatalogV2Packets(bundle,selected,proof,plan.digest,head);
 if(expected.run.runId!==runId)return deny('V2_TRUSTED_RUN_MISMATCH');
 return verifyPersistedV2AgainstTrusted(db,runId,expected);
}
export async function verifyPublishedV2StageReplay(db:D1Database,runId:string,
 proofInput:unknown,plan:Plan){
 const proof=projectionProofSchema.parse(proofInput);
 const row=await db.prepare(`SELECT i.commit_sha AS commitSha,
 i.manifest_digest AS manifestDigest,i.projection_digest AS projectionDigest,
 i.plan_digest AS planDigest,i.expected_revision AS expectedRevision,
 i.ledger_digest AS ledgerDigest,i.catalog_content_digest AS contentDigest,
 r.observed_commit AS publishedCommit,r.projection_digest AS publishedProjection,
 r.expected_revision AS publishedExpected,r.state AS publishedState,
 p.manifest_digest AS publishedManifest,h.sync_revision AS publishedRevision
 FROM catalog_ingest_v2_runs i JOIN catalog_runs r ON r.id=i.id
 JOIN catalog_run_proofs p ON p.run_id=r.id
 JOIN catalog_head h ON h.run_id=r.id AND h.scope='catalog'
 WHERE i.id=?`).bind(runId).first<{
 commitSha:string;manifestDigest:string;projectionDigest:string;planDigest:string;
 expectedRevision:number;ledgerDigest:string;contentDigest:string;
 publishedCommit:string;publishedProjection:string;publishedExpected:number;
 publishedState:string;publishedManifest:string;publishedRevision:number}>();
 if(!row)return deny('V2_PUBLISHED_RUN_NOT_CURRENT');
 // During recovery PERSONAL append can change the selection-context digest.
 // Pin replay to the original immutable staged/published plan, not a
 // newly computed projection input digest from the post-append context.
 await verifiedPlan(plan,proof,row.expectedRevision,false);
 if(row.publishedState!=='PUBLISHED'||row.publishedRevision!==row.expectedRevision+1||
   row.publishedExpected!==row.expectedRevision||
   row.commitSha!==row.publishedCommit||row.commitSha!==proof.observedGitCommit||
   row.projectionDigest!==row.publishedProjection||
   row.projectionDigest!==plan.origin.projectionDigest||
   row.manifestDigest!==row.publishedManifest||
   row.manifestDigest!==proof.sourceManifestDigest||row.planDigest!==plan.digest)
   return deny('V2_PUBLISHED_STAGE_REPLAY_CONFLICT');
 return {status:'V2_PUBLISHED_REPLAY_CONFIRMED' as const,runId};
}
