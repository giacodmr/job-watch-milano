#!/usr/bin/env python3
"""Initialize a fresh, fail-closed daily Job Watch manifest after collection.

The collector owns collection freshness, not semantic/autonomous completion. A
new snapshot must therefore replace any stale prior-day manifest with a current
PENDING manifest whose source timestamps exactly match JW1-JW4 and Amazon.
This removes misleading SOURCE_SNAPSHOT_MISMATCH errors without ever claiming
that semantic review, autonomous search, or priority review are complete.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ("JW1", "JW2", "JW3", "JW4")


def load(name: str):
    path = ROOT / name
    if not path.exists():
        raise SystemExit(f"RUN STATE INIT ERROR: missing {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def dump(name: str, payload) -> None:
    (ROOT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_id_from_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    current = {batch: load(f"current_jobs_{batch.lower()}.json") for batch in BATCHES}
    amazon = load("amazon_target_check.json")

    source_generated_at = {batch: current[batch].get("generated_at") for batch in BATCHES}
    missing = [batch for batch, value in source_generated_at.items() if not value]
    if missing:
        raise SystemExit(f"RUN STATE INIT ERROR: missing generated_at for {', '.join(missing)}")
    amazon_checked_at = amazon.get("checked_at")
    if not amazon_checked_at:
        raise SystemExit("RUN STATE INIT ERROR: amazon_target_check.checked_at missing")

    now = utc_now()
    state = {
        "version": "1.1",
        "run_id": run_id_from_now(),
        "run_phase": "COLLECTED_PENDING_SEMANTIC",
        "started_at": min(source_generated_at.values()),
        "completed_at": now,
        "source_generated_at": source_generated_at,
        "batches": {},
        "priority_checks": {
            "Amazon": False,
            "Mastercard": False,
        },
        "blocking_errors": [],
        "priority_snapshot_at": {
            "Amazon": amazon_checked_at,
        },
        "collection_complete": True,
        "semantic_manifest_status": "PENDING",
    }

    for batch in BATCHES:
        state["batches"][batch] = {
            "semantic_delta_complete": False,
            "autonomous_search_complete": False,
            "priority_check_complete": False,
            "autonomous_delta_count": 0,
            "autonomous_validated_count": 0,
            "errors": [],
            "autonomous_search_evidence": [],
            "priority_check_evidence": [],
        }

    dump("job_watch_run_state.json", state)
    print(
        "Initialized fresh pending Job Watch run state "
        f"run_id={state['run_id']} Amazon={amazon_checked_at}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
