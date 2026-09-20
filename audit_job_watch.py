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


def audit_batch(batch: str) -> dict:
    current = read_json(ROOT / f"current_jobs_{batch}.json", {})
    state = read_json(ROOT / f"analysis_results_{batch}.json", {"records": {}})
    queue = read_json(ROOT / f"semantic_queue_{batch}.json", {"records": []})

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
        and (
            r.get("priority_company") is True
            or (r.get("fit_score") or 0) >= (r.get("threshold") or 0)
        )
    ]
    surfaced = [r for r in reportable if r.get("surfaced_at")]

    summary_target = (current.get("summary") or {}).get("target_jobs_open")
    base_inventory_reconciliation = summary_target == len(base_keys)
    state_reconciliation = extracted_open == len(open_records)
    analysis_complete = len(analyzed) == extracted_open and not pending
    reporting_reconciliation = len(reportable) == len(surfaced) if analysis_complete else False

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
            "reportable_above_threshold_or_priority": len(reportable),
            "surfaced_ever_current": len(surfaced),
        },
        "checks": {
            "inventory_reconciliation": base_inventory_reconciliation,
            "priority_overlay_reconciliation": extracted_open == len(open_records),
            "state_reconciliation": state_reconciliation,
            "analysis_complete": analysis_complete,
            "reporting_reconciliation": reporting_reconciliation,
            "all_companies_attempted": all_companies_attempted,
            "no_failed_company_checks": not unresolved_attempts,
            "company_count": total_companies,
        },
        "run_complete": bool(
            base_inventory_reconciliation
            and state_reconciliation
            and analysis_complete
            and reporting_reconciliation
            and all_companies_attempted
            and not unresolved_attempts
        ),
    }


def main() -> int:
    batches = {batch.upper(): audit_batch(batch) for batch in BATCHES}
    payload = {
        "version": "1.1",
        "generated_at": utc_now(),
        "definition": (
            "Inventory completeness is separate from semantic-analysis completeness. "
            "JW2 includes the Amazon priority overlay (Milan/Rome/Luxembourg/London) in analysis reconciliation. "
            "A run is complete only when official inventory/state reconcile, every pending role is decided, "
            "and every currently reportable role has surfaced history."
        ),
        "batches": batches,
    }
    write_json(ROOT / "job_watch_audit.json", payload)

    for name, row in batches.items():
        v = row["vacancy_analysis_coverage"]
        c = row["company_ats_coverage"]
        print(
            f"{name} complete={row['run_complete']} | "
            f"ATS V/P/F/NC={c['VERIFIED']}/{c['PARTIAL']}/{c['FAILED']}/{c['NOT_CHECKED']} | "
            f"analysis={v['analyzed_current']}/{v['extracted_open']} ({v['analysis_pct']}%) | "
            f"semantic={v['semantic_analyzed']} pending={v['pending_analysis']} | "
            f"reportable/surfaced={v['reportable_above_threshold_or_priority']}/{v['surfaced_ever_current']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
