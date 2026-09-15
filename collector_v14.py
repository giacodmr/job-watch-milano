#!/usr/bin/env python3
from __future__ import annotations

import html
import re
from urllib.parse import unquote, urlparse

import requests

import collector as base

VERSION = "1.4"
ORACLE_SCOPE_NAME = "Oracle Recruiting Cloud / Oracle HCM Candidate Experience"
ORACLE_HOST_RE = re.compile(r"https?://([A-Za-z0-9.-]+\.oraclecloud\.com)(?=[:/\"'\\]|$)", re.I)
ORACLE_SITE_RE = re.compile(r"/sites/([^/?#]+)(?:/|$)", re.I)
ORACLE_PAGE_LIMIT = 25

# Reuse every v1.3 collector/reconciliation rule and add one conservative,
# metadata-only Oracle Recruiting Cloud collector. No job-detail calls are made.
base.COLLECTOR_VERSION = VERSION
_original_choose = base.choose
_original_unsupported_result = base.unsupported_result
_original_collect_batch = base.collect_batch


def oracle_family(company: dict) -> bool:
    family = (base.clean_text((company.get("ats") or {}).get("family")) or "").casefold()
    if "taleo" in family:
        return False
    return any(x in family for x in ("oracle recruiting cloud", "oracle hcm", "oracle fusion"))


def oracle_site_from_inventory(inventory: str) -> str | None:
    m = ORACLE_SITE_RE.search(urlparse(inventory).path)
    if not m:
        return None
    site = unquote(m.group(1)).strip()
    if not site or not base.SAFE_TENANT_RE.fullmatch(site):
        return None
    return site


def oracle_public_job_base(inventory: str, site: str) -> str:
    p = urlparse(inventory)
    path = p.path
    m = re.search(rf"^(.*?/sites/{re.escape(site)})(?:/.*)?$", path, re.I)
    if not m:
        raise base.NotCheckable("Oracle Candidate Experience site path could not be normalized")
    return f"{p.scheme or 'https'}://{p.netloc}{m.group(1)}"


def oracle_backend_hosts(inventory: str) -> list[str]:
    """Return only hosts evidenced by the mapped URL or the official page itself."""
    p = urlparse(inventory)
    hosts = []
    if p.netloc:
        hosts.append(p.netloc)

    # Custom branded Oracle Candidate Experience domains sometimes proxy the REST
    # path directly; others expose the underlying *.oraclecloud.com host in page
    # configuration. We only use a backend host if it is literally observed.
    try:
        r = base.get_response(inventory)
        text = html.unescape(r.text).replace("\\/", "/")
        for m in ORACLE_HOST_RE.finditer(text):
            host = m.group(1)
            if host.casefold() not in {x.casefold() for x in hosts}:
                hosts.append(host)
        final_host = urlparse(r.url).netloc
        if final_host and final_host.casefold() not in {x.casefold() for x in hosts}:
            hosts.append(final_host)
    except requests.RequestException:
        # The REST endpoint may still be reachable even if the rendered page blocks
        # automation. Do not turn page-rendering failure into collector failure.
        pass
    return hosts


def oracle_extract_root(data) -> dict:
    if not isinstance(data, dict):
        raise base.NotCheckable("Oracle Candidate Experience returned non-object JSON")
    items = data.get("items")
    if isinstance(items, list) and items:
        root = items[0]
    elif "requisitionList" in data:
        root = data
    else:
        raise base.NotCheckable("Oracle Candidate Experience response has no requisition inventory")
    if not isinstance(root, dict):
        raise base.NotCheckable("Oracle Candidate Experience root item is not an object")
    return root


def oracle_location(raw: dict) -> str | None:
    values = []
    primary = base.clean_text(raw.get("PrimaryLocation"))
    if primary:
        values.append(primary)
    for field in ("secondaryLocations", "otherWorkLocations"):
        for item in raw.get(field) or []:
            if not isinstance(item, dict):
                continue
            value = base.clean_text(item.get("Name"))
            if not value:
                pieces = [
                    base.clean_text(item.get("TownOrCity")),
                    base.clean_text(item.get("Region1")),
                    base.clean_text(item.get("Country")),
                ]
                value = ", ".join(x for x in pieces if x) or None
            if value and value not in values:
                values.append(value)
    return " | ".join(values) if values else None


def oracle_source_id(raw: dict) -> str | None:
    for field in ("Id", "RequisitionId", "RequisitionNumber", "ExternalRequisitionId"):
        value = base.clean_text(raw.get(field))
        if value:
            return value
    return None


def oracle_get_page(host: str, site: str, offset: int) -> tuple[dict, str]:
    endpoint = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    finder = f"findReqs;siteNumber={site},limit={ORACLE_PAGE_LIMIT},offset={offset}"
    headers = {
        "Accept": "application/vnd.oracle.adf.resourcecollection+json, application/json",
        "Ora-Irc-Language": "en",
        "REST-Framework-Version": "1",
    }
    r = base.get_session().get(
        endpoint,
        params={
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations",
            "finder": finder,
        },
        headers=headers,
        timeout=base.TIMEOUT,
    )
    if r.status_code in {401, 403, 404, 406, 410}:
        raise base.NotCheckable(f"Oracle public Candidate Experience endpoint unavailable on {host}: HTTP {r.status_code}")
    r.raise_for_status()
    try:
        return r.json(), r.url
    except ValueError as e:
        raise base.NotCheckable(f"Oracle endpoint on {host} did not return JSON") from e


def collect_oracle(company: dict):
    name = company.get("company")
    ats = company.get("ats") or {}
    inventory = base.clean_text(ats.get("inventory_url"))
    if not inventory:
        raise base.CollectorError("Oracle inventory URL missing")
    site = oracle_site_from_inventory(inventory)
    if not site:
        raise base.NotCheckable("Oracle Candidate Experience site number is not present in mapped inventory URL")
    public_base = oracle_public_job_base(inventory, site)
    hosts = oracle_backend_hosts(inventory)
    if not hosts:
        raise base.NotCheckable("No Oracle Candidate Experience host could be evidenced")

    selected_host = None
    first_data = None
    first_url = None
    not_checkable_reasons = []
    for host in hosts:
        try:
            first_data, first_url = oracle_get_page(host, site, 0)
            # Validate shape before accepting a host.
            oracle_extract_root(first_data)
            selected_host = host
            break
        except base.NotCheckable as e:
            not_checkable_reasons.append(str(e))
            continue
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            if status in {401, 403, 404, 406, 410}:
                not_checkable_reasons.append(f"{host}: HTTP {status}")
                continue
            raise base.CollectorError(f"Oracle Candidate Experience HTTP failure on {host}: {e}") from e
        except requests.RequestException as e:
            raise base.CollectorError(f"Oracle Candidate Experience request failure on {host}: {e}") from e

    if selected_host is None or first_data is None:
        detail = "; ".join(not_checkable_reasons[-3:]) or "no usable public endpoint"
        raise base.NotCheckable(f"Oracle inventory could not be safely enumerated: {detail}")

    all_rows: list[dict] = []
    seen: set[str] = set()
    total = None
    offset = 0
    source_url = first_url

    for page_index in range(base.MAX_PAGES):
        if page_index == 0:
            data = first_data
        else:
            try:
                data, source_url = oracle_get_page(selected_host, site, offset)
            except base.NotCheckable as e:
                raise base.NotCheckable(f"Oracle pagination became unavailable: {e}") from e
        root = oracle_extract_root(data)
        page = root.get("requisitionList")
        if not isinstance(page, list):
            raise base.NotCheckable("Oracle response does not expose requisitionList as an array")

        if total is None:
            raw_total = root.get("TotalJobsCount")
            if raw_total is None:
                raise base.NotCheckable("Oracle inventory has no TotalJobsCount; completeness cannot be proven")
            try:
                total = int(raw_total)
            except (TypeError, ValueError) as e:
                raise base.NotCheckable(f"Oracle TotalJobsCount is invalid: {raw_total!r}") from e
            if total < 0:
                raise base.NotCheckable("Oracle TotalJobsCount is negative")

        for raw in page:
            if not isinstance(raw, dict):
                continue
            sid = oracle_source_id(raw)
            if not sid:
                raise base.NotCheckable("Oracle requisition lacks a stable public identifier")
            if sid in seen:
                continue
            seen.add(sid)
            all_rows.append(raw)

        if len(all_rows) >= total:
            break
        if not page:
            raise base.NotCheckable(f"Oracle pagination stopped early: retrieved={len(all_rows)}, total={total}")
        offset += len(page)
    else:
        raise base.CollectorError("Oracle pagination safety limit")

    if total is None or len(all_rows) != total:
        raise base.NotCheckable(f"Oracle count mismatch: retrieved={len(all_rows)}, total={total}")

    jobs = []
    for raw in all_rows:
        sid = oracle_source_id(raw)
        assert sid is not None
        loc = oracle_location(raw)
        if not base.location_matches(loc):
            continue
        canonical = f"{public_base}/job/{sid}"
        employment = base.clean_text(raw.get("JobType")) or base.clean_text(raw.get("ContractType"))
        job = base.compact_job(
            name,
            sid,
            title=raw.get("Title"),
            location=loc,
            department=raw.get("Department") or raw.get("Organization"),
            employment_type=employment,
            published_at=raw.get("PostedDate"),
            updated_at=None,
            canonical=canonical,
            apply_url=canonical,
        )
        jobs.append(job)

    return {
        "coverage": "VERIFIED",
        "collector": "oracle_recruiting_cloud_ce_metadata",
        "inventory_count": len(all_rows),
        "jobs": jobs,
        "source_url": source_url or inventory,
    }


def choose(company):
    if oracle_family(company):
        inventory = base.clean_text((company.get("ats") or {}).get("inventory_url")) or ""
        if oracle_site_from_inventory(inventory):
            return collect_oracle
    return _original_choose(company)


def unsupported_result(company, reason=None):
    result = _original_unsupported_result(company, reason)
    if result.get("collector") == "unsupported_or_unverified_v1_3":
        result["collector"] = "unsupported_or_unverified_v1_4"
    if not reason and result.get("reason"):
        result["reason"] = result["reason"].replace("collector v1.3", "collector v1.4")
    return result


def collect_batch(batch: str, workers: int = base.DEFAULT_WORKERS):
    payload = _original_collect_batch(batch, workers=workers)
    payload["version"] = VERSION
    scope = list(payload.get("collector_scope") or [])
    if ORACLE_SCOPE_NAME not in scope:
        scope.append(ORACLE_SCOPE_NAME)
    payload["collector_scope"] = scope
    base.write_json(base.ROOT / f"current_jobs_{batch}.json", payload)
    return payload


base.choose = choose
base.unsupported_result = unsupported_result
base.collect_batch = collect_batch


def main(argv=None):
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
