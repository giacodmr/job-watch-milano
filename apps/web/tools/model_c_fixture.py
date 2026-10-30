"""Generate synthetic projection cases through the unchanged Python exporter.
No production JSON is opened: every input is built in a temporary fixture root.
"""
import json
from test_exporter import ExporterTests, STAMP

outputs = []
for scenario in ('pending_partial', 'manual_alias_reopened', 'automatic', 'unknown_personal', 'closed_personal', 'blocked_ai'):
    fixture = ExporterTests()
    fixture.setUp()
    try:
        if scenario == 'manual_alias_reopened':
            fixture.put('job_memory_jw2.json', {'batch':'JW2','records':{'Amazon::old-uuid':{
                'identity':{**fixture.job,'source_id':'old-uuid','fingerprint':'a'*16},
                'user':{'decision':'NOT_INTERESTED','fingerprint':'a'*16,'decided_at':STAMP}}}})
        if scenario == 'automatic':
            fixture.job['title'] = 'Sales Representative'
            fixture.put('current_jobs_jw2.json', {'generated_at':STAMP,'companies':[{'company':'Amazon','coverage':'PARTIAL','jobs':[fixture.job]}]})
            fixture.coherent()
        if scenario in ('unknown_personal', 'closed_personal'):
            fixture.put('current_jobs_jw2.json', {'generated_at':STAMP,'companies':[{'company':'Amazon','coverage':'PARTIAL','jobs':[]}]})
            fixture.put('job_memory_jw2.json', {'batch':'JW2','records':{'Amazon::123456':{'identity':fixture.job,'user':{'decision':'INTERESTED','decided_at':STAMP}}}})
            if scenario == 'closed_personal':
                (fixture.root/'archive').mkdir()
                (fixture.root/'archive/vacancies_2026_10.jsonl').write_text(json.dumps({**fixture.job,'job_key':'Amazon::123456'})+'\n')
            fixture.coherent()
        if scenario == 'blocked_ai':
            state={'evidence':{'fingerprint':'b'*16,'source_url':fixture.job['canonical_url']},'attempts':4,
                   'last_failure_at':STAMP,'retry_from':None,'status':'JD_UNAVAILABLE'}
            fixture.put('job_memory_jw2.json', {'batch':'JW2','records':{'Amazon::123456':{'identity':fixture.job,'jd_fetch':state}}})
        outputs.append({'scenario':scenario,'extracted':fixture.extract()})
    finally:
        fixture.doCleanups()
print(json.dumps(outputs))
