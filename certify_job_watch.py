#!/usr/bin/env python3
"""Fail-closed final certification layer for persisted Job Watch health."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ("JW1", "JW2", "JW3", "JW4")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(name: str, default=None):
    path = ROOT / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dump(name: str, payload) -> None:
    old = load(name, {})
    if {k: v for k, v in old.items() if k != "generated_at"} == {k: v for k, v in payload.items() if k != "generated_at"}:
        return
    (ROOT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_error(errors: list[dict], code: str, **fields) -> None:
    errors.append({"code": code, **fields})


def main() -> int:
    state = load("job_watch_run_state.json", {}) or {}
    audit = load("job_watch_audit.json", {}) or {}
    amazon = load("amazon_target_check.json", {}) or {}
    decisions = (load("user_job_decisions.json", {"records": {}}) or {}).get("records") or {}
    current = {b: load(f"current_jobs_{b.lower()}.json", {}) or {} for b in BATCHES}
    analysis = {b: load(f"analysis_results_{b.lower()}.json", {"records": {}}) or {} for b in BATCHES}

    errors: list[dict] = []
    for message in state.get("blocking_errors") or []:
        add_error(errors, "MANIFEST_BLOCKING_ERROR", message=str(message))

    for batch in BATCHES:
        expected = current[batch].get("generated_at")
        actual = (state.get("source_generated_at") or {}).get(batch)
        if expected != actual:
            add_error(errors, "SOURCE_SNAPSHOT_MISMATCH", batch=batch, expected=expected, actual=actual)

    expected_amazon = amazon.get("checked_at")
    actual_amazon = (state.get("priority_snapshot_at") or {}).get("Amazon")
    if expected_amazon != actual_amazon:
        add_error(errors, "AMAZON_PRIORITY_SNAPSHOT_MISMATCH", expected=expected_amazon, actual=actual_amazon)

    audit_batches = audit.get("batches") or {}
    for batch in BATCHES:
        row = audit_batches.get(batch) or {}
        if row.get("daily_complete") is not True:
            add_error(
                errors,
                "BATCH_DAILY_INCOMPLETE",
                batch=batch,
                actionable_delta_pending=((row.get("vacancy_analysis_coverage") or {}).get("actionable_delta_pending")),
            )
        cert = row.get("run_certification") or {}
        if cert.get("global_blocking_errors"):
            add_error(errors, "BATCH_CERTIFICATION_HAS_GLOBAL_ERRORS", batch=batch, errors=cert.get("global_blocking_errors"))

    # A persisted user decision is reconciled when either analysis state knows
    # the vacancy or a current snapshot carries an explicit lifecycle row. This
    # matters for TO_REVIEW/INTERESTED roles that close before ever entering the
    # semantic state: CLOSED is a resolved lifecycle, not a missing vacancy.
    all_state_keys = set()
    for batch in BATCHES:
        all_state_keys.update(((analysis[batch].get("records") or {}).keys()))

    lifecycle_status: dict[str, str] = {}
    for batch in BATCHES:
        for company in current[batch].get("companies", []) or []:
            company_name = company.get("company")
            if not company_name:
                continue
            for job in company.get("jobs", []) or []:
                if job.get("source_id") is None:
                    continue
                lifecycle_status[f"{company_name}::{job.get('source_id')}"] = str(job.get("status") or "UNKNOWN")

    active_decision_keys = {
        key for key, row in decisions.items()
        if (row or {}).get("decision") in {"TO_REVIEW", "INTERESTED"}
    }
    unresolved_user_decisions = sorted(
        key for key in active_decision_keys
        if key not in all_state_keys and key not in lifecycle_status
    )
    closed_user_decisions = sorted(
        key for key in active_decision_keys
        if lifecycle_status.get(key) == "CLOSED"
    )
    for key in unresolved_user_decisions:
        add_error(errors, "ACTIVE_USER_DECISION_NOT_RECONCILED", job_key=key)

    coverage = {}
    for batch in BATCHES:
        row = audit_batches.get(batch) or {}
        counts = row.get("company_ats_coverage") or {}
        verified = int(counts.get("VERIFIED", 0) or 0)
        partial = int(counts.get("PARTIAL", 0) or 0)
        failed = int(counts.get("FAILED", 0) or 0)
        not_checked = int(counts.get("NOT_CHECKED", 0) or 0)
        total = verified + partial + failed + not_checked
        coverage[batch] = {
            "VERIFIED": verified,
            "PARTIAL": partial,
            "FAILED": failed,
            "NOT_CHECKED": not_checked,
            "verified_pct": round(verified / total * 100, 2) if total else 100.0,
        }

    batch_health = {}
    all_batches_complete = True
    all_full_complete = True
    for batch in BATCHES:
        row = audit_batches.get(batch) or {}
        cert = row.get("run_certification") or {}
        vac = row.get("vacancy_analysis_coverage") or {}
        cov = row.get("company_ats_coverage") or {}
        daily = row.get("daily_complete") is True
        full = row.get("full_semantic_complete") is True
        all_batches_complete = all_batches_complete and daily
        all_full_complete = all_full_complete and full
        batch_health[batch] = {
            "source_generated_at": row.get("source_generated_at"),
            "daily_complete": daily,
            "full_semantic_complete": full,
            "gpt_run_certified": cert.get("complete") is True,
            "actionable_delta_pending": vac.get("actionable_delta_pending"),
            "historical_backlog_remaining": vac.get("historical_backlog_remaining"),
            "applied_material_updates_pending": sum(
                1 for rec in (analysis[batch].get("records") or {}).values()
                if rec.get("current_open") and rec.get("applied_material_update") and rec.get("needs_analysis")
            ),
            "failed": cov.get("FAILED"),
            "not_checked": cov.get("NOT_CHECKED"),
        }

    daily_complete = bool(all_batches_complete and not errors)
    full_complete = bool(all_full_complete and not errors)
    compact_errors = []
    for item in errors:
        code = item.get("code")
        if item.get("batch"):
            compact_errors.append(f"{item['batch']}: {code}")
        elif item.get("job_key"):
            compact_errors.append(f"{code}: {item['job_key']}")
        elif item.get("message"):
            compact_errors.append(f"{code}: {item['message']}")
        else:
            compact_errors.append(str(code))

    hardened = {
        "version": "1.2",
        "generated_at": now(),
        "run_id": state.get("run_id"),
        "DAILY_COMPLETE": daily_complete,
        "FULL_SEMANTIC_COMPLETE": full_complete,
        "priority_checks": state.get("priority_checks") or {},
        "batches": batch_health,
        "coverage": coverage,
        "unresolved_user_decisions": unresolved_user_decisions,
        "closed_user_decisions": closed_user_decisions,
        "blocking_errors": compact_errors,
        "blocking_error_details": errors,
        "certification_mode": "FAIL_CLOSED",
    }
    dump("job_watch_healthcheck.json", hardened)
    print(
        f"Hardened healthcheck DAILY_COMPLETE={daily_complete} "
        f"FULL_SEMANTIC_COMPLETE={full_complete} blocking_errors={len(errors)} "
        f"closed_user_decisions={len(closed_user_decisions)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
