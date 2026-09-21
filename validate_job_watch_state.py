#!/usr/bin/env python3
"""Fail-fast integrity checks for Job Watch generated state."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1","jw2","jw3","jw4")

def load(name):
    p=ROOT/name
    if not p.exists() or p.stat().st_size < 20:
        raise SystemExit(f"INTEGRITY ERROR: {name} missing or suspiciously small")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"INTEGRITY ERROR: {name} invalid JSON: {e}")


def load_head(name):
    try:
        cp = subprocess.run(
            ["git", "show", f"HEAD:{name}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(cp.stdout)
    except Exception:
        return None

for b in BATCHES:
    cur=load(f"current_jobs_{b}.json")
    state=load(f"analysis_results_{b}.json")
    queue=load(f"semantic_queue_{b}.json")
    summary=cur.get("summary") or {}
    target=int(summary.get("target_jobs_open",0) or 0)
    previous=load_head(f"current_jobs_{b}.json")
    if previous:
        previous_target=int(((previous.get("summary") or {}).get("target_jobs_open",0)) or 0)
        if previous_target >= 20 and target < previous_target * 0.25:
            raise SystemExit(
                f"INTEGRITY ERROR: {b} suspicious inventory collapse "
                f"{previous_target}->{target}; refusing silent overwrite"
            )
        if previous_target >= 20 and target > previous_target * 5:
            raise SystemExit(
                f"INTEGRITY ERROR: {b} suspicious inventory explosion "
                f"{previous_target}->{target}; refusing silent overwrite"
            )
    records=state.get("records")
    if not isinstance(records,dict):
        raise SystemExit(f"INTEGRITY ERROR: {b} analysis records missing")
    open_records=sum(1 for r in records.values() if r.get("current_open"))
    if open_records != target:
        raise SystemExit(f"INTEGRITY ERROR: {b} current/state mismatch {target}!={open_records}")
    qrecords=queue.get("records")
    if not isinstance(qrecords,list):
        raise SystemExit(f"INTEGRITY ERROR: {b} queue records missing")
    pending=int(queue.get("pending_count",len(qrecords)) or 0)
    if pending != len(qrecords):
        raise SystemExit(f"INTEGRITY ERROR: {b} queue count mismatch {pending}!={len(qrecords)}")

amazon=load("amazon_target_check.json")
for city in ("Milan","Rome","Luxembourg","London"):
    row=(amazon.get("locations") or {}).get(city)
    if not isinstance(row,dict):
        raise SystemExit(f"INTEGRITY ERROR: Amazon {city} missing")
    if row.get("coverage") != "VERIFIED":
        raise SystemExit(f"INTEGRITY ERROR: Amazon {city} not VERIFIED")
    if int(row.get("inventory_count",-1)) != int(row.get("api_reported_hits_sum",-2)):
        raise SystemExit(f"INTEGRITY ERROR: Amazon {city} count mismatch")

audit=load("job_watch_audit.json")
if set((audit.get("batches") or {}).keys()) != {"JW1","JW2","JW3","JW4"}:
    raise SystemExit("INTEGRITY ERROR: audit missing batches")
health=load("job_watch_healthcheck.json")
if set((health.get("batches") or {}).keys()) != {"JW1","JW2","JW3","JW4"}:
    raise SystemExit("INTEGRITY ERROR: healthcheck missing batches")
if health.get("DAILY_COMPLETE") is True:
    incomplete=[b for b,row in (health.get("batches") or {}).items() if row.get("daily_complete") is not True]
    if incomplete:
        raise SystemExit(f"INTEGRITY ERROR: healthcheck claims DAILY_COMPLETE with incomplete batches: {incomplete}")
print("Job Watch integrity checks passed.")
