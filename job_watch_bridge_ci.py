#!/usr/bin/env python3
"""Reuse proven validation on transport-only commits; fail closed on missing proof."""
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess

from job_watch import DERIVED, REGISTRIES

STATE = set(DERIVED + REGISTRIES + ['job_watch_run_state.json','amazon_target_check.json'])


def state_path(path):
    return (path in STATE or re.fullmatch(r'current_jobs_jw[1-4]\.json', path) is not None
            or path.startswith('archive/') and path.endswith('.jsonl')
            or path.startswith(('.job_watch_bridge/requests/', '.job_watch_bridge/receipts/')) and path.endswith('.json'))


def git(*args):
    return subprocess.check_output(['git',*args],text=True,stderr=subprocess.DEVNULL).strip()


def fingerprint(ref):
    entries = git('ls-tree','-r',ref).splitlines()
    return hashlib.sha256('\n'.join(e for e in entries if not state_path(e.split('\t',1)[1])).encode()).hexdigest()


def reusable(event, api):
    """A data-only request needs earlier code proof; a checkpoint needs Actions proof."""
    head = event.get('pull_request',{}).get('head',{}).get('sha')
    if not head:
        return False
    changed = git('diff-tree','--no-commit-id','--name-only','-r',head).splitlines()
    if not changed:
        return False
    request_only = all(p.startswith(('.job_watch_bridge/requests/', '.job_watch_bridge/receipts/')) and p.endswith('.json') for p in changed)
    if request_only:
        expected = fingerprint(head)
        if fingerprint('HEAD') != expected:
            return False  # PR merge checkout can contain new base-branch inputs.
        for run in api('actions/workflows/validate.yml/runs?status=success&per_page=30')['workflow_runs']:
            sha = run['head_sha']
            if sha != head and run.get('conclusion') == 'success':
                try:
                    git('merge-base','--is-ancestor',sha,head)
                    if fingerprint(sha) == expected:
                        return True
                except subprocess.CalledProcessError:
                    continue
        return False
    if event.get('sender',{}).get('login') != 'github-actions[bot]' or not all(state_path(p) for p in changed):
        return False
    parent = git('rev-parse',head+'^')
    if fingerprint('HEAD') != fingerprint(head):
        return False
    # The exact apply run must already have completed its full validation step.
    for run in api('actions/workflows/chatgpt_job_watch_bridge.yml/runs?head_sha='+parent+'&per_page=10')['workflow_runs']:
        if run.get('head_sha') != parent or run.get('event') != 'push':
            continue
        if fingerprint(head) != fingerprint(parent):
            continue
        for job in api('actions/runs/'+str(run['id'])+'/jobs')['jobs']:
            if any(s.get('name') == 'Validate batch once before publication' and s.get('conclusion') == 'success' for s in job.get('steps',[])):
                return True
    return False


def main():
    needed = True
    if os.environ.get('GITHUB_EVENT_NAME') == 'pull_request':
        try:
            import requests
            base = 'https://api.github.com/repos/' + os.environ['GITHUB_REPOSITORY'] + '/'
            def api(path):
                response = requests.get(base+path,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN']},timeout=15)
                response.raise_for_status()
                return response.json()
            event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
            needed = not reusable(event,api)
        except (OSError,ValueError,KeyError,subprocess.CalledProcessError,requests.RequestException):
            needed = True
    with open(os.environ['GITHUB_OUTPUT'],'a') as out:
        print('needed='+str(needed).lower(),file=out)
    print('Full validation required' if needed else 'Reusing verified code/apply validation for transport checkpoint')


if __name__ == '__main__':
    main()
