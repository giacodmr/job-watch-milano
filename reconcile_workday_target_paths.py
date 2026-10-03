#!/usr/bin/env python3
"""Recover target-geography Workday roles that the normal inventory can miss.

Recovery is deliberately conservative and uses only official Workday sources:
1. explicit target-city segments in Workday ``externalPath``;
2. targeted CXS searches for persisted TO_REVIEW / INTERESTED / APPLIED roles;
3. an official CXS job-detail fallback for explicitly externally-validated roles
   when Workday's broad inventory and search omit a still-live job.

A user decision is never deleted or silently closed merely because the broad
inventory omitted the vacancy.
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
    get_json,
    location_matches,
    metadata_fingerprint,
    post_json,
    workday_config,
    workday_source_id,
)

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1", "jw2", "jw3", "jw4")
PATH_LOCATION_COMPANIES = {"Euronext"}
ACTIVE_USER_DECISIONS = {"TO_REVIEW", "INTERESTED", "APPLIED"}


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


def targeted_workday_search(company: dict, search_text: str) -> tuple[list[dict], str, str, str]:
    host, tenant, site = workday_config(company)
    search_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    referer = f"https://{host}/{site}"
    data = post_json(
        search_url,
        {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": str(search_text)},
        headers={"Accept": "application/json", "Referer": referer, "Origin": f"https://{host}"},
    )
    page = data.get("jobPostings")
    if not isinstance(page, list):
        raise RuntimeError("Unexpected Workday CXS response during targeted decision reconciliation")
    return page, host, site, search_url


def candidate_from_raw(company_name: str, raw: dict, host: str, site: str, *, allow_metadata_location: bool = False) -> dict | None:
    external_path = str(raw.get("externalPath") or "").strip()
    path_location = safe_path_location(external_path)
    raw_location = str(raw.get("locationsText") or "").strip()
    if path_location:
        location = path_location if not raw_location else f"{path_location} | {raw_location}"
    elif allow_metadata_location and location_matches(raw_location, company_name):
        location = raw_location
    else:
        return None

    canonical = f"https://{host}/{site}{external_path}"
    employment = None
    for value in raw.get("bulletFields") or []:
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


def official_detail_candidate(company_name: str, source_id: str, mapped: dict) -> dict | None:
    """Validate an externally-known role against the official Workday detail API."""
    registry = (read_json("externally_validated_roles.json", {"records": {}}) or {}).get("records") or {}
    row = registry.get(f"{company_name}::{source_id}")
    if not isinstance(row, dict):
        return None

    host, tenant, site = workday_config(mapped)
    canonical = str(row.get("canonical_url") or "").strip()
    parsed = urlparse(canonical)
    expected_prefix = f"/{site}/job/"
    if parsed.scheme != "https" or parsed.netloc.casefold() != host.casefold() or not parsed.path.startswith(expected_prefix):
        raise RuntimeError(f"{company_name}::{source_id}: external fallback URL is not on the mapped Workday host/site")
    if source_id.casefold() not in unquote(parsed.path).casefold():
        raise RuntimeError(f"{company_name}::{source_id}: external fallback URL does not contain the source id")

    external_path = parsed.path[len(f"/{site}"):]
    path_location = safe_path_location(external_path)
    registry_location = str(row.get("location") or "").strip()
    if not path_location and not location_matches(registry_location, company_name):
        raise RuntimeError(f"{company_name}::{source_id}: external fallback is outside target geography")

    detail_url = f"https://{host}/wday/cxs/{tenant}/{site}{external_path}"
    detail = get_json(
        detail_url,
        headers={"Accept": "application/json", "Referer": canonical, "Origin": f"https://{host}"},
    )
    if not isinstance(detail, dict) or not detail:
        raise RuntimeError(f"{company_name}::{source_id}: official Workday detail response is empty")
    info = detail.get("jobPostingInfo") if isinstance(detail.get("jobPostingInfo"), dict) else detail
    detail_id = next(
        (str(info.get(field)) for field in ("jobReqId", "jobRequisitionId", "requisitionId") if info.get(field)),
        None,
    )
    if detail_id and detail_id != source_id:
        raise RuntimeError(f"{company_name}::{source_id}: official detail returned mismatched requisition {detail_id}")

    title = info.get("title") or row.get("title")
    location = info.get("location") or info.get("locationText") or path_location or registry_location
    if not location_matches(location, company_name) and not path_location:
        raise RuntimeError(f"{company_name}::{source_id}: official detail no longer resolves to a target geography")
    if path_location and path_location.casefold() not in str(location).casefold():
        location = f"{path_location} | {location}" if location else path_location

    job = compact_job(
        company_name,
        source_id,
        title=title,
        location=location,
        employment_type=info.get("timeType") or info.get("workerType"),
        published_at=info.get("postedOn") or info.get("startDate"),
        updated_at=info.get("updatedOn"),
        canonical=canonical,
        apply_url=canonical,
    )
    job["fingerprint"] = metadata_fingerprint(job)
    job["reconciliation_source"] = "official_workday_detail"
    return job


def upsert_recovered(jobs: list[dict], candidate: dict, *, persisted_decision: bool = False) -> bool:
    sid = str(candidate.get("source_id"))
    curl = str(candidate.get("canonical_url") or "").rstrip("/").casefold()
    existing = next((j for j in jobs if str(j.get("source_id")) == sid), None)
    if existing is None and curl:
        existing = next((j for j in jobs if str(j.get("canonical_url") or "").rstrip("/").casefold() == curl), None)
    if existing and existing.get("status") in OPEN_STATUSES:
        return False
    if existing:
        old_fp = existing.get("fingerprint")
        candidate["status"] = "STILL_OPEN" if old_fp == candidate.get("fingerprint") else "UPDATED"
        jobs[jobs.index(existing)] = candidate
    else:
        candidate["status"] = "STILL_OPEN" if persisted_decision else "NEW"
        jobs.append(candidate)
    return True


def active_decisions_for_company(company_name: str) -> list[tuple[str, dict]]:
    decisions = (read_json("user_job_decisions.json", {"records": {}}) or {}).get("records") or {}
    prefix = f"{company_name}::"
    return [
        (job_key[len(prefix):], row or {})
        for job_key, row in decisions.items()
        if job_key.startswith(prefix) and (row or {}).get("decision") in ACTIVE_USER_DECISIONS
    ]


def reconcile_persisted_decisions(company_name: str, mapped: dict, jobs: list[dict]) -> int:
    recovered = 0
    open_ids = {str(j.get("source_id")) for j in jobs if j.get("status") in OPEN_STATUSES}
    for source_id, decision in active_decisions_for_company(company_name):
        if source_id in open_ids:
            continue
        rows, host, site, _ = targeted_workday_search(mapped, source_id)
        exact = []
        for raw in rows:
            external_path = str(raw.get("externalPath") or "").strip()
            actual_id = str(workday_source_id(raw, external_path))
            if actual_id == source_id or source_id.casefold() in external_path.casefold():
                exact.append(raw)
        if len(exact) > 1:
            raise RuntimeError(f"{company_name}::{source_id}: targeted Workday search returned multiple exact matches")

        candidate = None
        if len(exact) == 1:
            candidate = candidate_from_raw(company_name, exact[0], host, site, allow_metadata_location=True)
            if candidate is None:
                raise RuntimeError(f"{company_name}::{source_id}: exact targeted Workday match is outside target geography")
        else:
            candidate = official_detail_candidate(company_name, source_id, mapped)
            if candidate is None:
                print(f"Targeted Workday decision search did not find {company_name}::{source_id}")
                continue
            print(f"Recovered official Workday detail fallback: {company_name}::{source_id} | {candidate.get('title')}")

        if upsert_recovered(jobs, candidate, persisted_decision=True):
            recovered += 1
            open_ids.add(source_id)
            print(
                f"Recovered persisted Workday decision: {company_name}::{source_id} | "
                f"{candidate.get('title')} | decision={decision.get('decision')}"
            )
    return recovered


def reconcile_batch(batch: str) -> int:
    current_name = f"current_jobs_{batch}.json"
    mapping_name = f"ats_mapping_{batch}.json"
    current = read_json(current_name, {}) or {}
    mapping = read_json(mapping_name, {"companies": []}) or {"companies": []}
    mapping_by_company = {row.get("company"): row for row in mapping.get("companies", []) if row.get("company")}

    changed = 0
    for company_row in current.get("companies", []):
        company_name = company_row.get("company")
        mapped = mapping_by_company.get(company_name)
        if not mapped:
            continue
        family = str(((mapped.get("ats") or {}).get("family") or "")).casefold()
        if "workday" not in family:
            continue
        jobs = list(company_row.get("jobs") or [])

        if company_name in PATH_LOCATION_COMPANIES:
            rows, host, site, search_url = enumerate_workday(mapped)
            for raw in rows:
                candidate = candidate_from_raw(company_name, raw, host, site)
                if candidate and upsert_recovered(jobs, candidate):
                    changed += 1
                    print(f"{batch.upper()} recovered Workday path-target role: {company_name}::{candidate.get('source_id')} | {candidate.get('title')}")
            company_row["path_location_reconciled"] = True
            company_row["path_location_source_url"] = search_url

        targeted = reconcile_persisted_decisions(company_name, mapped, jobs)
        changed += targeted
        if targeted:
            company_row["active_decision_reconciled"] = True
        company_row["jobs"] = jobs
        company_row["target_jobs_count"] = sum(1 for j in jobs if j.get("status") in OPEN_STATUSES)

    if changed:
        all_jobs = [job for company in current.get("companies", []) for job in (company.get("jobs") or [])]
        summary = current.setdefault("summary", {})
        summary["target_jobs_open"] = sum(1 for job in all_jobs if job.get("status") in OPEN_STATUSES)
        for status in ("NEW", "STILL_OPEN", "UPDATED", "CLOSED", "UNKNOWN"):
            summary[status] = sum(1 for job in all_jobs if job.get("status") == status)
        current["workday_path_reconciliation"] = {
            "companies": sorted(PATH_LOCATION_COMPANIES),
            "recovered_count": changed,
            "active_decision_targeted_search": True,
            "official_detail_fallback": True,
        }
        write_json(current_name, current)
    return changed


def main() -> int:
    total = sum(reconcile_batch(batch) for batch in BATCHES)
    print(f"Workday target-path/decision reconciliation complete: recovered={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
