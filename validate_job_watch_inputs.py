#!/usr/bin/env python3
"""Validate persistent Job Watch inputs before any state regeneration."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1","jw2","jw3","jw4")
REQUIRED_CONFIG = (
    "job_watch_rules.json",
    "job_watch_batches.json",
    "companies_job_watch_v2.json",
    "watchlist_additions.json",
    "discovery_candidates.json",
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

rules = load("job_watch_rules.json")
if not (rules.get("run_certification_policy") or {}).get("enabled"):
    raise SystemExit("INPUT ERROR: run_certification_policy missing/disabled")

for b in BATCHES:
    load(f"ats_mapping_{b}.json")
    decisions = load(f"semantic_decisions_{b}.json")
    surfaced = load(f"surfaced_jobs_{b}.json")
    if not isinstance(decisions.get("records"), dict):
        raise SystemExit(f"INPUT ERROR: semantic_decisions_{b}.json records must be an object")
    if not isinstance(surfaced.get("records"), dict):
        raise SystemExit(f"INPUT ERROR: surfaced_jobs_{b}.json records must be an object")
    for key, value in decisions["records"].items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise SystemExit(f"INPUT ERROR: invalid semantic decision record in {b}")
        if "fingerprint" not in value or "analysis_status" not in value:
            raise SystemExit(f"INPUT ERROR: semantic decision {key} in {b} lacks fingerprint/status")
    for key, value in surfaced["records"].items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise SystemExit(f"INPUT ERROR: invalid surfaced record in {b}")
        if not value.get("surfaced_at") or not value.get("surfaced_status"):
            raise SystemExit(f"INPUT ERROR: surfaced record {key} in {b} lacks timestamp/status")

run_state = load("job_watch_run_state.json")
if set((run_state.get("source_generated_at") or {}).keys()) != {"JW1","JW2","JW3","JW4"}:
    raise SystemExit("INPUT ERROR: run-state source_generated_at must contain JW1-JW4")
if set((run_state.get("batches") or {}).keys()) != {"JW1","JW2","JW3","JW4"}:
    raise SystemExit("INPUT ERROR: run-state batches must contain JW1-JW4")
if not isinstance(run_state.get("priority_checks"), dict):
    raise SystemExit("INPUT ERROR: run-state priority_checks missing")
if not isinstance(run_state.get("priority_snapshot_at"), dict):
    raise SystemExit("INPUT ERROR: run-state priority_snapshot_at missing")
if not isinstance(run_state.get("blocking_errors"), list):
    raise SystemExit("INPUT ERROR: run-state blocking_errors must be a list")

print("Job Watch persistent input validation passed.")
