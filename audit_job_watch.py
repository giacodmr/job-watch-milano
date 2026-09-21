#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1", "jw2", "jw3", "jw4")
OPEN_STATUSES = {"NEW", "STILL_OPEN", "UPDATED"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def canonical_key(url: str | None) -> str | None:
    if not url:
        return None
    return str(url).split("#", 1)[0].rstrip("/").casefold()


def iso_at_or_after(value: str | None, cutoff: str | None) -> bool:
    if not value or not cutoff:
        return False
    try:
        left = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        right = datetime.fromisoformat(str(cutoff).replace("Z", "+00:00"))
        return left >= right
    except (TypeError, ValueError):
        return False


def extracted_open_keys(current: dict) -> set[str]:
    keys = set()
    for company in current.get("companies", []):
        name = company.get("company")
        for job in company.get("jobs", []):
            if job.get("status") not in OPEN_STATUSES:
                continue
            c = canonical_key(job.get("canonical_url") or job.get("url") or job.get("apply_url"))
            if c:
                keys.add(f"url::{c}")
            elif name and job.get("source_id") is not None:
                keys.add(f"id::{name}::{job.get('source_id')}")
    return keys


def priority_overlay_keys(batch: str, existing: set[str]) -> set[str]:
    extra = set()
    if batch == "jw2":
        data = read_json(ROOT / "amazon_target_check.json", {})
        for job in data.get("target_jobs", []):
            if job.get("status") not in OPEN_STATUSES:
                continue
            c = canonical_key(job.get("apply_url"))
            key = f"url::{c}" if c else f"id::Amazon::{job.get('job_id')}"
            if key not in existing:
                extra.add(key)
    return extra



def run_certification(batch: str, current: dict, run_state: dict) -> dict:
    name = batch.upper()
    row = ((run_state.get("batches") or {}).get(name) or {})
    source_match = ((run_state.get("source_generated_at") or {}).get(name) == current.get("generated_at"))
    autonomous_complete = row.get("autonomous_search_complete") is True
    autonomous_evidence = row.get("autonomous_search_evidence") or []
    autonomous_evidence_ok = isinstance(autonomous_evidence, list) and len(autonomous_evidence) > 0
    semantic_declared = row.get("semantic_delta_complete") is True
    priority_required = batch in {"jw1", "jw2"}
    priority_name = "Mastercard" if batch == "jw1" else "Amazon" if batch == "jw2" else None
    priority_row_ok = row.get("priority_check_complete") is True
    priority_evidence = row.get("priority_check_evidence") or []
    priority_evidence_ok = (not priority_required) or (isinstance(priority_evidence, list) and len(priority_evidence) > 0)
    priority_global_ok = True if not priority_required else (run_state.get("priority_checks") or {}).get(priority_name) is True
    if batch == "jw2":
        amazon = read_json(ROOT / "amazon_target_check.json", {})
        priority_snapshot_match = (
            (run_state.get("priority_snapshot_at") or {}).get("Amazon") == amazon.get("checked_at")
        )
    else:
        priority_snapshot_match = True
    try:
        autonomous_delta_count = int(row.get("autonomous_delta_count", 0) or 0)
        autonomous_validated_count = int(row.get("autonomous_validated_count", 0) or 0)
    except (TypeError, ValueError):
        autonomous_delta_count = -1
        autonomous_validated_count = -2
    autonomous_reconciled = autonomous_delta_count >= 0 and autonomous_delta_count == autonomous_validated_count
    batch_errors = row.get("errors") or []
    global_errors = run_state.get("blocking_errors") or []
    identity_ok = bool(run_state.get("run_id") and run_state.get("completed_at"))
    complete = bool(
        identity_ok
        and source_match
        and semantic_declared
        and autonomous_complete
        and autonomous_evidence_ok
        and autonomous_reconciled
        and priority_row_ok
        and priority_evidence_ok
        and priority_global_ok
        and priority_snapshot_match
        and not batch_errors
    )
    return {
        "run_id": run_state.get("run_id"),
        "manifest_persisted": bool(run_state),
        "identity_complete": identity_ok,
        "source_snapshot_match": source_match,
        "semantic_delta_declared_complete": semantic_declared,
        "autonomous_search_complete": autonomous_complete,
        "autonomous_search_evidence_present": autonomous_evidence_ok,
        "autonomous_delta_count": autonomous_delta_count,
        "autonomous_validated_count": autonomous_validated_count,
        "autonomous_delta_reconciled": autonomous_reconciled,
        "priority_check_required": priority_required,
        "priority_check_evidence_present": priority_evidence_ok,
        "priority_check_complete": priority_row_ok and priority_global_ok,
        "priority_snapshot_match": priority_snapshot_match,
        "batch_errors": batch_errors,
        "global_blocking_errors": global_errors,
        "complete": complete,
    }

def audit_batch(batch: str, run_state: dict) -> dict:
    current = read_json(ROOT / f"current_jobs_{batch}.json", {})
    mapping = read_json(ROOT / f"ats_mapping_{batch}.json", {"companies": []})
    state = read_json(ROOT / f"analysis_results_{batch}.json", {"records": {}})
    queue = read_json(ROOT / f"semantic_queue_{batch}.json", {"records": []})
    user_decisions = (read_json(ROOT / "user_job_decisions.json", {"records": {}}).get("records") or {})
    rules = read_json(ROOT / "job_watch_rules.json", {})
    never_disappear_since = ((rules.get("user_decision_policy") or {}).get("never_disappear_since"))
    certification = run_certification(batch, current, run_state)

    base_keys = extracted_open_keys(current)
    overlay_keys = priority_overlay_keys(batch, base_keys)
    extracted_open = len(base_keys) + len(overlay_keys)

    records = list((state.get("records") or {}).values())
    open_records = [r for r in records if r.get("current_open")]
    analyzed = [
        r for r in open_records
        if r.get("analysis_status") == "ANALYZED" and not r.get("needs_analysis")
    ]
    pending = [r for r in open_records if r.get("needs_analysis")]

    # Priority-company jobs have their own exhaustive reporting rule: when the
    # semantic decision marks them reportable they are included regardless of
    # the normal Milan/Rome/London score threshold. Standard roles still need
    # to clear the batch threshold.
    reportable = [
        r for r in analyzed
        if r.get("reportable") is True
        and r.get("user_decision") not in {"APPLIED", "NOT_INTERESTED"}
        and (
            r.get("priority_company") is True
            or (r.get("fit_score") or 0) >= (r.get("threshold") or 0)
        )
    ]
    surfaced = [r for r in reportable if r.get("surfaced_at")]

    summary_target = (current.get("summary") or {}).get("target_jobs_open")
    base_inventory_reconciliation = summary_target == len(base_keys)
    state_reconciliation = extracted_open == len(open_records)
    # Two different completeness concepts:
    # - DAILY_COMPLETE: today's actionable delta is decided and any reportable
    #   delta roles have surfaced history. Historical STILL_OPEN backlog does
    #   not block a daily run.
    # - FULL_SEMANTIC_COMPLETE: every currently open record is semantically
    #   decided and every reportable record is surfaced.
    # Daily actionable work includes normal NEW/UPDATED plus any explicit user-facing
    # review item. This prevents an interesting vacancy from disappearing merely
    # because it rolled from NEW to STILL_OPEN before semantic review/surfacing.
    actionable_delta = [
        r for r in open_records
        if (
            r.get("user_decision") not in {"APPLIED", "NOT_INTERESTED"}
            and (
                r.get("current_status") in {"NEW", "UPDATED"}
                or r.get("user_decision") in {"TO_REVIEW", "INTERESTED"}
                or (
                    r.get("needs_analysis")
                    and not r.get("surfaced_at")
                    and iso_at_or_after(r.get("first_seen_at"), never_disappear_since)
                )
            )
        )
    ]
    actionable_pending = [r for r in actionable_delta if r.get("needs_analysis")]
    actionable_analyzed = [
        r for r in actionable_delta
        if r.get("analysis_status") == "ANALYZED" and not r.get("needs_analysis")
    ]
    actionable_reportable = [
        r for r in actionable_analyzed
        if (
            r.get("user_decision") in {"TO_REVIEW", "INTERESTED"}
            or (
                r.get("reportable") is True
                and r.get("user_decision") not in {"APPLIED", "NOT_INTERESTED"}
                and (
                    r.get("priority_company") is True
                    or (r.get("fit_score") or 0) >= (r.get("threshold") or 0)
                )
            )
        )
    ]
    actionable_surfaced = [r for r in actionable_reportable if r.get("surfaced_at")]

    analysis_complete = len(analyzed) == extracted_open and not pending
    reporting_reconciliation = len(reportable) == len(surfaced) if analysis_complete else False
    actionable_delta_complete = not actionable_pending
    actionable_reporting_reconciliation = (
        len(actionable_reportable) == len(actionable_surfaced)
        if actionable_delta_complete else False
    )

    company_summary = current.get("summary") or {}
    coverage = {
        "VERIFIED": int(company_summary.get("VERIFIED", 0) or 0),
        "PARTIAL": int(company_summary.get("PARTIAL", 0) or 0),
        "FAILED": int(company_summary.get("FAILED", 0) or 0),
        "NOT_CHECKED": int(company_summary.get("NOT_CHECKED", 0) or 0),
    }

    total_companies = sum(coverage.values())
    all_companies_attempted = coverage["NOT_CHECKED"] == 0
    unresolved_attempts = coverage["FAILED"] > 0

    mapping_by_company = {
        row.get("company"): row
        for row in (mapping.get("companies") or [])
        if row.get("company")
    }
    partial_backlog = []
    for company in current.get("companies", []):
        if company.get("coverage") != "PARTIAL":
            continue
        mapped = mapping_by_company.get(company.get("company")) or {}
        partial_backlog.append({
            "company": company.get("company"),
            "mapping_level": (mapped.get("verification") or {}).get("level"),
            "ats_family": company.get("ats_family"),
            "collector": company.get("collector"),
            "reason": company.get("reason"),
            "source_url": company.get("source_url"),
            "priority_full_mapping": (mapped.get("verification") or {}).get("level") == "FULL",
        })
    partial_backlog.sort(
        key=lambda row: (
            0 if row.get("priority_full_mapping") else 1,
            (row.get("company") or "").casefold(),
        )
    )

    return {
        "batch": batch.upper(),
        "source_generated_at": current.get("generated_at"),
        "company_ats_coverage": coverage,
        "vacancy_analysis_coverage": {
            "base_extracted_open": len(base_keys),
            "priority_overlay_open": len(overlay_keys),
            "extracted_open": extracted_open,
            "state_records_open": len(open_records),
            "analyzed_current": len(analyzed),
            "hard_rule_analyzed": sum(1 for r in analyzed if r.get("analysis_method") == "hard_rule_title"),
            "semantic_analyzed": sum(1 for r in analyzed if r.get("analysis_method") != "hard_rule_title"),
            "pending_analysis": len(pending),
            "queue_pending": int(queue.get("pending_count", len(queue.get("records") or [])) or 0),
            "analysis_pct": round((len(analyzed) / extracted_open) * 100, 2) if extracted_open else 100.0,
            "actionable_delta_open": len(actionable_delta),
            "actionable_delta_analyzed": len(actionable_analyzed),
            "actionable_delta_pending": len(actionable_pending),
            "historical_backlog_remaining": max(0, len(pending) - len(actionable_pending)),
            "explicit_user_review_open": sum(1 for r in open_records if r.get("user_decision") in {"TO_REVIEW", "INTERESTED"}),
            "applied_open": sum(1 for r in open_records if r.get("user_decision") == "APPLIED"),
            "not_interested_open": sum(1 for r in open_records if r.get("user_decision") == "NOT_INTERESTED"),
            "guarded_never_reviewed_open": sum(
                1 for r in open_records
                if r.get("needs_analysis")
                and not r.get("surfaced_at")
                and iso_at_or_after(r.get("first_seen_at"), never_disappear_since)
            ),
            "never_reviewed_open": sum(1 for r in open_records if r.get("analysis_status") != "ANALYZED"),
            "never_surfaced_pending": sum(1 for r in pending if not r.get("surfaced_at")),
            "reportable_above_threshold_or_priority": len(reportable),
            "surfaced_ever_current": len(surfaced),
            "actionable_reportable": len(actionable_reportable),
            "actionable_surfaced": len(actionable_surfaced),
        },
        "partial_remediation": {
            "count": len(partial_backlog),
            "full_mapping_but_partial": sum(1 for row in partial_backlog if row.get("priority_full_mapping")),
            "companies": partial_backlog,
        },
        "checks": {
            "inventory_reconciliation": base_inventory_reconciliation,
            "priority_overlay_reconciliation": extracted_open == len(open_records),
            "state_reconciliation": state_reconciliation,
            "analysis_complete": analysis_complete,
            "reporting_reconciliation": reporting_reconciliation,
            "actionable_delta_complete": actionable_delta_complete,
            "actionable_reporting_reconciliation": actionable_reporting_reconciliation,
            "all_companies_attempted": all_companies_attempted,
            "no_failed_company_checks": not unresolved_attempts,
            "company_count": total_companies,
            "gpt_run_certified": certification["complete"],
        },
        "run_certification": certification,
        "daily_complete": bool(
            base_inventory_reconciliation
            and state_reconciliation
            and actionable_delta_complete
            and actionable_reporting_reconciliation
            and all_companies_attempted
            and not unresolved_attempts
            and certification["complete"]
        ),
        "full_semantic_complete": bool(
            base_inventory_reconciliation
            and state_reconciliation
            and analysis_complete
            and reporting_reconciliation
            and all_companies_attempted
            and not unresolved_attempts
        ),
        # Backward-compatible alias: operational run completion now means
        # DAILY_COMPLETE, not historical backlog exhaustion.
        "run_complete": bool(
            base_inventory_reconciliation
            and state_reconciliation
            and actionable_delta_complete
            and actionable_reporting_reconciliation
            and all_companies_attempted
            and not unresolved_attempts
            and certification["complete"]
        ),
    }


def main() -> int:
    run_state = read_json(ROOT / "job_watch_run_state.json", {})
    batches = {batch.upper(): audit_batch(batch, run_state) for batch in BATCHES}
    payload = {
        "version": "1.4",
        "generated_at": utc_now(),
        "definition": (
            "Inventory completeness is separate from semantic-analysis completeness. "
            "JW2 includes the Amazon priority inventory in analysis reconciliation. "
            "DAILY_COMPLETE requires official inventory/state reconciliation, complete semantic handling, "
            "surfaced history, a current GPT run certification, mandatory autonomous search, and priority-company "
            "checks for today's actionable delta. Explicit TO_REVIEW/INTERESTED vacancies remain actionable even after becoming STILL_OPEN. Historical STILL_OPEN backlog "
            "is reported separately and does not block the daily run. FULL_SEMANTIC_COMPLETE additionally "
            "requires zero pending historical records and full reporting reconciliation."
        ),
        "batches": batches,
    }
    write_json(ROOT / "job_watch_audit.json", payload)

    overall = all(row.get("daily_complete") is True for row in batches.values())
    health = {
        "version": "1.0",
        "generated_at": payload["generated_at"],
        "run_id": run_state.get("run_id"),
        "DAILY_COMPLETE": overall,
        "FULL_SEMANTIC_COMPLETE": all(row.get("full_semantic_complete") is True for row in batches.values()),
        "priority_checks": run_state.get("priority_checks") or {},
        "batches": {
            name: {
                "source_generated_at": row.get("source_generated_at"),
                "daily_complete": row.get("daily_complete"),
                "full_semantic_complete": row.get("full_semantic_complete"),
                "gpt_run_certified": (row.get("run_certification") or {}).get("complete"),
                "actionable_delta_pending": (row.get("vacancy_analysis_coverage") or {}).get("actionable_delta_pending"),
                "historical_backlog_remaining": (row.get("vacancy_analysis_coverage") or {}).get("historical_backlog_remaining"),
                "failed": (row.get("company_ats_coverage") or {}).get("FAILED"),
                "not_checked": (row.get("company_ats_coverage") or {}).get("NOT_CHECKED"),
            }
            for name, row in batches.items()
        },
        "blocking_errors": list(run_state.get("blocking_errors") or []) + [
            f"{name}: end-to-end run incomplete"
            for name, row in batches.items()
            if row.get("daily_complete") is not True
        ],
    }
    write_json(ROOT / "job_watch_healthcheck.json", health)

    for name, row in batches.items():
        v = row["vacancy_analysis_coverage"]
        c = row["company_ats_coverage"]
        print(
            f"{name} DAILY_COMPLETE={row['daily_complete']} FULL_SEMANTIC_COMPLETE={row['full_semantic_complete']} | "
            f"ATS V/P/F/NC={c['VERIFIED']}/{c['PARTIAL']}/{c['FAILED']}/{c['NOT_CHECKED']} | "
            f"delta analyzed/pending={v['actionable_delta_analyzed']}/{v['actionable_delta_pending']} | "
            f"historical_backlog={v['historical_backlog_remaining']} | "
            f"reportable/surfaced={v['actionable_reportable']}/{v['actionable_surfaced']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
