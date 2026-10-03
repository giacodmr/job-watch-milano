#!/usr/bin/env python3
from __future__ import annotations

import json
from daily_worklist import action_reason
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
    from pipeline_state import stable_dump
    stable_dump(path.name,obj,path.parent)


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
    from pipeline_state import search_complete, priority_status, snapshot
    required = {'jw1':'Mastercard','jw2':'Amazon'}.get(batch)
    priority = priority_status(ROOT)
    token = snapshot(ROOT)
    search = search_complete(batch,ROOT)
    return {'run_id':token['run_id'], 'autonomous_search_complete':search,
            'priority_check_required':bool(required),
            'priority_check_status':priority.get(required) if required else 'NOT_APPLICABLE',
            'priority_check_complete':not required or priority[required] in {'VERIFIED','PARTIAL'},
            'source_snapshot_match':bool(current.get('generated_at')),
            'complete':search and (not required or priority[required] in {'VERIFIED','PARTIAL'})}


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

    actionable_delta = [r for r in open_records if action_reason(r)]
    actionable_pending = [r for r in actionable_delta if r.get("needs_analysis")]
    actionable_analyzed = [
        r for r in actionable_delta
        if r.get("analysis_status") == "ANALYZED" and not r.get("needs_analysis")
    ]
    actionable_reportable = [
        r for r in actionable_analyzed
        if (
            r.get("user_decision") in {"TO_REVIEW", "INTERESTED"}
            or r.get("applied_material_update") is True
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
    actionable_surfaced = [r for r in actionable_reportable if r.get("surfaced_at") and (
        r.get("surfaced_fingerprint") == r.get("fingerprint") or (not r.get("surfaced_fingerprint") and not (r.get("delta_pending") or r.get("applied_material_update")))
    )]

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
            "applied_material_updates_pending": sum(
                1 for r in open_records
                if r.get("user_decision") == "APPLIED"
                and r.get("applied_material_update") is True
                and r.get("needs_analysis")
            ),
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
        ),
        "full_semantic_complete": bool(
            base_inventory_reconciliation
            and state_reconciliation
            and analysis_complete
            and reporting_reconciliation
            and all_companies_attempted
        ),
        "run_complete": bool(
            base_inventory_reconciliation
            and state_reconciliation
            and actionable_delta_complete
            and actionable_reporting_reconciliation
            and all_companies_attempted
        ),
    }


def write_batch_metrics(batch):
    payload = read_json(ROOT/'job_watch_audit.json',{'version':'2.0','batches':{}})
    payload['version'] = '2.0'
    payload.pop('definition',None)
    payload.setdefault('batches',{})[batch.upper()] = audit_batch(batch,{})
    write_json(ROOT/'job_watch_audit.json',payload)
    return payload['batches'][batch.upper()]


def main() -> int:
    from pipeline_state import attempt
    for batch in BATCHES:
        attempt('metrics',lambda batch=batch:write_batch_metrics(batch),batch=batch,root=ROOT)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
