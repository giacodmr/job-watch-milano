#!/usr/bin/env python3
"""Recover target-geography Workday roles whose locationsText is too coarse.

Some official Workday inventories expose a country-only locationsText (for
example `Italy`) while the canonical externalPath still contains an explicit,
official location segment such as `/job/Milan/...`. The base collector filters
on locationsText, so those roles can otherwise disappear despite remaining
open on the official ATS.

This reconciliation is intentionally conservative: it only trusts explicit
Workday path segments for Milan/Milano, Rome/Roma, or UK London and currently
runs only for companies listed in PATH_LOCATION_COMPANIES. It enumerates the
same official Workday CXS inventory to exhaustion and never upgrades coverage
without exact total reconciliation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from collector import (
    MAX_PAGES,
    OPEN_STATUSES,
    compact_job,
    metadata_fingerprint,
    post_json,
    workday_config,
    workday_source_id,
)

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1", "jw2", "jw3", "jw4")
PATH_LOCATION_COMPANIES = {"Euronext"}


def read_json(name: str, default=None):
    path = ROOT / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(name: str, payload) -> None:
    (ROOT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_path_location(external_path: str | None) -> str | None:
    if not external_path:
        return None
    parts = [unquote(x) for x in urlparse(external_path).path.split("/") if x]
    try:
        idx = next(i for i, part in enumerate(parts) if part.casefold() == "job")
        slug = parts[idx + 1]
    except (StopIteration, IndexError):
        return None

    normalized = re.sub(r"[-_]+", " ", slug).strip()
    folded = normalized.casefold()

    if folded in {"milan", "milano"}:
        return normalized
    if re.match(r"^(milan|milano)\b", normalized, re.I) and re.search(r"\b(italy|it)\b", normalized, re.I):
        return normalized
    if folded in {"rome", "roma"}:
        return normalized
    if re.match(r"^(rome|roma)\b", normalized, re.I) and re.search(r"\b(italy|it)\b", normalized, re.I):
        return normalized
    if folded == "london":
        return normalized
    if re.match(r"^london\b", normalized, re.I) and re.search(r"\b(england|uk|gb|united kingdom)\b", normalized, re.I):
        return normalized
    return None


def enumerate_workday(company: dict) -> tuple[list[dict], str, str, str]:
    host, tenant, site = workday_config(company)
    search_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    referer = f"https://{host}/{site}"
    limit = 20
    offset = 0
    total = None
    rows: list[dict] = []

    for _ in range(MAX_PAGES):
        data = post_json(
            search_url,
            {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""},
            headers={"Accept": "application/json", "Referer": referer, "Origin": f"https://{host}"},
        )
        page = data.get("jobPostings")
        if not isinstance(page, list):
            raise RuntimeError("Unexpected Workday CXS response during path reconciliation")
        if total is None:
            total = int(data.get("total", len(page)))
        rows.extend(page)
        if len(rows) >= total:
            break
        if not page:
            raise RuntimeError(f"Workday path reconciliation stopped early: retrieved={len(rows)}, total={total}")
        offset += len(page)
    else:
        raise RuntimeError("Workday path reconciliation pagination safety limit")

    if total is None or len(rows) != total:
        raise RuntimeError(f"Workday path reconciliation mismatch: retrieved={len(rows)}, total={total}")
    return rows, host, site, search_url


def candidate_from_raw(company_name: str, raw: dict, host: str, site: str) -> dict | None:
    external_path = str(raw.get("externalPath") or "").strip()
    path_location = safe_path_location(external_path)
    if not path_location:
        return None

    raw_location = str(raw.get("locationsText") or "").strip()
    location = path_location if not raw_location else f"{path_location} | {raw_location}"
    canonical = f"https://{host}/{site}{external_path}"
    bullet_fields = raw.get("bulletFields") or []
    employment = None
    if isinstance(bullet_fields, list):
        for value in bullet_fields:
            text = str(value or "").strip()
            if text and re.search(r"\b(full[ -]?time|part[ -]?time|intern(?:ship)?|temporary|contract)\b", text, re.I):
                employment = text
                break

    job = compact_job(
        company_name,
        workday_source_id(raw, external_path),
        title=raw.get("title"),
        location=location,
        employment_type=employment,
        published_at=raw.get("postedOn"),
        updated_at=raw.get("updatedOn"),
        canonical=canonical,
        apply_url=canonical,
    )
    job["fingerprint"] = metadata_fingerprint(job)
    return job


def reconcile_batch(batch: str) -> int:
    current_name = f"current_jobs_{batch}.json"
    mapping_name = f"ats_mapping_{batch}.json"
    current = read_json(current_name, {}) or {}
    mapping = read_json(mapping_name, {"companies": []}) or {"companies": []}
    mapping_by_company = {row.get("company"): row for row in mapping.get("companies", []) if row.get("company")}

    changed = 0
    for company_row in current.get("companies", []):
        company_name = company_row.get("company")
        if company_name not in PATH_LOCATION_COMPANIES:
            continue
        mapped = mapping_by_company.get(company_name)
        if not mapped:
            raise RuntimeError(f"{batch.upper()} {company_name}: ATS mapping missing")
        family = str(((mapped.get("ats") or {}).get("family") or "")).casefold()
        if "workday" not in family:
            raise RuntimeError(f"{batch.upper()} {company_name}: expected Workday mapping, got {family!r}")

        rows, host, site, search_url = enumerate_workday(mapped)
        jobs = list(company_row.get("jobs") or [])
        by_source = {str(j.get("source_id")): j for j in jobs if j.get("source_id") is not None}
        by_url = {
            str(j.get("canonical_url") or "").rstrip("/").casefold(): j
            for j in jobs
            if j.get("canonical_url")
        }

        for raw in rows:
            candidate = candidate_from_raw(company_name, raw, host, site)
            if not candidate:
                continue
            sid = str(candidate.get("source_id"))
            curl = str(candidate.get("canonical_url") or "").rstrip("/").casefold()
            existing = by_source.get(sid) or by_url.get(curl)

            # The normal collector already captured it; no reconciliation needed.
            if existing and existing.get("status") in OPEN_STATUSES:
                continue

            if existing:
                old_fp = existing.get("fingerprint")
                candidate["status"] = "STILL_OPEN" if old_fp == candidate.get("fingerprint") else "UPDATED"
                idx = jobs.index(existing)
                jobs[idx] = candidate
            else:
                candidate["status"] = "NEW"
                jobs.append(candidate)
            by_source[sid] = candidate
            by_url[curl] = candidate
            changed += 1
            print(f"{batch.upper()} recovered Workday path-target role: {company_name}::{sid} | {candidate.get('title')}")

        company_row["jobs"] = jobs
        company_row["target_jobs_count"] = sum(1 for j in jobs if j.get("status") in OPEN_STATUSES)
        company_row["path_location_reconciled"] = True
        company_row["path_location_source_url"] = search_url

    if changed:
        all_jobs = [job for company in current.get("companies", []) for job in (company.get("jobs") or [])]
        summary = current.setdefault("summary", {})
        summary["target_jobs_open"] = sum(1 for job in all_jobs if job.get("status") in OPEN_STATUSES)
        for status in ("NEW", "STILL_OPEN", "UPDATED", "CLOSED", "UNKNOWN"):
            summary[status] = sum(1 for job in all_jobs if job.get("status") == status)
        current["workday_path_reconciliation"] = {
            "companies": sorted(PATH_LOCATION_COMPANIES),
            "recovered_count": changed,
        }
        write_json(current_name, current)
    return changed


def main() -> int:
    total = 0
    for batch in BATCHES:
        total += reconcile_batch(batch)
    print(f"Workday target-path reconciliation complete: recovered={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
