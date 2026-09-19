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


def job_key(company: str, source_id) -> str:
    return f"{company}::{source_id}"


def threshold_for(location: str | None) -> int:
    return 80 if "london" in (location or "").casefold() else 70


def sync_batch(batch: str) -> dict:
    current_path = ROOT / f"current_jobs_{batch}.json"
    state_path = ROOT / f"analysis_results_{batch}.json"
    current = read_json(current_path, {})
    old_state = read_json(state_path, {"records": {}})
    old_records = old_state.get("records") or {}

    current_all = {}
    current_open = {}
    for company in current.get("companies", []):
        company_name = company.get("company")
        for job in company.get("jobs", []):
            if not company_name or job.get("source_id") is None:
                continue
            key = job_key(company_name, job.get("source_id"))
            current_all[key] = (company_name, job)
            if job.get("status") in OPEN_STATUSES:
                current_open[key] = (company_name, job)

    records = {}
    reset = 0
    preserved = 0

    for key, (company_name, job) in current_open.items():
        fingerprint = job.get("fingerprint")
        old = old_records.get(key) or {}
        same = old.get("fingerprint") == fingerprint and old.get("analysis_status") == "ANALYZED"

        if same:
            rec = dict(old)
            rec.update({
                "company": company_name,
                "source_id": str(job.get("source_id")),
                "title": job.get("title"),
                "location": job.get("location"),
                "canonical_url": job.get("canonical_url") or job.get("url"),
                "apply_url": job.get("apply_url"),
                "fingerprint": fingerprint,
                "current_status": job.get("status"),
                "current_open": True,
                "threshold": threshold_for(job.get("location")),
                "needs_analysis": False,
                "last_seen_at": current.get("generated_at") or utc_now(),
            })
            preserved += 1
        else:
            rec = {
                "company": company_name,
                "source_id": str(job.get("source_id")),
                "title": job.get("title"),
                "location": job.get("location"),
                "canonical_url": job.get("canonical_url") or job.get("url"),
                "apply_url": job.get("apply_url"),
                "fingerprint": fingerprint,
                "current_status": job.get("status"),
                "current_open": True,
                "threshold": threshold_for(job.get("location")),
                "needs_analysis": True,
                "analysis_status": "PENDING",
                "fit_score": None,
                "experience_required": None,
                "salary": None,
                "salary_source": None,
                "reportable": None,
                "rationale": None,
                "analyzed_at": None,
                "surfaced_at": old.get("surfaced_at"),
                "surfaced_status": old.get("surfaced_status"),
                "first_seen_at": old.get("first_seen_at") or current.get("generated_at") or utc_now(),
                "last_seen_at": current.get("generated_at") or utc_now(),
            }
            reset += 1
        records[key] = rec

    # Keep historical rows for closed/unknown jobs so "ever surfaced" state is never lost.
    for key, old in old_records.items():
        if key in records:
            continue
        rec = dict(old)
        rec["current_open"] = False
        if key in current_all:
            rec["current_status"] = current_all[key][1].get("status")
            rec["last_seen_at"] = current.get("generated_at") or utc_now()
        records[key] = rec

    open_records = [r for r in records.values() if r.get("current_open")]
    pending = sum(1 for r in open_records if r.get("needs_analysis"))
    analyzed = sum(1 for r in open_records if r.get("analysis_status") == "ANALYZED" and not r.get("needs_analysis"))
    reportable = sum(1 for r in open_records if r.get("reportable") is True and not r.get("needs_analysis"))
    surfaced = sum(1 for r in open_records if r.get("reportable") is True and r.get("surfaced_at"))

    payload = {
        "version": "1.0",
        "batch": batch.upper(),
        "synced_at": utc_now(),
        "source_generated_at": current.get("generated_at"),
        "policy": {
            "milan_rome_threshold": 70,
            "london_threshold": 80,
            "no_top_n_cap": True,
            "semantic_analysis_required": True,
            "manager_senior_lead_auto_exclusion": False,
        },
        "summary": {
            "open_extracted": len(current_open),
            "open_state_records": len(open_records),
            "preserved_current_analysis": preserved,
            "reset_or_new_pending_analysis": reset,
            "analyzed_current": analyzed,
            "pending_analysis": pending,
            "reportable_current": reportable,
            "surfaced_current": surfaced,
        },
        "records": records,
    }
    write_json(state_path, payload)
    return payload


def main() -> int:
    for batch in BATCHES:
        p = sync_batch(batch)
        s = p["summary"]
        print(
            f"{batch.upper()} open={s['open_extracted']} analyzed={s['analyzed_current']} "
            f"pending={s['pending_analysis']} reportable={s['reportable_current']} surfaced={s['surfaced_current']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
