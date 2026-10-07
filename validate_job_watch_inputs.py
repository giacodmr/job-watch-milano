#!/usr/bin/env python3
"""Validate persistent Job Watch inputs before any state regeneration."""
import json
from rejection_reasons import REJECTION_REASONS, infer_rejection_reason, reason_is_vague
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1","jw2","jw3","jw4")
REQUIRED_CONFIG = (
    "job_watch_rules.json",
    "job_watch_batches.json",
    "companies_job_watch_v2.json",
    "company_candidates.json",
)

def load(name):
    p = ROOT / name
    if not p.exists() or p.stat().st_size < 20:
        raise SystemExit(f"INPUT ERROR: {name} missing or suspiciously small")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"INPUT ERROR: {name} invalid JSON: {e}")


for name in REQUIRED_CONFIG:
    load(name)

companies = load("companies_job_watch_v2.json")
if not isinstance(companies.get("companies"), list):
    raise SystemExit("INPUT ERROR: companies_job_watch_v2.json companies must be a list")
company_names = [r.get("company") for r in companies["companies"] if isinstance(r, dict)]
if len(company_names) != len(set(company_names)) or any(not x for x in company_names):
    raise SystemExit("INPUT ERROR: active company registry contains blank/duplicate names")
known_locations={'Milan','Rome','London','Luxembourg'}
for company in companies['companies']:
    locations=company.get('allowed_locations')
    assert isinstance(locations,list) and set(locations)<=known_locations, f"Invalid allowed_locations: {company['company']}"
    assert len(locations)==len(set(locations)), f"Duplicate allowed_locations: {company['company']}"
candidates = load("company_candidates.json")
if not isinstance(candidates.get("records"), dict):
    raise SystemExit("INPUT ERROR: company_candidates.json records must be an object")
for key, row in candidates["records"].items():
    if not isinstance(key, str) or not isinstance(row, dict) or row.get("company") != key:
        raise SystemExit(f"INPUT ERROR: invalid company candidate {key}")

from job_memory import load_memory, validate_memory, older_timestamp
owners = {c:b.lower() for b,g in load('job_watch_batches.json')['batches'].items() for c in g['companies']}
try:
    migration_baseline=json.loads(subprocess.run(['git','show','HEAD:user_job_decisions.json'],cwd=ROOT,capture_output=True,text=True,check=True).stdout)['records']
except (ValueError,KeyError,subprocess.CalledProcessError): migration_baseline={}
for b in BATCHES:
    memory=load_memory(b, ROOT)
    validate_memory(memory,b,owners)
    # A schema upgrade is audited separately; normal edits cannot erase memory.
    try:
        previous = json.loads(subprocess.run(['git','show',f'HEAD:job_memory_{b}.json'],cwd=ROOT,capture_output=True,text=True,check=True).stdout)['records']
    except (ValueError,KeyError,subprocess.CalledProcessError): previous={}
    assert set(previous) <= set(memory['records']), f'Memory keys lost in {b}'
    for key, row in memory['records'].items():
        prior=previous.get(key,{})
        for section in ('semantic','user','surfacing'):
            assert not prior.get(section) or row.get(section), f'Durable section erased: {key}:{section}'
        user=row.get('user', {})
        old=prior.get('user', {})
        if old.get('decided_at') and user.get('decided_at'):
            assert not older_timestamp(user['decided_at'],old['decided_at']), f'Older user decision overwrote {key}'
        category=user.get('rejection_reason')
        if category is not None: assert category in REJECTION_REASONS, f'Invalid rejection reason: {key}'
        # The first schema-upgrade commit is checked against preserved legacy
        # choices; all subsequent new/revised rejections need explicit feedback.
        if not previous: old=migration_baseline.get(key,old)
        if user.get('decision')=='NOT_INTERESTED' and user!=old:
            assert category and not reason_is_vague(user.get('reason')), f'Ask rejection reason: {key}'
            inferred=infer_rejection_reason(user.get('reason'))
            assert not inferred or inferred==category, f'Conflicting rejection reason: {key}'
        if row.get('surfacing') and prior.get('surfacing'):
            assert row['surfacing']['first_surfaced_at']==prior['surfacing']['first_surfaced_at'], f'First surface timestamp changed: {key}'
            assert row['surfacing']['surface_count']>=prior['surfacing']['surface_count'], f'Surface count decreased: {key}'

rules = load("job_watch_rules.json")
if not (rules.get("run_certification_policy") or {}).get("enabled"):
    raise SystemExit("INPUT ERROR: run_certification_policy missing/disabled")

for b in BATCHES: load(f'ats_mapping_{b}.json')

# Run identity, coverage and completion are derived, never trusted inputs.
print("Job Watch persistent input validation passed.")
