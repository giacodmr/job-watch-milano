#!/usr/bin/env python3
"""Reject a falsely certified GPT run after semantic sync/audit."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ("JW1","JW2","JW3","JW4")

def load(name):
    with (ROOT/name).open("r",encoding="utf-8") as f:
        return json.load(f)

state=load("job_watch_run_state.json")
health=load("job_watch_healthcheck.json")
current={b:load(f"current_jobs_{b.lower()}.json") for b in BATCHES}
amazon=load("amazon_target_check.json")

source_match=all(
    (state.get("source_generated_at") or {}).get(b)==current[b].get("generated_at")
    for b in BATCHES
)
amazon_match=(state.get("priority_snapshot_at") or {}).get("Amazon")==amazon.get("checked_at")
batch_flags=all(
    ((state.get("batches") or {}).get(b) or {}).get("semantic_delta_complete") is True
    and ((state.get("batches") or {}).get(b) or {}).get("autonomous_search_complete") is True
    and ((state.get("batches") or {}).get(b) or {}).get("priority_check_complete") is True
    and not (((state.get("batches") or {}).get(b) or {}).get("errors") or [])
    for b in BATCHES
)
priority=(
    (state.get("priority_checks") or {}).get("Amazon") is True
    and (state.get("priority_checks") or {}).get("Mastercard") is True
)
asserts_current_complete=bool(
    state.get("run_id")
    and state.get("completed_at")
    and source_match
    and amazon_match
    and batch_flags
    and priority
    and not (state.get("blocking_errors") or [])
)

if asserts_current_complete and health.get("DAILY_COMPLETE") is not True:
    raise SystemExit(
        "CERTIFICATION ERROR: job_watch_run_state claims current end-to-end completion "
        "but job_watch_healthcheck.json DAILY_COMPLETE is not true"
    )

if asserts_current_complete:
    incomplete=[
        b for b,row in (health.get("batches") or {}).items()
        if row.get("daily_complete") is not True or row.get("gpt_run_certified") is not True
    ]
    if incomplete:
        raise SystemExit(f"CERTIFICATION ERROR: incomplete certified batches: {incomplete}")

print(
    "Certified-run validation passed"
    if asserts_current_complete
    else "No current COMPLETE certification asserted; strict completion check not applicable."
)
