#!/usr/bin/env python3
"""Independent bounded worker packets and transactional, per-batch review commits."""
import argparse
import hashlib
import json
from pathlib import Path
from pipeline_state import BATCHES, load, writer_lock, transaction
from job_memory import load_memory, validate_memory, pack_memory, IDENTITY_FIELDS
from harden_job_watch_state import semantic_decision_valid

ROOT = Path(__file__).resolve().parent

def batch_snapshot(batch, root=ROOT):
    names = [f'current_jobs_{batch}.json',f'job_memory_{batch}.json','job_watch_rules.json','companies_job_watch_v2.json','job_watch_batches.json']
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}

def apply_packet(batch, patch, root=ROOT, bridge_receipt=None):
    from sync_analysis_state import project_batch
    with writer_lock(root):
        memory = load_memory(batch,root)
        patch_id = hashlib.sha256(json.dumps(patch,sort_keys=True).encode()).hexdigest()
        if patch_id in memory.get('applied_update_ids',[]): return 0
        if patch.get('batch','').lower()!=batch or patch.get('snapshot')!=batch_snapshot(batch,root):
            raise ValueError('Stale or wrong-batch worker packet; reload selected jobs')
        projection = project_batch(batch,root)['records']
        updates = patch.get('semantic_decisions', {})
        if not isinstance(updates,dict) or not 1 <= len(updates) <= 30: raise ValueError('Worker commits require 1–30 decisions')
        for key, decision in updates.items():
            rec = projection.get(key, {})
            if not rec.get('current_open') or rec.get('user_decision') in {'APPLIED','NOT_INTERESTED'}:
                raise ValueError(f'Vacancy no longer eligible: {key}')
            valid, reason = semantic_decision_valid(decision,rec)
            if not valid: raise ValueError(f'{key}: {reason}')
            record = memory['records'].setdefault(key,{})
            record['identity']={f:rec[f] for f in IDENTITY_FIELDS if rec.get(f) is not None}
            record['semantic']=decision
        memory.setdefault('applied_update_ids',[]).append(patch_id)
        groups=load('job_watch_batches.json',root=root)['batches']
        owners={c:b.lower() for b,g in groups.items() for c in g['companies']}
        validate_memory(memory,batch,owners)
        writes = {f'job_memory_{batch}.json':pack_memory(memory)}
        if bridge_receipt is not None:
            name, receipt = bridge_receipt
            path = Path(name)
            if path.parent != Path('.job_watch_bridge/receipts') or path.suffix != '.json':
                raise ValueError('Invalid bridge receipt path')
            (root / path.parent).mkdir(parents=True, exist_ok=True)
            writes[name] = receipt
        transaction(writes,root=root)
        return len(updates)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('select','apply'))
    parser.add_argument('batch',choices=BATCHES)
    parser.add_argument('--limit',type=int,default=20)
    parser.add_argument('--fetch',action='store_true')
    parser.add_argument('--patch',type=Path)
    parser.add_argument('--exclude-key',action='append',default=[])
    args=parser.parse_args()
    if args.action=='apply':
        if not args.patch: parser.error('--patch required')
        print('Committed decisions:',apply_packet(args.batch,json.loads(args.patch.read_text())))
    else:
        if not 1<=args.limit<=30: parser.error('--limit must be 1–30')
        from enrich_semantic_jds import fetch_candidates
        token=batch_snapshot(args.batch)
        records=fetch_candidates(args.batch,args.limit,fetch=args.fetch,exclude_keys=args.exclude_key)
        if token!=batch_snapshot(args.batch): raise SystemExit('Sources changed while fetching; reload')
        print(json.dumps({'batch':args.batch,'snapshot':token,'records':records},ensure_ascii=False))

if __name__=='__main__': main()
