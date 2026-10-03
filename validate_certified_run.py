#!/usr/bin/env python3
"""Reject any mismatch between the GPT manifest and persisted fail-closed healthcheck."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ("JW1", "JW2", "JW3", "JW4")


def load(name):
    with (ROOT / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def manifest_complete(state, current, amazon) -> bool:
    source_match = all(
        (state.get("source_generated_at") or {}).get(batch) == current[batch].get("generated_at")
        for batch in BATCHES
    )
    amazon_match = (state.get("priority_snapshot_at") or {}).get("Amazon") == amazon.get("checked_at")
    batch_flags = True
    for batch in BATCHES:
        row = ((state.get("batches") or {}).get(batch) or {})
        autonomous_evidence = row.get("autonomous_search_evidence") or []
        priority_evidence = row.get("priority_check_evidence") or []
        try:
            autonomous_delta_count = int(row.get("autonomous_delta_count", 0) or 0)
            autonomous_validated_count = int(row.get("autonomous_validated_count", 0) or 0)
        except (TypeError, ValueError):
            autonomous_delta_count = -1
            autonomous_validated_count = -2
        required_priority_evidence = batch in {"JW1", "JW2"}
        row_ok = bool(
            row.get("semantic_delta_complete") is True
            and row.get("autonomous_search_complete") is True
            and isinstance(autonomous_evidence, list)
            and len(autonomous_evidence) > 0
            and row.get("priority_check_complete") is True
            and ((not required_priority_evidence) or (isinstance(priority_evidence, list) and len(priority_evidence) > 0))
            and autonomous_delta_count >= 0
            and autonomous_delta_count == autonomous_validated_count
            and not (row.get("errors") or [])
        )
        batch_flags = batch_flags and row_ok
    priority = bool(
        (state.get("priority_checks") or {}).get("Amazon") is True
        and (state.get("priority_checks") or {}).get("Mastercard") is True
    )
    return bool(
        state.get("run_id")
        and state.get("completed_at")
        and source_match
        and amazon_match
        and batch_flags
        and priority
        and not (state.get("blocking_errors") or [])
    )


def main() -> int:
    state = load("job_watch_run_state.json")
    health = load("job_watch_healthcheck.json")
    current = {batch: load(f"current_jobs_{batch.lower()}.json") for batch in BATCHES}
    amazon = load("amazon_target_check.json")

    manifest_ok = manifest_complete(state, current, amazon)
    health_ok = health.get("DAILY_COMPLETE") is True

    if health_ok and not manifest_ok:
        raise SystemExit(
            "CERTIFICATION ERROR: healthcheck claims DAILY_COMPLETE but the manifest does not satisfy current fail-closed certification."
        )
    if health_ok and (health.get("blocking_errors") or []):
        raise SystemExit("CERTIFICATION ERROR: DAILY_COMPLETE healthcheck contains blocking_errors")
    if health_ok and (health.get("unresolved_user_decisions") or []):
        raise SystemExit("CERTIFICATION ERROR: DAILY_COMPLETE healthcheck contains unresolved TO_REVIEW/INTERESTED decisions")
    if health_ok and health.get("run_id") != state.get("run_id"):
        raise SystemExit("CERTIFICATION ERROR: healthcheck run_id does not match manifest run_id")

    if manifest_ok and not health_ok:
        raise SystemExit(
            "CERTIFICATION ERROR: job_watch_run_state claims current end-to-end completion "
            "but job_watch_healthcheck.json DAILY_COMPLETE is not true"
        )

    if health_ok:
        incomplete = [
            batch for batch, row in (health.get("batches") or {}).items()
            if row.get("daily_complete") is not True or row.get("gpt_run_certified") is not True
        ]
        if incomplete:
            raise SystemExit(f"CERTIFICATION ERROR: incomplete certified batches: {incomplete}")

    print("Certified-run validation passed" if health_ok else "No current COMPLETE certification asserted; fail-closed healthcheck is consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
