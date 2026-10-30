"""Synthetic safety fixtures only: never read production data or call GitHub."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest
from unittest.mock import patch

from privacy_safety.common import SafetyError, canonical, digest, git, read_private_json, write_private
from privacy_safety.continuity import capture, compare
from privacy_safety.git_backup import census, create_backup, restore_backup
from privacy_safety.preflight import GitHubReadClient, MANUAL, REPO_ID, WRITERS, offline, online, workflow, compare_preflight
from privacy_safety.publish_guard import check_publish

AGE = os.environ.get('JOB_WATCH_AGE_BIN') or shutil.which('age')
KEYGEN = str(Path(AGE).with_name('age-keygen')) if AGE else None
HAS_AGE = bool(AGE and KEYGEN and Path(KEYGEN).is_file())
HAS_YAML = importlib.util.find_spec('yaml') is not None

class GitFixture:
    def __init__(self, parent):
        self.root = Path(parent)/'source';self.root.mkdir(mode=0o700)
        git(self.root,'init','-b','main')
        git(self.root,'config','user.name','Synthetic Fixture')
        git(self.root,'config','user.email','synthetic@example.test')
        (self.root/'history.txt').write_text('Synthetic decision history\n')
        self.commit('first')
        git(self.root,'branch','preserved-branch')
        git(self.root,'tag','-a','preserved-tag','-m','Synthetic tag')
        (self.root/'history.txt').write_text('Synthetic changed decision\n')
        self.commit('second')
        self.remote = Path(parent)/'remote.git'
        subprocess.run(['git','clone','--mirror',str(self.root),str(self.remote)],check=True,capture_output=True)
        first = git(self.root,'rev-parse','preserved-branch').decode().strip()
        git(self.remote,'update-ref','refs/pull/7/head',first)
    def commit(self, message):
        git(self.root,'add','.');git(self.root,'commit','-m',message)

class PrivatePaths(unittest.TestCase):
    def test_evidence_mode_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'evidence.json'
            write_private(path,b'{"version":1}')
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(read_private_json(path),{'version':1})
            with self.assertRaisesRegex(SafetyError,'OUTPUT_ALREADY_EXISTS'):write_private(path,b'changed')
    def test_rejects_any_git_checkout_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)/'repo';repo.mkdir(mode=0o700);git(repo,'init')
            with self.assertRaisesRegex(SafetyError,'OUTPUT_INSIDE_GIT_FORBIDDEN'):write_private(repo/'private.json',b'bad')
            target=Path(tmp)/'target';target.write_text('synthetic');target.chmod(0o600)
            link=Path(tmp)/'link';link.symlink_to(target)
            with self.assertRaisesRegex(SafetyError,'OUTPUT_ALREADY_EXISTS'):write_private(link,b'bad')
            with self.assertRaisesRegex(SafetyError,'PRIVATE_FILE_REQUIRED'):read_private_json(link)
    def test_world_readable_destination_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'open';directory.mkdir(mode=0o755)
            with self.assertRaisesRegex(SafetyError,'PRIVATE_DIRECTORY_REQUIRED'):write_private(directory/'out',b'bad')
    def test_cli_redacts_invalid_arguments(self):
        result=subprocess.run([sys.executable,'tools/privacy_cutover.py','--token','SYNTHETIC_PRIVATE_CANARY'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY',result.stdout+result.stderr)
        self.assertNotIn('Traceback',result.stderr)

class EncryptedBackup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('PRIVACY_SAFETY_REQUIRE_AGE')=='1' and not HAS_AGE:
            raise AssertionError('Crypto integration requires age and age-keygen')
        if not HAS_AGE:raise unittest.SkipTest('Optional age dependency absent; dedicated safety CI requires it')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.fixture=GitFixture(self.root)
        self.key=self.root/'identity.agekey'
        run=subprocess.run([KEYGEN,'-o',str(self.key)],capture_output=True,check=True)
        self.key.chmod(0o600)
        self.recipient=subprocess.check_output([KEYGEN,'-y',str(self.key)]).decode().strip()
        self.capsule=self.root/'backup.age'
    def tearDown(self):self.tmp.cleanup()
    def backup(self):
        return create_backup(str(self.fixture.remote),self.capsule,self.recipient,age=AGE,repository='synthetic/repository')
    def restore(self, summary, **kw):
        return restore_backup(self.capsule,self.key,summary['capsule_sha256'],age=AGE,repository='synthetic/repository',**kw)
    def test_complete_refs_objects_and_offline_restore(self):
        before=census(str(self.fixture.remote));summary=self.backup()
        self.assertFalse(summary['restore_verified'])
        self.assertEqual(self.capsule.stat().st_mode & 0o777,0o600)
        self.assertTrue(self.capsule.read_bytes().startswith(b'age-encryption.org/v1'))
        self.assertNotIn(b'Synthetic changed decision',self.capsule.read_bytes())
        target=self.root/'restored.git';result=self.restore(summary,target=target)
        self.assertEqual(result['status'],'RESTORE_VERIFIED')
        self.assertEqual(census(str(target)),before)
        self.assertEqual(git(target,'remote').strip(),b'')
        self.assertEqual(git(target,'show','HEAD:history.txt'),b'Synthetic changed decision\n')
        self.assertEqual(git(target,'show','preserved-branch:history.txt'),b'Synthetic decision history\n')
        self.assertFalse((self.root/'repository.bundle').exists())
    def test_tamper_wrong_key_and_existing_target_fail_closed(self):
        summary=self.backup()
        with self.assertRaisesRegex(SafetyError,'CAPSULE_HASH_MISMATCH'):
            restore_backup(self.capsule,self.key,'a'*64,age=AGE)
        other=self.root/'other.agekey';subprocess.run([KEYGEN,'-o',str(other)],capture_output=True,check=True);other.chmod(0o600)
        with self.assertRaisesRegex(SafetyError,'BACKUP_DECRYPTION_FAILED'):
            restore_backup(self.capsule,other,summary['capsule_sha256'],age=AGE,repository='synthetic/repository')
        existing=self.root/'existing';existing.mkdir(mode=0o700)
        with self.assertRaisesRegex(SafetyError,'OUTPUT_ALREADY_EXISTS'):self.restore(summary,target=existing)
        content=bytearray(self.capsule.read_bytes());content[-5]^=1;self.capsule.write_bytes(content)
        with self.assertRaisesRegex(SafetyError,'BACKUP_DECRYPTION_FAILED'):
            restore_backup(self.capsule,self.key,digest(content),age=AGE,repository='synthetic/repository')
    def test_ref_movement_aborts_before_output(self):
        real=census(str(self.fixture.remote));changed={**real,'head':'a'*40}
        with patch('privacy_safety.git_backup.census',side_effect=[real,changed]):
            with self.assertRaisesRegex(SafetyError,'REMOTE_CHANGED_RETRY'):self.backup()
        self.assertFalse(self.capsule.exists())
    def test_capsule_symlink_and_open_permissions_rejected_before_read(self):
        summary=self.backup();link=self.root/'symlink.age';link.symlink_to(self.capsule)
        with patch('privacy_safety.git_backup.file_digest',side_effect=AssertionError('must not read')):
            with self.assertRaisesRegex(SafetyError,'PRIVATE_FILE_REQUIRED'):
                restore_backup(link,self.key,summary['capsule_sha256'],age=AGE,repository='synthetic/repository')
            self.capsule.chmod(0o644)
            with self.assertRaisesRegex(SafetyError,'PRIVATE_FILE_REQUIRED'):self.restore(summary)
    def test_all_history_submodule_payload_is_not_silently_lost(self):
        (self.fixture.root/'.gitmodules').write_text('[submodule "synthetic"]\npath=vendor\nurl=https://example.test/fixture\n')
        self.fixture.commit('submodule metadata')
        git(self.fixture.remote,'fetch',str(self.fixture.root),'+refs/heads/*:refs/heads/*')
        with self.assertRaisesRegex(SafetyError,'EXTERNAL_PAYLOAD_BACKUP_UNSUPPORTED'):self.backup()
        self.assertFalse(self.capsule.exists())
    def test_historical_lfs_pointer_is_refused(self):
        (self.fixture.root/'external.txt').write_text('version https://git-lfs.github.com/spec/v1\noid sha256:'+'a'*64+'\nsize 123\n')
        self.fixture.commit('external object')
        git(self.fixture.remote,'fetch',str(self.fixture.root),'+refs/heads/*:refs/heads/*')
        with self.assertRaisesRegex(SafetyError,'EXTERNAL_PAYLOAD_BACKUP_UNSUPPORTED'):self.backup()
    def test_malformed_encrypted_archive_has_no_restore_side_effect(self):
        for names in [('manifest.json','../escape'),('manifest.json','manifest.json')]:
            archive=self.root/'malformed.tar'
            with tarfile.open(archive,'w') as tar:
                for name in names:
                    entry=tarfile.TarInfo(name);entry.size=2;tar.addfile(entry,io.BytesIO(b'{}'))
            self.capsule.unlink(missing_ok=True)
            subprocess.run([AGE,'-r',self.recipient,'-o',str(self.capsule),str(archive)],check=True,capture_output=True)
            self.capsule.chmod(0o600);target=self.root/'malformed-restore.git'
            with self.assertRaisesRegex(SafetyError,'INVALID_CAPSULE_MEMBERS'):
                restore_backup(self.capsule,self.key,digest(self.capsule.read_bytes()),target=target,age=AGE,repository='synthetic/repository')
            self.assertFalse(target.exists());self.assertFalse((self.root/'escape').exists())
    def test_detached_remote_head_is_preserved(self):
        git(self.fixture.remote,'update-ref','--no-deref','HEAD',git(self.fixture.root,'rev-parse','HEAD').decode().strip())
        summary=self.backup();target=self.root/'detached.git';self.restore(summary,target=target)
        self.assertIsNone(census(str(target))['symbolic_head'])
        self.assertEqual(target.stat().st_mode & 0o777,0o700)
    def test_shallow_mirror_is_not_called_complete(self):
        from privacy_safety.git_backup import assert_self_contained
        with patch('privacy_safety.git_backup.git',return_value=b'true\n'):
            with self.assertRaisesRegex(SafetyError,'SHALLOW_BACKUP_FORBIDDEN'):assert_self_contained(self.fixture.remote)

@unittest.skipUnless(HAS_YAML,'PyYAML installed in dedicated tooling environment/CI')
class WorkflowChecks(unittest.TestCase):
    def test_yaml12_on_and_false_are_not_misread(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'workflow.yml';path.write_text('on:\n  push: {}\nconcurrency:\n  cancel-in-progress: false\n')
            data=workflow(path)
            self.assertIn('on',data);self.assertIs(data['concurrency']['cancel-in-progress'],False)
    def test_duplicate_keys_and_unsafe_tags_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'workflow.yml'
            for text in ['on: {}\non: {}\n','value: !!python/object/apply:os.system [echo]']:
                path.write_text(text)
                with self.assertRaisesRegex(SafetyError,'WORKFLOW_PARSE_FAILED'):workflow(path)
    def test_declared_contracts_are_not_claimed_as_external_automation_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);git(root,'init');(root/'.github/workflows').mkdir(parents=True)
            from privacy_safety.preflight import DOCS
            for name in DOCS:(root/name).write_text('Synthetic instructions')
            for name in WRITERS:
                text='concurrency:\n  group: job-watch-state-writer\n  cancel-in-progress: false\n  queue: max\non:\n'
                text+=('  push:\n    branches: [main]\n    paths: [".job_watch_bridge/requests/*.json"]\n' if 'bridge' in name else '  schedule: [{cron: "0 1 * * *"}]\n')
                (root/'.github/workflows'/name).write_text(text)
            rows=offline(root,age=AGE or 'age')
            self.assertTrue(all(r['status']=='PASS' for r in rows if r['check'].startswith('WRITER_')))
            self.assertTrue(all(any(r['check']==m and r['status']=='MANUAL_REQUIRED' for r in rows) for m in MANUAL))
            path=root/'.github/workflows/collect_jobs.yml';path.write_text(path.read_text().replace('cancel-in-progress: false','cancel-in-progress: true'))
            self.assertIn({'check':'WRITER_collect_jobs_yml','status':'BLOCKED'},offline(root,age=AGE or 'age'))

class FakeGitHub(GitHubReadClient):
    def __init__(self, private=False, token='synthetic-token', busy=False):
        self.token=token;self.private=private;self.busy=busy;self.paths=[]
    def get(self,path):
        self.paths.append(path)
        if path=='/user':return {'login':'SYNTHETIC_PRIVATE_CANARY'}
        if path.endswith('/actions/permissions'):return {'enabled':True}
        if '/git/ref/' in path:return {'object':{'sha':'a'*40}}
        if '/git/commits/' in path:return {'sha':'a'*40}
        if '/actions/workflows?' in path:return {'workflows':[{'path':'.github/workflows/'+f,'state':'active'} for f in WRITERS]}
        if '/actions/runs?' in path:return {'workflow_runs':[{'id':7}] if self.busy and 'status=queued&' in path else []}
        if '/actions/artifacts?' in path:return {'artifacts':[]}
        return {'id':REPO_ID,'full_name':'giacodmr/job-watch-milano','default_branch':'main','private':self.private,'description':'SYNTHETIC_PRIVATE_CANARY'}

class RemoteChecks(unittest.TestCase):
    def test_public_read_is_not_private_access_proof(self):
        rows,_=online(FakeGitHub(), 'before')
        self.assertIn({'check':'PRIVATE_ACCESS_PROVEN','status':'MANUAL_REQUIRED'},rows)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY',json.dumps(rows))
    def test_private_authenticated_read_and_busy_runs(self):
        rows,facts=online(FakeGitHub(private=True,busy=True),'after')
        self.assertIn({'check':'PRIVATE_ACCESS_PROVEN','status':'PASS'},rows)
        self.assertIn({'check':'NO_ACTIVE_ACTIONS_RUNS','status':'BLOCKED','count':1},rows)
        self.assertTrue(facts['private'])
    def test_missing_credentials_never_get_an_authenticated_pass(self):
        rows,_=online(FakeGitHub(private=True,token=None),'after')
        self.assertIn({'check':'CREDENTIAL_AUTHENTICATED_NOW','status':'MANUAL_REQUIRED'},rows)
        self.assertIn({'check':'PRIVATE_ACCESS_PROVEN','status':'MANUAL_REQUIRED'},rows)
    def test_bounded_pagination_and_get_only_allowlist(self):
        class Endless(GitHubReadClient):
            def get(self,path):return {'items':[{}]*100}
        with self.assertRaisesRegex(SafetyError,'API_PAGINATION_INCOMPLETE'):Endless().pages('/repos/giacodmr/job-watch-milano/items','items',max_pages=2)
        client=GitHubReadClient('SYNTHETIC_PRIVATE_CANARY')
        with self.assertRaisesRegex(SafetyError,'API_PATH_FORBIDDEN'):client.get('https://example.test/exfiltrate')
        class Opening:
            def open(self,request,timeout):
                self.method=request.get_method()
                raise OSError('SYNTHETIC_PRIVATE_CANARY')
        fake=Opening();client.opener=fake
        with self.assertRaisesRegex(SafetyError,'API_READ_UNAVAILABLE') as error:client.get('/repos/giacodmr/job-watch-milano')
        self.assertEqual(fake.method,'GET');self.assertNotIn('SYNTHETIC_PRIVATE_CANARY',str(error.exception))

class PreflightComparison(unittest.TestCase):
    def evidence(self,private):
        return {'version':1,'repository':'giacodmr/job-watch-milano','phase':'after' if private else 'before',
                'local_head':'a'*40,'workflow_docs_sha256':'b'*64,'automated_checks_pass':True,
                'remote':{'repository_id':REPO_ID,'main_sha':'c'*40,'private':private},
                'checks':[{'check':'PRIVATE_ACCESS_PROVEN','status':'PASS' if private else 'MANUAL_REQUIRED'}]}
    def test_same_checkpoint_and_actual_private_access_required(self):
        before,after=self.evidence(False),self.evidence(True)
        self.assertEqual(compare_preflight(before,after)['status'],'PREFLIGHT_CHECKPOINT_MATCH')
        after['remote']['main_sha']='d'*40
        with self.assertRaisesRegex(SafetyError,'PREFLIGHT_CHECKPOINT_MISMATCH'):compare_preflight(before,after)
    def test_private_connection_cannot_be_assumed_from_public_read(self):
        before,after=self.evidence(False),self.evidence(True)
        after['checks'][0]['status']='MANUAL_REQUIRED'
        with self.assertRaisesRegex(SafetyError,'PRIVATE_ACCESS_NOT_PROVEN'):compare_preflight(before,after)

class PublicationChecks(unittest.TestCase):
    def test_scope_secret_binary_and_symlink_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture=GitFixture(tmp);root=fixture.root;base=git(root,'rev-parse','HEAD').decode().strip()
            path=root/'tools/privacy_cutover.py';path.parent.mkdir()
            path.write_text('# Synthetic tooling\n')
            self.assertEqual(check_publish(root,base)['files'],1)
            path.write_text('gh'+'p_'+'S'*40)
            with self.assertRaisesRegex(SafetyError,'PUBLISH_SENSITIVE_CONTENT'):check_publish(root,base)
            path.write_bytes(b'binary\x00payload')
            with self.assertRaisesRegex(SafetyError,'PUBLISH_SENSITIVE_CONTENT'):check_publish(root,base)
            path.unlink();path.symlink_to(root/'history.txt')
            with self.assertRaisesRegex(SafetyError,'PUBLISH_SYMLINK_FORBIDDEN'):check_publish(root,base)
            path.unlink();(root/'job_memory_jw1.json').write_text('{}')
            with self.assertRaisesRegex(SafetyError,'PUBLISH_SCOPE_VIOLATION'):check_publish(root,base)

class ContinuityChecks(unittest.TestCase):
    def test_misaligned_time_or_commit_is_not_a_behavior_regression(self):
        baseline={'version':1,'repository':'fixture','commit_sha':'a'*40,'evaluation_at':'2026-10-30T08:00:00Z','tree_sha':'b'*40,'engine':{}}
        with self.assertRaisesRegex(SafetyError,'CONTINUITY_CHECKPOINT_MISMATCH'):compare(baseline,{**baseline,'evaluation_at':'2026-10-31T08:00:00Z'})
        with self.assertRaisesRegex(SafetyError,'CONTINUITY_CHANGED'):compare(baseline,{**baseline,'engine':{'changed':True}})
    def test_real_engine_pinned_fixture_ignores_dirty_checkout_and_transport_settings(self):
        from test_pipeline_resilience import Fixture
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'fixture';root.mkdir(mode=0o700);fixture=Fixture(root)
            for i,state in [(1,'APPLIED'),(2,'NOT_INTERESTED')]:
                name=f'JW{i}';batch=f'jw{i}';current=fixture.get(f'current_jobs_{batch}.json')
                job={'company':name,'source_id':'1','title':'Business Analyst','location':'Milan','fingerprint':'abc','status':'UPDATED','canonical_url':f'https://example.test/{batch}/1'}
                current['companies'][0]['jobs']=[job];fixture.put(f'current_jobs_{batch}.json',current)
                fixture.put(f'job_memory_{batch}.json',{'batch':name,'records':{name+'::1':{'identity':job,'user':{'decision':state,'decided_at':'2026-10-01T08:00:00Z','fingerprint':'abc','reason':'Synthetic private reason','rejection_reason':'OTHER'}}}})
            git(root,'init','-b','main');git(root,'config','user.name','Synthetic');git(root,'config','user.email','synthetic@example.test')
            git(root,'add','.');git(root,'commit','-m','Synthetic snapshot')
            sha=git(root,'rev-parse','HEAD').decode().strip();at='2026-10-30T08:00:00Z'
            before=capture(root,sha,at=at)
            (root/'job_memory_jw1.json').write_text('SYNTHETIC_PRIVATE_CANARY dirty state')
            git(root,'config','privacy.simulatedVisibility','private')
            after=capture(root,sha,at=at)
            self.assertEqual(compare(before,after)['status'],'CONTINUITY_MATCH')
            self.assertNotIn('Synthetic private reason',json.dumps(before))
            self.assertEqual((root/'job_memory_jw1.json').read_text(),'SYNTHETIC_PRIVATE_CANARY dirty state')
            self.assertNotEqual(before['engine']['batches']['jw1']['queue'], '')

if __name__=='__main__':unittest.main()
