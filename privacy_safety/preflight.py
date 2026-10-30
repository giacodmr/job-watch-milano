"""Offline workflow checks and bounded GET-only GitHub metadata probes."""
import copy
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
import urllib.error
import urllib.request

from .common import REPOSITORY, SafetyError, canonical, digest, git, utc_now

REPO_ID = 1353778491
WRITERS = ('collect_jobs.yml','sync_semantic_state.yml','chatgpt_job_watch_bridge.yml','amazon_priority.yml')
DOCS = ('DAILY.md','DAILY_PROMPT.txt','CHATGPT_WORKER_PROMPT.txt','JOB_WATCH_BRIDGE.md','CHATGPT_HANDOFF_E_RICORRENZE.md')
MANUAL = ('BILLING_OVERAGE_STOP_VERIFIED','PRIVATE_BRANCH_CONTROLS_REVIEWED',
          'CHATGPT_WORKER_PRIVATE_CONNECTOR_AND_RECURRENCE', 'DAILY_PRIVATE_CONNECTOR_AND_RECURRENCE',
          'RECOVERY_KEY_CUSTODY_AND_OFFLINE_DESTINATION', 'NO_UNCHECKPOINTED_BRIDGE_REQUEST',
          'RESTORE_REHEARSAL_VERIFIED')

def check(code, status, **facts):
    return {'check':code, 'status':status, **facts}

def workflow(path):
    try:
        import yaml
        class Loader(yaml.SafeLoader):
            pass
        Loader.yaml_implicit_resolvers = copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)
        for key, rows in Loader.yaml_implicit_resolvers.items():
            Loader.yaml_implicit_resolvers[key] = [(tag, regex) for tag, regex in rows if tag != 'tag:yaml.org,2002:bool']
        Loader.add_implicit_resolver('tag:yaml.org,2002:bool', re.compile(r'^(?:true|false|True|False|TRUE|FALSE)$'), list('tTfF'))
        # Duplicate YAML keys must not silently replace a safety setting.
        def mapping(loader, node):
            values = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node)
                if key in values: raise ValueError('duplicate')
                values[key] = loader.construct_object(value_node)
            return values
        Loader.add_constructor('tag:yaml.org,2002:map', mapping)
        if path.stat().st_size > 1024*1024: raise ValueError('size')
        data = yaml.load(path.read_text(), Loader=Loader)
        if not isinstance(data, dict): raise ValueError('shape')
        return data
    except ImportError:
        raise SafetyError('PYYAML_REQUIRED') from None
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        raise SafetyError('WORKFLOW_PARSE_FAILED') from None

def offline(root, age='age'):
    root = Path(root)
    rows = [check('PYTHON_3_12_PLUS', 'PASS' if sys.version_info >= (3,12) else 'BLOCKED')]
    for package in ('requests','PyYAML'):
        try: importlib.metadata.version(package); present = True
        except importlib.metadata.PackageNotFoundError: present = False
        rows.append(check('DEPENDENCY_'+package.upper(), 'PASS' if present else 'BLOCKED'))
    rows.append(check('AGE_AVAILABLE', 'PASS' if shutil.which(age) else 'BLOCKED'))
    rows.append(check('GIT_NOT_SHALLOW', 'PASS' if git(root,'rev-parse','--is-shallow-repository').strip()==b'false' else 'BLOCKED'))
    for name in DOCS:
        rows.append(check('DOC_'+name.replace('.','_'), 'PASS' if (root/name).is_file() else 'BLOCKED'))
    definitions = {}
    for name in WRITERS:
        try:
            data = workflow(root/'.github/workflows'/name); definitions[name] = data
            settings = data.get('concurrency', {})
            good = settings.get('group') == 'job-watch-state-writer' and settings.get('cancel-in-progress') is False and settings.get('queue') == 'max'
            rows.append(check('WRITER_'+name.replace('.','_'), 'PASS' if good else 'BLOCKED'))
        except SafetyError:
            rows.append(check('WRITER_'+name.replace('.','_'), 'BLOCKED'))
    bridge = definitions.get('chatgpt_job_watch_bridge.yml', {})
    push = bridge.get('on',{}).get('push',{})
    trigger = push.get('branches') == ['main'] and push.get('paths') == ['.job_watch_bridge/requests/*.json']
    rows.append(check('BRIDGE_TRIGGER_CONTRACT', 'PASS' if trigger else 'BLOCKED'))
    schedule = definitions.get('collect_jobs.yml',{}).get('on',{}).get('schedule',[])
    rows.append(check('COLLECTOR_SCHEDULE_DECLARED', 'PASS' if schedule else 'BLOCKED', entries=len(schedule)))
    # A declared prompt is not evidence that an external ChatGPT task can access a private repo.
    rows.extend(check(code,'MANUAL_REQUIRED') for code in MANUAL)
    return rows

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class GitHubReadClient:
    def __init__(self, token=None):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect)

    def get(self, path):
        if not (path.startswith('/repos/'+REPOSITORY+'/') or path == '/repos/'+REPOSITORY or path in {'/user','/installation/repositories'}):
            raise SafetyError('API_PATH_FORBIDDEN')
        headers = {'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'job-watch-privacy-preflight'}
        if self.token: headers['Authorization'] = 'Bearer '+self.token
        req = urllib.request.Request('https://api.github.com'+path, headers=headers, method='GET')
        try:
            with self.opener.open(req, timeout=20) as response:
                raw = response.read(8*1024*1024+1)
                if len(raw)>8*1024*1024: raise SafetyError('API_RESPONSE_TOO_LARGE')
                result = json.loads(raw)
                if not isinstance(result,dict): raise SafetyError('API_SHAPE_INVALID')
                return result
        except (urllib.error.URLError, ValueError, TimeoutError, OSError):
            raise SafetyError('API_READ_UNAVAILABLE') from None

    def pages(self, path, field, max_pages=10):
        result = []
        for page in range(1,max_pages+1):
            separator = '&' if '?' in path else '?'
            data = self.get(path+f'{separator}per_page=100&page={page}')
            items = data.get(field)
            if not isinstance(items,list): raise SafetyError('API_SHAPE_INVALID')
            result.extend(items)
            if len(items)<100: return result
        raise SafetyError('API_PAGINATION_INCOMPLETE')

def online(client, phase):
    prefix = '/repos/'+REPOSITORY
    rows, facts = [], {}
    authenticated = False
    if client.token:
        for path in ('/user','/installation/repositories'):
            try:
                client.get(path); authenticated = True; break
            except SafetyError: pass
    rows.append(check('CREDENTIAL_AUTHENTICATED_NOW','PASS' if authenticated else 'MANUAL_REQUIRED'))
    try:
        repo = client.get(prefix)
        same = repo.get('id') == REPO_ID and repo.get('full_name') == REPOSITORY and repo.get('default_branch') == 'main'
        rows.append(check('REPOSITORY_IDENTITY', 'PASS' if same else 'BLOCKED'))
        private = repo.get('private')
        rows.append(check('VISIBILITY_EXPECTATION','PASS' if isinstance(private,bool) and private == (phase=='after') else 'BLOCKED'))
        facts.update(repository_id=repo.get('id'), private=private)
        ref = client.get(prefix+'/git/ref/heads/main')
        facts['main_sha'] = ref['object']['sha']
        commit = client.get(prefix+'/git/commits/'+facts['main_sha'])
        rows.append(check('PINNED_GIT_COMMIT_READ','PASS' if commit.get('sha')==facts['main_sha'] else 'BLOCKED'))
        flows = client.pages(prefix+'/actions/workflows','workflows')
        indexed = {f.get('path'):f for f in flows}
        active = all(indexed.get('.github/workflows/'+name,{}).get('state')=='active' for name in WRITERS)
        rows.append(check('ACTIONS_CRITICAL_WORKFLOWS_ACTIVE','PASS' if active else 'BLOCKED'))
        artifacts = client.get(prefix+'/actions/artifacts?per_page=1')
        rows.append(check('ARTIFACT_METADATA_READ','PASS' if isinstance(artifacts.get('artifacts'),list) else 'BLOCKED'))
        runs = []
        for status in ('queued','in_progress','waiting','pending','requested'):
            runs.extend(client.pages(prefix+'/actions/runs?status='+status,'workflow_runs'))
        live = {r['id'] for r in runs}
        rows.append(check('NO_ACTIVE_ACTIONS_RUNS','PASS' if not live else 'BLOCKED', count=len(live)))
    except (SafetyError, KeyError, TypeError):
        rows.append(check('REMOTE_METADATA_COMPLETE','BLOCKED'))
    try:
        permission = client.get(prefix+'/actions/permissions')
        rows.append(check('ACTIONS_ENABLED','PASS' if permission.get('enabled') is True else 'BLOCKED'))
    except SafetyError:
        rows.append(check('ACTIONS_ENABLED','MANUAL_REQUIRED'))
    # Reading PUBLIC metadata with an authenticated token does not prove private permissions.
    rows.append(check('PRIVATE_ACCESS_PROVEN','PASS' if authenticated and facts.get('private') is True else 'MANUAL_REQUIRED'))
    return rows, facts

def preflight(root, *, phase='before', age='age', client=None):
    rows = offline(root,age)
    facts = {}
    if client:
        remote, facts = online(client,phase); rows.extend(remote)
    else:
        rows.append(check('GITHUB_READ_ONLY_METADATA','MANUAL_REQUIRED'))
    return {'version':1,'repository':REPOSITORY,'observed_at':utc_now(),'phase':phase,
            'ready':all(row['status']=='PASS' for row in rows),
            'automated_checks_pass':not any(row['status']=='BLOCKED' for row in rows), 'checks':rows, 'remote':facts,
            'local_head':git(root,'rev-parse','HEAD').decode().strip(),
            'workflow_docs_sha256':digest(canonical({name:digest((Path(root)/name).read_bytes())
              for name in DOCS+tuple('.github/workflows/'+n for n in WRITERS) if (Path(root)/name).is_file()}))}

def compare_preflight(before, after):
    """Same quiet checkpoint, same configuration, real private authenticated read."""
    try:
        if (before['version'], after['version'], before['repository'], after['repository'], before['phase'], after['phase']) != (1,1,REPOSITORY,REPOSITORY,'before','after'):
            raise ValueError('shape')
        for field in ('local_head','workflow_docs_sha256'):
            if before[field] != after[field]: raise SafetyError('PREFLIGHT_CHECKPOINT_MISMATCH')
        for field in ('repository_id','main_sha'):
            if before['remote'][field] != after['remote'][field]: raise SafetyError('PREFLIGHT_CHECKPOINT_MISMATCH')
        if before['remote']['private'] is not False or after['remote']['private'] is not True:
            raise SafetyError('VISIBILITY_TRANSITION_NOT_PROVEN')
        checks = {row['check']:row['status'] for row in after['checks']}
        if not after['automated_checks_pass'] or checks.get('PRIVATE_ACCESS_PROVEN') != 'PASS':
            raise SafetyError('PRIVATE_ACCESS_NOT_PROVEN')
    except (KeyError,TypeError,ValueError):
        raise SafetyError('INVALID_PREFLIGHT_EVIDENCE') from None
    return {'status':'PREFLIGHT_CHECKPOINT_MATCH','manual_checks_still_required':True}
