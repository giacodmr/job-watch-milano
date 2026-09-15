#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

PATH = Path("collector.py")
MARKER = "# === JOB WATCH V1.5 SUCCESSFACTORS TILE PAGINATION ==="

CODE = r'''

# === JOB WATCH V1.5 SUCCESSFACTORS TILE PAGINATION ===
# SAP SuccessFactors Career Site Builder can render a first page of job tiles and
# load subsequent tiles from an endpoint explicitly configured in the page's
# j2w.SearchResults.init(...) block. Use that contract only when it is directly
# evidenced by the official same-host page, and reconcile against a stable total.

SF_TILE_INIT_RE = re.compile(r"j2w\.SearchResults\.init\s*\(\s*\{(.*?)\}\s*\)\s*;?", re.I | re.S)
SF_TILE_PER_PAGE_RE = re.compile(r'data-per-page=["\'](\d+)["\']', re.I)


def sf_tile_config(page_html: str, base_url: str):
    blocks = SF_TILE_INIT_RE.findall(page_html)
    if len(blocks) != 1:
        return None
    block = blocks[0]
    endpoint_m = re.search(r'\bapiEndpoint\s*:\s*["\']([^"\']+)["\']', block, re.I)
    query_m = re.search(r'\bsearchQuery\s*:\s*["\']([^"\']*)["\']', block, re.I)
    per_m = SF_TILE_PER_PAGE_RE.search(page_html)
    if not endpoint_m or not query_m or not per_m:
        return None

    endpoint = clean_text(endpoint_m.group(1))
    query = html.unescape(query_m.group(1)).strip()
    if not endpoint or not re.fullmatch(r"[A-Za-z0-9_-]+", endpoint):
        return None
    if "startrow=" in query.casefold():
        return None
    try:
        per_page = int(per_m.group(1))
    except (TypeError, ValueError):
        return None
    if per_page <= 0 or per_page > 100:
        return None

    # SearchResults JS prefixes apiEndpoint with the optional CSB brand path.
    # Only accept a simple evidenced brand path segment; otherwise fail closed.
    brand = ""
    brand_matches = re.findall(r"[\"']brand[\"']\s*:\s*[\"']([^\"']*)[\"']", page_html, re.I)
    if brand_matches:
        unique_brands = {clean_text(x) or "" for x in brand_matches}
        if len(unique_brands) == 1:
            brand = next(iter(unique_brands))
    if brand:
        if not SAFE_TENANT_RE.fullmatch(brand):
            return None
        endpoint_url = urljoin(base_url, f"/{brand}/{endpoint}/")
    else:
        endpoint_url = urljoin(base_url, f"/{endpoint}/")

    if not same_host(base_url, endpoint_url):
        return None
    return {"endpoint": endpoint_url, "query": query, "per_page": per_page}


def sf_tile_url(config: dict, startrow: int) -> str:
    query = config["query"]
    sep = "&" if query and not query.endswith("?") and not query.endswith("&") else ""
    if not query:
        query = "?"
        sep = ""
    elif not query.startswith("?"):
        query = "?" + query
    return f"{config['endpoint']}{query}{sep}startrow={int(startrow)}"


def sf_tile_fragment_jobs(text: str, base_url: str):
    parser = SFPageParser()
    parser.feed(text)
    return merge_sf_page_jobs(base_url, parser)


def _sf_prepare_inventory(company):
    ats = company.get("ats", {})
    inventory = clean_text(ats.get("inventory_url"))
    if not inventory:
        raise NotCheckable("SuccessFactors inventory URL missing")

    html_text, current_url, parser = _sf_load_page(inventory)
    jobs = merge_sf_page_jobs(current_url, parser)
    total = parse_sf_total(parser.visible_text)
    discovered = find_sf_search_url(current_url, parser)
    should_probe = not is_sf_search_path(current_url) or (total not in (None, 0) and not jobs)
    if discovered and should_probe and discovered != current_url:
        d_html, d_url, d_parser = _sf_load_page(discovered)
        d_jobs = merge_sf_page_jobs(d_url, d_parser)
        if d_jobs or parse_sf_total(d_parser.visible_text) == 0:
            html_text, current_url, parser = d_html, d_url, d_parser
            jobs = d_jobs
            total = parse_sf_total(parser.visible_text)
    return html_text, current_url, parser, jobs, total


def collect_successfactors_tile(company):
    name = company.get("company")
    page_html, search_url, parser, first_jobs, expected_total = _sf_prepare_inventory(company)
    if expected_total is None:
        raise NotCheckable("SuccessFactors tile inventory has no reconcilable total")
    if expected_total == 0:
        return {
            "coverage": "VERIFIED",
            "collector": "successfactors_jobs2web_tile_metadata_v15",
            "inventory_count": 0,
            "jobs": [],
            "source_url": search_url,
        }
    if not first_jobs:
        raise NotCheckable("SuccessFactors tile inventory exposes no initial public requisitions")

    config = sf_tile_config(page_html, search_url)
    if not config:
        raise NotCheckable("SuccessFactors tile pagination contract is not safely evidenced by the public page")

    inventory_jobs = {item["url"]: item for item in first_jobs}
    startrow = config["per_page"]
    pages = 1
    while len(inventory_jobs) < expected_total:
        pages += 1
        if pages > MAX_PAGES:
            raise NotCheckable("SuccessFactors tile inventory exceeds safe exhaustive-page limit")
        url = sf_tile_url(config, startrow)
        try:
            r = get_session().get(
                url,
                headers={"Accept": "text/html; charset=UTF-8"},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise CollectorError(f"SuccessFactors tile endpoint request failed: {e}") from e
        page_jobs = sf_tile_fragment_jobs(r.text, search_url)
        if not page_jobs:
            raise NotCheckable(
                f"SuccessFactors tile pagination stopped early: retrieved={len(inventory_jobs)}, total={expected_total}"
            )
        before = len(inventory_jobs)
        for item in page_jobs:
            inventory_jobs[item["url"]] = item
        if len(inventory_jobs) == before:
            raise NotCheckable(
                f"SuccessFactors tile pagination repeated a page: retrieved={len(inventory_jobs)}, total={expected_total}"
            )
        startrow += config["per_page"]

    if len(inventory_jobs) != expected_total:
        raise NotCheckable(
            f"SuccessFactors tile reconciliation mismatch: retrieved={len(inventory_jobs)}, total={expected_total}"
        )

    # Re-read the canonical search inventory after the exhaustive walk. A live
    # inventory that changed while paginating must not be labelled VERIFIED.
    final_html, final_url, final_parser = _sf_load_page(search_url)
    final_total = parse_sf_total(final_parser.visible_text)
    if final_total != expected_total:
        raise NotCheckable(
            f"SuccessFactors tile total changed during enumeration: {expected_total}->{final_total}"
        )

    if not any(clean_text(x.get("location")) for x in inventory_jobs.values()):
        raise NotCheckable("SuccessFactors tile inventory was exhaustive but location metadata is unavailable")

    jobs = []
    for raw in inventory_jobs.values():
        loc = clean_text(raw.get("location"))
        if not location_matches(loc):
            continue
        jobs.append(
            compact_job(
                name,
                sf_job_source_id(raw["url"]),
                title=raw.get("title"),
                location=loc,
                published_at=raw.get("published_at"),
                canonical=raw.get("url"),
                apply_url=raw.get("url"),
            )
        )

    return {
        "coverage": "VERIFIED",
        "collector": "successfactors_jobs2web_tile_metadata_v15",
        "inventory_count": len(inventory_jobs),
        "jobs": jobs,
        "source_url": final_url,
    }


_collect_successfactors_v15_paged = collect_successfactors

def collect_successfactors(company):
    try:
        return _collect_successfactors_v15_paged(company)
    except NotCheckable as e:
        message = str(e).casefold()
        if "inventory not exhaustible" not in message:
            raise
        return collect_successfactors_tile(company)
'''


def main():
    text = PATH.read_text(encoding="utf-8")
    if MARKER in text:
        print("SuccessFactors tile pagination already present")
        return
    m = re.search(r'\nif __name__ == ["\']__main__["\']:\n\s+raise SystemExit\(main\(\)\)\s*$', text)
    if not m:
        raise SystemExit("Final main guard not found")
    PATH.write_text(text[:m.start()] + CODE + text[m.start():], encoding="utf-8")
    print("Applied evidenced SuccessFactors tile pagination")


if __name__ == "__main__":
    main()
