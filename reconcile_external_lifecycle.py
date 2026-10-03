#!/usr/bin/env python3
"""Reconcile persisted user decisions against current first-party inventories.

This module handles the narrow case where an ATS inventory/search is known to
omit a vacancy that the user explicitly kept. Historical detail pages are not
used to prove openness. For supported records we exhaust the current corporate
open-positions inventory and persist an explicit STILL_OPEN or CLOSED lifecycle
row in current_jobs_*.json, while leaving user_job_decisions.json untouched.
"""
from __future__ import annotations

import html as html_lib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from collector import OPEN_STATUSES, compact_job, get_html, metadata_fingerprint

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1", "jw2", "jw3", "jw4")
METHOD = "official_current_inventory_absence_or_presence"
MAX_CORPORATE_PAGES = 20
EURONEXT_JOB_RE = re.compile(r"/about/careers/job-offers/r([a-z0-9-]+)-", re.I)
PAGE_RE = re.compile(r"(?:[?&]|&amp;)page=(\d+)", re.I)


def load(name: str, default=None):
    path = ROOT / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dump(name: str, payload) -> None:
    (ROOT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def official_euronext_inventory(base_url: str) -> tuple[set[str], int]:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or (parsed.hostname or "").casefold().lstrip("www.") != "euronext.com":
        raise RuntimeError("Euronext lifecycle inventory must be an HTTPS euronext.com URL")

    def fetch(page: int) -> tuple[str, str]:
        sep = "&" if "?" in base_url else "?"
        return get_html(f"{base_url}{sep}page={page}")

    first_html, first_final = fetch(0)
    if (urlparse(first_final).hostname or "").casefold().lstrip("www.") != "euronext.com":
        raise RuntimeError("Euronext current inventory redirected off first-party host")
    decoded = html_lib.unescape(first_html)
    ids = {f"R{m.group(1).lstrip('rR')}" for m in EURONEXT_JOB_RE.finditer(decoded)}
    if not ids:
        raise RuntimeError("Euronext current inventory exposed zero parseable job IDs")

    page_numbers = {int(x) for x in PAGE_RE.findall(decoded)}
    max_page = max(page_numbers) if page_numbers else 0
    if max_page >= MAX_CORPORATE_PAGES:
        raise RuntimeError(f"Euronext pagination safety limit exceeded: max_page={max_page}")

    for page in range(1, max_page + 1):
        body, final_url = fetch(page)
        if (urlparse(final_url).hostname or "").casefold().lstrip("www.") != "euronext.com":
            raise RuntimeError(f"Euronext page {page} redirected off first-party host")
        ids.update(f"R{m.group(1).lstrip('rR')}" for m in EURONEXT_JOB_RE.finditer(html_lib.unescape(body)))

    if len(ids) < 20:
        raise RuntimeError(f"Euronext current inventory suspiciously small: {len(ids)} jobs")
    return ids, max_page + 1


def upsert_lifecycle(company_row: dict, registry_row: dict, status: str, evidence_url: str, pages_checked: int) -> bool:
    jobs = list(company_row.get("jobs") or [])
    source_id = str(registry_row["source_id"])
    canonical = str(registry_row.get("canonical_url") or "")
    candidate = compact_job(
        str(registry_row["company"]),
        source_id,
        title=registry_row.get("title"),
        location=registry_row.get("location"),
        canonical=canonical,
        apply_url=canonical if status in OPEN_STATUSES else None,
    )
    candidate["fingerprint"] = metadata_fingerprint(candidate)
    candidate["status"] = status
    candidate["lifecycle_reconciliation_source"] = "official_current_corporate_inventory"
    candidate["lifecycle_evidence_url"] = evidence_url
    candidate["lifecycle_pages_checked"] = pages_checked

    existing_index = next((i for i, job in enumerate(jobs) if str(job.get("source_id")) == source_id), None)
    if existing_index is not None:
        old = jobs[existing_index]
        # Never downgrade a role that the normal live collector already proved open.
        if old.get("status") in OPEN_STATUSES and status == "CLOSED":
            return False
        if all(old.get(k) == candidate.get(k) for k in ("status", "fingerprint", "canonical_url")):
            return False
        jobs[existing_index] = candidate
    else:
        jobs.append(candidate)

    company_row["jobs"] = jobs
    company_row["target_jobs_count"] = sum(1 for job in jobs if job.get("status") in OPEN_STATUSES)
    return True


def reconcile_batch(batch: str, records: dict) -> int:
    name = f"current_jobs_{batch}.json"
    current = load(name, {}) or {}
    companies = {row.get("company"): row for row in current.get("companies", []) if row.get("company")}
    changed = 0
    checks = []

    inventory_cache: dict[str, tuple[set[str], int]] = {}
    for key, row in records.items():
        if not isinstance(row, dict) or row.get("validation_method") != METHOD:
            continue
        company = str(row.get("company") or "")
        company_row = companies.get(company)
        if company_row is None:
            continue
        source_id = str(row.get("source_id") or "")
        if key != f"{company}::{source_id}" or not source_id:
            raise RuntimeError(f"External lifecycle registry key mismatch: {key}")
        inventory_url = str(row.get("current_inventory_url") or "")
        if company != "Euronext":
            raise RuntimeError(f"Unsupported external lifecycle company: {company}")
        if inventory_url not in inventory_cache:
            inventory_cache[inventory_url] = official_euronext_inventory(inventory_url)
        live_ids, pages = inventory_cache[inventory_url]
        status = "STILL_OPEN" if source_id in live_ids else "CLOSED"
        if upsert_lifecycle(company_row, row, status, inventory_url, pages):
            changed += 1
        checks.append({"job_key": key, "status": status, "pages_checked": pages, "inventory_size": len(live_ids)})
        print(f"External lifecycle reconciled: {key} -> {status} (inventory={len(live_ids)}, pages={pages})")

    if checks:
        all_jobs = [job for company in current.get("companies", []) for job in (company.get("jobs") or [])]
        summary = current.setdefault("summary", {})
        summary["target_jobs_open"] = sum(1 for job in all_jobs if job.get("status") in OPEN_STATUSES)
        for status in ("NEW", "STILL_OPEN", "UPDATED", "CLOSED", "UNKNOWN"):
            summary[status] = sum(1 for job in all_jobs if job.get("status") == status)
        current["external_lifecycle_reconciliation"] = {
            "method": METHOD,
            "checks": checks,
        }
        dump(name, current)
    return changed


def main() -> int:
    registry = (load("externally_validated_roles.json", {"records": {}}) or {}).get("records") or {}
    total = sum(reconcile_batch(batch, registry) for batch in BATCHES)
    print(f"External lifecycle reconciliation complete: changed={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
