"""Permanent invariants for daily-first state, migration and early geography."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import daily_worklist as daily
import sync_analysis_state as sync
import pipeline_state as ps
import collector
import enrich_semantic_jds as enrich
import semantic_worker as worker
from job_memory import load_memory, validate_memory, record_surface, material_signature
from location_policy import allowed
from state_migration import migrate, LEGACY
from test_daily_pipeline import full_decision
from test_pipeline_resilience import Fixture

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.f=Fixture(self.root)
        self.context=self.f.modules();self.context.__enter__()
        self.add_job()
    def tearDown(self): self.context.__exit__(None,None,None);self.tmp.cleanup()
    def add_job(self,b='jw3',sid='1',**extra):
        cur=self.f.get(f'current_jobs_{b}.json')
        row={'company':b.upper(),'source_id':sid,'title':'Business Analyst','location':'Milan','fingerprint':'abc','status':'NEW','canonical_url':f'https://official.example/{b}/{sid}','first_seen_at':'2026-10-03T06:30:00Z',**extra}
        cur['companies'][0]['jobs'].append(row)
        cur['summary']['target_jobs_open']=sum(j.get('status') in sync.OPEN_STATUSES for c in cur['companies'] for j in c['jobs'])
        self.f.put(f'current_jobs_{b}.json',cur)
        return row
    def memory(self,b='jw3',**sections):
        mem=self.f.get(f'job_memory_{b}.json')
        mem['records'].setdefault(f'{b.upper()}::1',{}).update(sections)
        self.f.put(f'job_memory_{b}.json',mem)
        return mem
    def rec(self): return sync.project_batch('jw3',self.root)['records']['JW3::1']
    def test_projection_and_queue_need_only_current_and_memory(self):
        self.assertTrue(self.rec()['needs_analysis'])
        self.assertEqual(sync.project_batch('jw3',self.root)['queue'][0]['job_key'],'JW3::1')
        self.assertFalse(any((self.root/n).exists() for n in LEGACY))
    def test_current_first_seen_not_projection_timestamp(self):
        self.assertEqual(self.rec()['first_seen_at'],'2026-10-03T06:30:00Z')
        sync.sync_batch('jw3');self.assertEqual(self.rec()['first_seen_at'],'2026-10-03T06:30:00Z')
    def test_memory_rejects_full_jd(self):
        mem=self.memory(semantic={**full_decision(),'description':'full JD'})
        with self.assertRaisesRegex(AssertionError,'Full JD'): validate_memory(mem,'jw3')
    def test_surfacing_roundtrip_and_idempotent_same_event(self):
        rec=self.rec();record={};event={'fingerprint':'abc','surfaced_at':'2026-10-03T08:00:00Z','surfaced_status':'NEW'}
        record_surface(record,event,rec);record_surface(record,event,rec)
        self.assertEqual(record['surfacing']['surface_count'],1)
        record_surface(record,{**event,'surfaced_at':'2026-10-04T08:00:00Z'},rec)
        self.memory(semantic=full_decision(),**record)
        reread=self.rec()['surfacing']
        self.assertEqual(reread['surface_count'],2);self.assertEqual(reread['first_surfaced_at'],event['surfaced_at'])
        self.assertEqual(reread['last_surfaced_fingerprint'],'abc')
    def test_older_surface_event_cannot_reset_reminder_history(self):
        record={};rec=self.rec()
        event={'fingerprint':'abc','surfaced_at':'2026-10-03T08:00:00Z','surfaced_status':'NEW'}
        record_surface(record,event,rec)
        with self.assertRaises(ValueError):record_surface(record,{**event,'surfaced_at':'2026-10-02T08:00:00Z'},rec)
        self.assertEqual(record['surfacing']['surface_count'],1)
    def test_delayed_daily_patch_does_not_overwrite_newer_user_or_review(self):
        import job_watch
        self.memory(semantic={**full_decision(),'analyzed_at':'2026-10-05T08:00:00Z'}, user={'decision':'INTERESTED','decided_at':'2026-10-05T08:00:00Z','fingerprint':'abc'})
        self.f.put('daily_updates.json',{'version':'1.0','snapshot':daily.build_worklist()['snapshot'],
            'semantic_decisions':{'jw3':{'JW3::1':full_decision()}},
            'user_decisions':{'JW3::1':{'decision':'TO_REVIEW','decided_at':'2026-10-03T08:00:00Z','fingerprint':'abc'}}})
        job_watch.apply_updates()
        record=load_memory('jw3',self.root)['records']['JW3::1']
        self.assertEqual(record['user']['decision'],'INTERESTED')
        self.assertEqual(record['semantic']['analyzed_at'],'2026-10-05T08:00:00Z')
        rejected=self.f.get('rejected_daily_updates.json')
        self.assertIn('semantic_decisions',rejected);self.assertIn('user_decisions',rejected)

    def test_user_decision_roundtrip_all_states_and_rejection_reason(self):
        for state in ('INTERESTED','TO_REVIEW','APPLIED','NOT_INTERESTED'):
            choice={'decision':state,'decided_at':'2026-10-03T08:00:00Z','fingerprint':'abc','rejection_reason':'TOO_SENIOR','reason':'Troppo senior'}
            self.memory(user=choice)
            self.assertEqual(load_memory('jw3',self.root)['records']['JW3::1']['user'],choice)
            self.assertEqual(self.rec()['user_decision'],state)
    def test_not_interested_suppresses_changed_fingerprint_forever(self):
        self.memory(user={'decision':'NOT_INTERESTED','fingerprint':'old','decided_at':'2026-10-01','rejection_reason':'TOO_SENIOR'})
        self.assertFalse(self.rec()['needs_analysis']);self.assertIsNone(daily.action_reason(self.rec()))
        self.assertEqual(sync.project_batch('jw3',self.root)['queue'],[])
    def test_applied_never_reopens_ordinary_review(self):
        self.memory(user={'decision':'APPLIED','fingerprint':'old','decided_at':'2026-10-01'})
        self.assertFalse(self.rec()['needs_analysis']);self.assertIsNone(daily.action_reason(self.rec()))
    def test_model_and_rule_version_do_not_invalidate_valid_decisions(self):
        self.memory(semantic={**full_decision(),'model':'previous','rule_context':'old'})
        self.f.put('job_watch_rules.json',{'model':'new','version':'changed'})
        self.assertFalse(self.rec()['needs_analysis'])
    def surfaced(self,fit=90):
        record={};record_surface(record,{'fingerprint':'abc','surfaced_at':'2026-10-03T08:00:00Z','surfaced_status':'NEW'},self.rec())
        self.memory(semantic={**full_decision(),'fit_score':fit},**record)
    def test_reminders_anchored_to_first_surface_max_three_days(self):
        self.surfaced()
        self.assertIsNone(daily.action_reason(self.rec(),at='2026-10-03T10:00:00Z'))
        for date in ('2026-10-04','2026-10-05'):
            self.assertEqual(daily.action_reason(self.rec(),at=date+'T08:00:00Z'),'REMINDER')
        self.assertIsNone(daily.action_reason(self.rec(),at='2026-10-06T08:00:00Z'))
        self.assertIsNone(daily.action_reason(self.rec(),at='2026-11-04T08:00:00Z'))
    def test_lower_fit_no_reminder(self):
        self.surfaced(fit=75);self.assertIsNone(daily.action_reason(self.rec(),at='2026-10-04T08:00:00Z'))
    def test_technical_fingerprint_change_does_not_resurface(self):
        self.surfaced()
        cur=self.f.get('current_jobs_jw3.json');cur['companies'][0]['jobs'][0]['fingerprint']='technical';self.f.put('current_jobs_jw3.json',cur)
        self.memory(semantic=full_decision('technical'))
        self.assertIsNone(daily.action_reason(self.rec(),at='2026-11-04T08:00:00Z'))
        cur['companies'][0]['jobs'][0]['title']='Strategy Analyst';self.f.put('current_jobs_jw3.json',cur)
        self.assertEqual(daily.action_reason(self.rec(),at='2026-11-04T08:00:00Z'),'NEW_INTERESTING')
    def test_closed_vacancy_archived_once_and_active_choice_retained(self):
        self.memory(user={'decision':'INTERESTED','decided_at':'2026-10-01'})
        cur=self.f.get('current_jobs_jw3.json');cur['companies'][0]['jobs'][0]['status']='CLOSED';self.f.put('current_jobs_jw3.json',cur)
        sync.sync_batch('jw3');sync.sync_batch('jw3')
        self.assertEqual(self.f.get('current_jobs_jw3.json')['companies'][0]['jobs'],[])
        archive=list((self.root/'archive').glob('*.jsonl'));self.assertEqual(len(archive),1)
        self.assertEqual(len(archive[0].read_text().splitlines()),1)
        work=daily.build_worklist();self.assertEqual(work['records'][0]['action'],'INTERESTED')
    def test_archive_is_never_read_by_daily_workers_or_certification(self):
        (self.root/'archive').mkdir();(self.root/'archive'/'vacancies_2026_10.jsonl').write_text('invalid json')
        original=Path.read_text
        def guard(path,*a,**kw):
            if path.parent.name=='archive': raise AssertionError('Cold archive read')
            return original(path,*a,**kw)
        with patch.object(Path,'read_text',guard):
            daily.build_worklist();enrich.fetch_candidates('jw3',root=self.root)
            sync.sync_batch('jw3')
            import certify_job_watch
            certify_job_watch.certify(self.root)
    def test_worklist_idempotent_and_bounded_without_jd(self):
        for i in range(2,60): self.add_job(sid=str(i))
        first=daily.build_worklist();second=daily.build_worklist()
        self.assertEqual(first,second);self.assertLessEqual(first['summary']['daily_semantic_pending'],20)
        self.assertNotIn('"jd"',json.dumps(first));self.assertEqual(first['summary']['full_semantic_pending'],59)
    def test_completed_daily_selection_does_not_pull_more_backlog(self):
        for i in range(2,40): self.add_job(sid=str(i))
        work=daily.build_worklist()
        mem=self.f.get('job_memory_jw3.json')
        for row in work['records']:
            mem['records'][row['job_key']]={'semantic':{**full_decision(),'reportable':False}}
        self.f.put('job_memory_jw3.json',mem)
        self.assertEqual(daily.build_worklist()['summary']['daily_semantic_pending'],0)
        self.assertGreater(daily.build_worklist()['summary']['full_semantic_pending'],0)
    def test_batch_isolation_worker_commit_and_replay(self):
        for b in ps.BATCHES:
            if b!='jw3':self.add_job(b=b)
        for b in ps.BATCHES:
            before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
            packet={'batch':b,'snapshot':worker.batch_snapshot(b,self.root),'semantic_decisions':{f'{b.upper()}::1':full_decision()}}
            self.assertEqual(worker.apply_packet(b,packet,self.root),1)
            self.assertEqual(worker.apply_packet(b,packet,self.root),0)
            changed=[p.name for p in self.root.glob('*.json') if before[p.name]!=p.read_bytes()]
            self.assertEqual(changed,[f'job_memory_{b}.json'])
    def test_worker_snapshot_independent_of_other_batches(self):
        before=worker.batch_snapshot('jw3',self.root)
        self.add_job(b='jw1')
        self.assertEqual(before,worker.batch_snapshot('jw3',self.root))
    def test_worker_rejects_wrong_owner_stale_snapshot_and_full_jd(self):
        packet={'batch':'jw3','snapshot':worker.batch_snapshot('jw3',self.root),'semantic_decisions':{'JW1::1':full_decision()}}
        with self.assertRaises(ValueError):worker.apply_packet('jw3',packet,self.root)
        packet['semantic_decisions']={'JW3::1':{**full_decision(),'text':'full JD'}}
        with self.assertRaises(AssertionError):worker.apply_packet('jw3',packet,self.root)
        self.assertEqual(load_memory('jw3',self.root)['records'],{})
        packet['snapshot']={}
        with self.assertRaises(ValueError):worker.apply_packet('jw3',packet,self.root)
    def test_public_url_alias_preserves_rejection_across_id_changes(self):
        job=self.rec()
        self.memory(semantic=full_decision())
        memory=self.f.get('job_memory_jw3.json')
        memory['records']['JW3::old']={'identity':{**job,'canonical_url':job['canonical_url']+'?tracking=old'},
            'user':{'decision':'NOT_INTERESTED','decided_at':'2026-10-04','fingerprint':'old'}}
        self.f.put('job_memory_jw3.json',memory)
        self.assertFalse(self.rec()['needs_analysis'])
        self.assertEqual(self.rec()['user_decision'],'NOT_INTERESTED')
        self.assertEqual(daily.build_worklist()['records'],[])
        self.assertIn('JW3::old',load_memory('jw3',self.root)['records'])
    def test_worker_does_not_need_other_batch_files(self):
        for b in ('jw1','jw2','jw4'):
            (self.root/f'current_jobs_{b}.json').unlink()
            (self.root/f'job_memory_{b}.json').unlink()
        self.assertEqual(len(enrich.fetch_candidates('jw3',root=self.root)),1)
        packet={'batch':'jw3','snapshot':worker.batch_snapshot('jw3',self.root),'semantic_decisions':{'JW3::1':full_decision()}}
        self.assertEqual(worker.apply_packet('jw3',packet,self.root),1)
    def test_new_semantic_fields_do_not_persist_jd_from_amazon(self):
        from amazon_target_check import strip_full_jds
        item={'job_id':'1','title':'Analyst','description':'long description','basic_qualifications':'qualifications','preferred_qualifications':'preferred','fingerprint':'same','l68_status':'REQUIRED'}
        data=strip_full_jds({'target_jobs':[item]})
        self.assertNotIn('description',data['target_jobs'][0])
        self.assertEqual(data['target_jobs'][0]['fingerprint'],'same')
        self.assertEqual(data['target_jobs'][0]['l68_status'],'REQUIRED')
    def test_repeated_priority_overlay_filters_geography_without_state_churn(self):
        company=self.f.get('current_jobs_jw2.json');company['companies'].append({'company':'Amazon','jobs':[],'coverage':'VERIFIED'});self.f.put('current_jobs_jw2.json',company)
        source=self.f.get('amazon_target_check.json');source['target_jobs']=[{'job_id':'bad','title':'Business Analyst','location':'East London, South Africa','target_city':'London','status':'NEW','fingerprint':'bad','apply_url':'https://www.amazon.jobs/en/jobs/123456/bad'}];self.f.put('amazon_target_check.json',source)
        sync.sync_batch('jw2');before=(self.root/'current_jobs_jw2.json').read_bytes();sync.sync_batch('jw2')
        self.assertEqual(before,(self.root/'current_jobs_jw2.json').read_bytes())
        self.assertEqual(self.f.get('current_jobs_jw2.json')['companies'][-1]['jobs'],[])

    def test_reporting_thresholds_are_geography_configurable(self):
        self.f.put('job_watch_rules.json',{'reporting_thresholds_by_geography':{'Milan':70,'London':91,'Luxembourg':93}})
        self.assertEqual(sync.threshold_for('London, England',self.root),91)
        self.assertEqual(sync.threshold_for('Luxembourg City',self.root),93)
        self.assertEqual(sync.threshold_for('Milan',self.root),70)

    def test_priorities_new_and_likelihood_ordering(self):
        from harden_job_watch_state import queue_sort_key
        rows=[{'company':'X','title':'Other','current_status':'STILL_OPEN'}, {'company':'X','title':'Business Analyst','current_status':'NEW'}, {'company':'Amazon','priority_company':True,'title':'Other','current_status':'STILL_OPEN'}]
        self.assertEqual(sorted(rows,key=queue_sort_key),[rows[2],rows[1],rows[0]])
    def test_publication_retry_discards_untracked_archive_before_regeneration(self):
        import subprocess
        import job_watch
        def git(*args):
            return subprocess.run(['git',*args],cwd=self.root,capture_output=True,text=True,check=True)
        git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
        git('add','current_jobs_jw1.json');git('commit','-qm','fixture')
        git('update-ref','refs/remotes/origin/main','HEAD')
        path=self.root/'archive'/'vacancies_2026_11.jsonl';path.parent.mkdir();path.write_text('generated losing attempt\n')
        job_watch.reset_generated_checkout()
        self.assertFalse(path.exists())
        self.assertTrue((self.root/'current_jobs_jw1.json').exists())

    def test_append_journal_recovers_without_duplicate_archive_rows(self):
        path=self.root/'archive'/'vacancies_2026_10.jsonl';path.parent.mkdir();path.write_text('old\npartial')
        ps.atomic_json(self.root/'.job_watch.transaction.json',{'writes':{'done.json':{}},'appends':{'archive/vacancies_2026_10.jsonl':{'offset':4,'text':'new\n'}},'remove':[]})
        ps.recover_transaction(self.root);ps.recover_transaction(self.root)
        self.assertEqual(path.read_text(),'old\nnew\n')

class GeographyTests(unittest.TestCase):
    def test_exact_configured_foreign_allowlists(self):
        for company in ('Amazon','Mastercard','American Express','Campari','Prima Assicurazioni','Uber','Revolut','Satispay','EssilorLuxottica','Snam','Webuild'):
            for loc in ('London','London, England','London, UK','Greater London'):
                self.assertTrue(allowed(company,loc),(company,loc))
        for company in ('Ferrero','Amazon','Mastercard'):
            self.assertTrue(allowed(company,'Luxembourg City'))
        self.assertFalse(allowed('Ferrero','London'))
        self.assertFalse(allowed('Visa','London'));self.assertFalse(allowed('Visa','Luxembourg'))
    def test_italian_scope_and_foreign_homonyms(self):
        for loc in ('Milan','Milano, Italia','Rome','Roma, IT'):
            self.assertTrue(allowed('Unlisted Company',loc))
        for loc in ('East London, South Africa','London, Ontario, Canada','London, KY','Milan, TN, US','Rome, GA, USA'):
            self.assertFalse(allowed('Amazon',loc),loc)
    def test_configuration_edit_requires_no_code_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'companies_job_watch_v2.json'
            ps.atomic_json(p,{'companies':[{'company':'Visa','allowed_locations':['London']}]})
            self.assertTrue(allowed('Visa','London',root));self.assertFalse(allowed('Visa','Luxembourg',root))
            ps.atomic_json(p,{'companies':[{'company':'Visa','allowed_locations':['Luxembourg']}]})
            self.assertFalse(allowed('Visa','London',root));self.assertTrue(allowed('Visa','Luxembourg',root))
    def test_filtered_foreign_inventory_stops_before_jd_and_backlog_and_daily(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);f=Fixture(root)
            current=f.get('current_jobs_jw3.json');current['companies'][0]['jobs']=[{'source_id':'1','title':'Business Analyst','location':loc,'fingerprint':'abc','status':'NEW'} for loc in ('London','Luxembourg')]
            f.put('current_jobs_jw3.json',current)
            with f.modules(),patch.object(enrich,'fetch_jd') as fetch:
                self.assertEqual(enrich.fetch_candidates('jw3',root=root,fetch=True),[])
                self.assertEqual(daily.build_worklist()['records'],[])
                self.assertEqual(sync.project_batch('jw3',root)['queue'],[])
                fetch.assert_not_called()
    def test_yello_query_uses_only_authorized_company_locations(self):
        rows=[{'id':1,'label':'Milan'},{'id':2,'label':'Rome'},{'id':3,'label':'London'}]
        self.assertEqual(collector._yello_target_filter_ids(rows,'Visa'),[1,2])
        self.assertEqual(collector._yello_target_filter_ids(rows,'Amazon'),[1,2,3])

    def test_adapter_applies_policy_in_metadata_loop(self):
        mapped={'company':'Visa','ats':{'inventory_url':'https://visa.wd3.myworkdayjobs.com/Careers'}}
        rows=[{'externalPath':f'/job/{city}/Analyst_R{10000+i}','title':'Analyst','locationsText':city} for i,city in enumerate(('London','Luxembourg','Milan'))]
        with patch.object(collector,'post_json',return_value={'total':3,'jobPostings':rows}),patch.object(collector,'get_html') as detail:
            result=collector.collect_workday(mapped)
            self.assertEqual([r['location'] for r in result['jobs']],['Milan']);detail.assert_not_called()

class MigrationTests(unittest.TestCase):
    def test_fixture_has_no_state_loss_or_silent_unresolved_drop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);f=Fixture(root)
            for b in ps.BATCHES:(root/f'job_memory_{b}.json').unlink()
            for name in LEGACY:f.put(name,{'batch':name[-8:-5],'records':{} if not name.startswith('semantic_queue') else []})
            semantic=full_decision();surface={'fingerprint':'abc','surfaced_at':'2026-10-01T08:00:00Z','surfaced_status':'NEW'}
            f.put('semantic_decisions_jw3.json',{'records':{'JW3::1':semantic}})
            f.put('surfaced_jobs_jw3.json',{'records':{'JW3::1':surface}})
            users={f'JW3::{i}':{'decision':state,'decided_at':'2026-10-01','reason':'Original reason','rejection_reason':'TOO_SENIOR'} for i,state in enumerate(('INTERESTED','TO_REVIEW','APPLIED','NOT_INTERESTED'),1)}
            users['Missing::1']={'decision':'APPLIED','decided_at':'2026-10-01'};f.put('user_job_decisions.json',{'records':users})
            current=f.get('current_jobs_jw3.json');current['companies'][0]['jobs']=[{'source_id':'1','title':'Business Analyst','location':'Milan','fingerprint':'abc','status':'NEW'}];f.put('current_jobs_jw3.json',current)
            f.put('analysis_results_jw3.json',{'records':{'JW3::1':{'company':'JW3','source_id':'1','first_seen_at':'2025-01-01','current_open':True}}})
            f.put('daily_worklist.json',{'records':[]})
            report=migrate(root);memory=load_memory('jw3',root)['records']
            self.assertEqual(memory['JW3::1']['semantic'],semantic)
            self.assertEqual(memory['JW3::1']['surfacing']['first_surfaced_at'],surface['surfaced_at'])
            self.assertEqual(memory['JW3::1']['identity']['first_seen_at'],'2025-01-01')
            for k,v in users.items():self.assertEqual(memory[k]['user'] if k.startswith('JW3::') else report['unresolved_user_decisions'][k],v)
            self.assertEqual(report['user_total'],5);self.assertFalse(any((root/n).exists() for n in LEGACY))
            before={p.name:p.read_bytes() for p in root.glob('*.json')};migrate(root)
            self.assertTrue(all(p.read_bytes()==before[p.name] for p in root.glob('*.json')))
