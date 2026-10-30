"""Synthetic Git sources only; never opens any operational JSON."""
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from test_exporter import ExporterTests, STAMP

root=Path(sys.argv[1])
if sys.argv[2]=='seed':
    fixture=ExporterTests()
    fixture.setUp()
    try:
        jobs=[{**fixture.job,'source_id':str(123456+i),'canonical_url':f'https://www.amazon.jobs/en/jobs/{123456+i}/role'} for i in range(int(sys.argv[3]))]
        if len(sys.argv)>4 and sys.argv[4]=='baseline':
            records={f"Amazon::{j['source_id']}":{'identity':j} for j in jobs[151:]}
            for i,j in enumerate(jobs[:20]):
                records[f'Amazon::synthetic-alias-{i}']={'identity':{**j,'source_id':f'synthetic-alias-{i}'}}
            fixture.put('job_memory_jw2.json',{'batch':'JW2','records':records})
            jobs=jobs[:151]
        fixture.put('current_jobs_jw2.json',{'generated_at':STAMP,'companies':[{'company':'Amazon','coverage':'PARTIAL','jobs':jobs}]})
        fixture.coherent()
        shutil.copytree(fixture.root,root,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    finally:
        fixture.doCleanups()
else:
    sys.path.insert(0,str(root))
    import pipeline_state
    token=pipeline_state.snapshot(root)
    (root/'job_watch_run_state.json').write_text(json.dumps({'version':'2.0',**token}))
    (root/'job_watch_healthcheck.json').write_text(json.dumps({'snapshot':token,'run_id':token['run_id'],'generated_at':STAMP,'status':'NEEDS_REVIEW','collection_status':'COMPLETE_WITH_WARNINGS','DAILY_COMPLETE':False,'FULL_SEMANTIC_COMPLETE':False}))
