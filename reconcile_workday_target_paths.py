#!/usr/bin/env python3
"""Recover target-geography Workday roles that the normal inventory can miss.

Recovery is deliberately conservative and first-party only:
1. explicit target-city segments in Workday ``externalPath``;
2. targeted CXS searches for persisted TO_REVIEW / INTERESTED / APPLIED roles;
3. an externally-validated official corporate careers listing when Workday's
   broad inventory/search omit a still-live job and the Workday detail API is
   blocked.

A user decision is never deleted or silently closed merely because the broad
inventory omitted the vacancy.
"""
from __future__ import annotations

import html as html_lib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from collector import (
    MAX_PAGES,
    OPEN_STATUSES,
    compact_job,
    get_html,
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
CORPORATE_LISTING_METHOD = "official_corporate_listing_contains_workday_link"


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


def same_first_party_host(listing_url: str, career_url: str) -> bool:
    listing_host = (urlparse(listing_url).hostname or "").casefold().lstrip("www.")
    career_host = (urlparse(career_url).hostname or "").casefold().lstrip("www.")
    if not listing_host or not career_host:
        return False
    return listing_host == career_host or listing_host.endswith("." + career_host) or career_host.endswith("." + listing_host)


def official_listing_candidate(company_name: str, source_id: str, mapped: dict) -> dict | None:
    """Validate a registry fallback against a first-party corporate careers listing.

    The fallback is fail-closed: the Workday canonical URL must belong to the
    mapped ATS, the listing must belong to the mapped corporate careers host,
    and the live HTML must contain both the exact role title and the exact
    Workday job-path marker (which carries the source id).
    """
    registry = (read_json("externally_validated_roles.json", {"records": {}}) or {}).get("records") or {}
    row = registry.get(f"{company_name}::{source_id}")
    if not isinstance(row, dict):
        return None
    if row.get("validation_method") != CORPORATE_LISTING_METHOD:
        return None

    host, _tenant, site = workday_config(mapped)
    canonical = str(row.get("canonical_url") or "").strip()
    parsed = urlparse(canonical)
    expected_prefix = f"/{site}/job/"
    if parsed.scheme != "https" or parsed.netloc.casefold() != host.casefold() or not parsed.path.startswith(expected_prefix):
        raise RuntimeError(f"{company_name}::{source_id}: fallback URL is not on the mapped Workday host/site")
    if source_id.casefold() not in unquote(parsed.path).casefold():
        raise RuntimeError(f"{company_name}::{source_id}: fallback URL does not contain the source id")

    path_location = safe_path_location(parsed.path[len(f"/{site}"):])
    registry_location = str(row.get("location") or "").strip()
    if not path_location and not location_matches(registry_location, company_name):
        raise RuntimeError(f"{company_name}::{source_id}: fallback is outside target geography")

    listing_url = str(row.get("official_listing_url") or "").strip()
    career_url = str(((mapped.get("ats") or {}).get("career_site") or "")).strip()
    if not listing_url or urlparse(listing_url).scheme != "https" or not same_first_party_host(listing_url, career_url):
        raise RuntimeError(f"{company_name}::{source_id}: official listing is not on the mapped first-party careers host")

    listing_html, final_url = get_html(listing_url)
    if not same_first_party_host(final_url, career_url):
        raise RuntimeError(f"{company_name}::{source_id}: official listing redirected off the first-party careers host")
    decoded = html_lib.unescape(listing_html)
    title = str(row.get("title") or "").strip()
    workday_path_marker = unquote(parsed.path.split("/job/", 1)[1])
    normalized_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", decoded)).casefold()
    if title.casefold() not in normalized_text:
        raise RuntimeError(f"{company_name}::{source_id}: role title is absent from the official corporate listing")
    if source_id.casefold() not in decoded.casefold() or workday_path_marker.casefold() not in decoded.casefold():
        raise RuntimeError(f"{company_name}::{source_id}: official listing does not contain the exact Workday job link")

    location = path_location or registry_location
    job = compact_job(
        company_name,
        source_id,
        title=title,
        location=location,
        canonical=canonical,
        apply_url=canonical + "/apply",
    )
    job["fingerprint"] = metadata_fingerprint(job)
    job["reconciliation_source"] = "official_corporate_listing"
    job["official_listing_url"] = final_url
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

        if len(exact) == 1:
            candidate = candidate_from_raw(company_name, exact[0], host, site, allow_metadata_location=True)
            if candidate is None:
                raise RuntimeError(f"{company_name}::{source_id}: exact targeted Workday match is outside target geography")
        else:
            candidate = official_listing_candidate(company_name, source_id, mapped)
            if candidate is None:
                print(f"Targeted Workday decision search did not find {company_name}::{source_id}")
                continue
            print(f"Recovered official corporate-listing fallback: {company_name}::{source_id} | {candidate.get('title')}")

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
            "official_corporate_listing_fallback": True,
        }
        write_json(current_name, current)
    return changed


def main() -> int:
    total = sum(reconcile_batch(batch) for batch in BATCHES)
    print(f"Workday target-path/decision reconciliation complete: recovered={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
