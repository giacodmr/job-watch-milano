#!/usr/bin/env python3
from __future__ import annotations

import re
from urllib.parse import urlparse

import collector_sf_v15 as exp

base = exp.base
_orig_collect_successfactors = base.collect_successfactors


def tile_config(text: str):
    """Read the public j2w.SearchResults.init configuration embedded in the page."""
    endpoint = re.search(r'''apiEndpoint\s*:\s*["']([^"']+)["']''', text, re.I)
    query = re.search(r'''searchQuery\s*:\s*["']([^"']*)["']''', text, re.I)
    per_page = re.search(r'''jobRecordsPerPage\s*:\s*parseInt\s*\(\s*["'](\d+)["']\s*\)''', text, re.I)
    found = re.search(r'''jobRecordsFound\s*:\s*parseInt\s*\(\s*["'](\d+)["']\s*\)''', text, re.I)
    if not all((endpoint, query, per_page, found)):
        return None
    ep = endpoint.group(1).strip().strip("/")
    q = query.group(1)
    if not ep or ".." in ep or not re.fullmatch(r"[A-Za-z0-9_./-]+", ep):
        return None
    pp = int(per_page.group(1))
    total = int(found.group(1))
    if pp <= 0 or pp > 200 or total < 0:
        return None

    brands = set(re.findall(r'''\bvar\s+brand\s*=\s*["']([^"']*)["']''', text, re.I))
    nonempty = {x.strip().strip("/") for x in brands if x.strip()}
    if len(nonempty) > 1:
        return None
    brand = next(iter(nonempty), "")
    if brand and not re.fullmatch(r"[A-Za-z0-9_-]+", brand):
        return None
    return {"endpoint": ep, "query": q, "per_page": pp, "total": total, "brand": brand}


def tile_page_url(page_url: str, cfg: dict, startrow: int) -> str:
    """Reproduce the exact URL construction used by public j2w.searchResults.min.js."""
    p = urlparse(page_url)
    prefix = f"/{cfg['brand']}" if cfg.get("brand") else ""
    h = f"{cfg['query']}&startrow={int(startrow)}"
    return f"{p.scheme}://{p.netloc}{prefix}/{cfg['endpoint']}/{h}"


def collect_successfactors(company):
    ats = company.get("ats") or {}
    inventory = base.clean_text(ats.get("inventory_url"))
    if not inventory:
        raise base.NotCheckable("SuccessFactors inventory URL missing")

    html_text, current_url = base.sf_get_html(inventory)
    parser = base.SFPageParser()
    parser.feed(html_text)

    if not base.is_sf_search_path(current_url):
        discovered = base.find_sf_search_url(current_url, parser)
        if not discovered:
            raise base.NotCheckable("No same-host exhaustive /search/ or /viewalljobs/ link exposed by portal")
        html_text, current_url = base.sf_get_html(discovered)
        parser = base.SFPageParser()
        parser.feed(html_text)

    expected_total = base.parse_sf_total(parser.visible_text)
    cfg = tile_config(parser.visible_text)
    first_jobs = base.merge_sf_page_jobs(current_url, parser)

    # Classic table/paged sites continue through the already-tested collector.
    if not cfg or not getattr(parser, "tile_jobs", None):
        return _orig_collect_successfactors(company)

    if expected_total is None:
        raise base.NotCheckable("SuccessFactors tile page does not expose a reconcilable inventory total")
    if cfg["total"] != expected_total:
        raise base.NotCheckable(
            f"SuccessFactors tile config total mismatch: page={expected_total}, config={cfg['total']}"
        )

    inventory_jobs = {x["url"]: x for x in first_jobs}
    if len(inventory_jobs) > expected_total:
        raise base.NotCheckable(
            f"SuccessFactors tile reconciliation overflow: retrieved={len(inventory_jobs)}, total={expected_total}"
        )

    startrow = cfg["per_page"]
    page_count = 1
    while len(inventory_jobs) < expected_total:
        page_count += 1
        if page_count > base.MAX_PAGES:
            raise base.NotCheckable("SuccessFactors tile inventory exceeds safe exhaustive-page limit")
        next_url = tile_page_url(current_url, cfg, startrow)
        fragment, final_url = base.sf_get_html(next_url)
        page_parser = base.SFPageParser()
        page_parser.feed(fragment)
        page_jobs = base.merge_sf_page_jobs(final_url, page_parser)
        if not page_jobs:
            raise base.NotCheckable(
                f"SuccessFactors tile pagination stopped early: retrieved={len(inventory_jobs)}, total={expected_total}, startrow={startrow}"
            )
        before = len(inventory_jobs)
        for item in page_jobs:
            inventory_jobs[item["url"]] = item
        if len(inventory_jobs) == before:
            raise base.NotCheckable(
                f"SuccessFactors tile pagination repeated a page: retrieved={len(inventory_jobs)}, total={expected_total}, startrow={startrow}"
            )
        if len(inventory_jobs) > expected_total:
            raise base.NotCheckable(
                f"SuccessFactors tile reconciliation overflow: retrieved={len(inventory_jobs)}, total={expected_total}"
            )
        startrow += cfg["per_page"]

    if len(inventory_jobs) != expected_total:
        raise base.NotCheckable(
            f"SuccessFactors tile reconciliation mismatch: retrieved={len(inventory_jobs)}, total={expected_total}"
        )
    if expected_total and not any(base.clean_text(x.get("location")) for x in inventory_jobs.values()):
        raise base.NotCheckable("SuccessFactors tile inventory was exhaustive but location metadata could not be extracted safely")

    name = company.get("company")
    jobs = []
    for raw in inventory_jobs.values():
        loc = base.clean_text(raw.get("location"))
        if not base.location_matches(loc):
            continue
        jobs.append(
            base.compact_job(
                name,
                base.sf_job_source_id(raw["url"]),
                title=raw.get("title"),
                location=loc,
                published_at=raw.get("published_at"),
                canonical=raw.get("url"),
                apply_url=raw.get("url"),
            )
        )

    return {
        "coverage": "VERIFIED",
        "collector": "successfactors_jobs2web_metadata",
        "inventory_count": len(inventory_jobs),
        "jobs": jobs,
        "source_url": inventory,
    }


base.collect_successfactors = collect_successfactors


if __name__ == "__main__":
    raise SystemExit(base.main())
