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


def audit_batch(batch: str) -> dict:
    current = read_json(ROOT / f"current_jobs_{batch}.json", {})
    state = read_json(ROOT / f"analysis_results_{batch}.json", {"records": {}})

    extracted_open = 0
    for company in current.get("companies", []):
        for job in company.get("jobs", []):
            if job.get("status") in OPEN_STATUSES:
                extracted_open += 1

    records = list((state.get("records") or {}).values())
    open_records = [r for r in records if r.get("current_open")]
    analyzed = [
        r for r in open_records
        if r.get("analysis_status") == "ANALYZED" and not r.get("needs_analysis")
    ]
    pending = [r for r in open_records if r.get("needs_analysis")]
    reportable = [
        r for r in analyzed
        if r.get("reportable") is True and (r.get("fit_score") or 0) >= (r.get("threshold") or 0)
    ]
    surfaced = [r for r in reportable if r.get("surfaced_at")]

    summary_target = (current.get("summary") or {}).get("target_jobs_open")
    inventory_reconciliation = summary_target == extracted_open
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

    return {
        "batch": batch.upper(),
        "source_generated_at": current.get("generated_at"),
        "company_ats_coverage": coverage,
        "vacancy_analysis_coverage": {
            "extracted_open": extracted_open,
            "state_records_open": len(open_records),
            "analyzed_current": len(analyzed),
            "pending_analysis": len(pending),
            "analysis_pct": round((len(analyzed) / extracted_open) * 100, 2) if extracted_open else 100.0,
            "reportable_above_threshold": len(reportable),
            "surfaced_ever_current": len(surfaced),
        },
        "checks": {
            "inventory_reconciliation": inventory_reconciliation,
            "state_reconciliation": state_reconciliation,
            "analysis_complete": analysis_complete,
            "reporting_reconciliation": reporting_reconciliation,
        },
        "run_complete": bool(
            inventory_reconciliation
            and state_reconciliation
            and analysis_complete
            and reporting_reconciliation
        ),
    }


def main() -> int:
    batches = {batch.upper(): audit_batch(batch) for batch in BATCHES}
    payload = {
        "version": "1.0",
        "generated_at": utc_now(),
        "definition": (
            "Inventory completeness is separate from analysis completeness. "
            "A run is complete only when extracted open vacancies reconcile to the analysis state, "
            "all are analyzed, and every currently reportable above-threshold vacancy has been surfaced."
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
            f"reportable/surfaced={v['reportable_above_threshold']}/{v['surfaced_ever_current']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
