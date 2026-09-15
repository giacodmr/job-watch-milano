#!/usr/bin/env python3
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import collector

TARGETS = {
    "Worldline",
    "Capgemini Invent",
    "Terna",
    "ENGIE Italia",
    "Pirelli",
    "Zurich",
}


def companies():
    out = {}
    for batch in ("jw1", "jw2", "jw3", "jw4"):
        data = json.loads(Path(f"ats_mapping_{batch}.json").read_text(encoding="utf-8"))
        for company in data.get("companies", []):
            if company.get("company") in TARGETS:
                out[company["company"]] = company
    return out


def snippets(text):
    pats = [
        r"j2w\.SearchResults\.init\s*\(\s*\{.*?\}\s*\)",
        r"apiEndpoint\s*:\s*['\"][^'\"]+['\"]",
        r"searchQuery\s*:\s*['\"][^'\"]*['\"]",
        r"(?:totalJobs|totalResults|resultCount|jobCount)\s*[:=]\s*['\"]?\d+",
        r"data-per-page=['\"]\d+['\"]",
        r"(?:ajax|api|search|job)[A-Za-z0-9_-]*(?:Url|URL|Endpoint)\s*[:=]\s*['\"][^'\"]+['\"]",
    ]
    found = []
    for pat in pats:
        for m in re.finditer(pat, text, re.I | re.S):
            s = re.sub(r"\s+", " ", m.group(0)).strip()
            if len(s) > 500:
                s = s[:500] + "..."
            if s not in found:
                found.append(s)
    return found[:30]


def raw_signals(page_html):
    return {
        "raw_job_path_count": len(re.findall(r"/job/", page_html, re.I)),
        "raw_job_id_count": len(re.findall(r"\bjob(?:Id|ID|id)\b", page_html)),
        "raw_startrow_count": len(re.findall(r"startrow", page_html, re.I)),
        "raw_ajax_count": len(re.findall(r"ajax", page_html, re.I)),
        "raw_searchresults_count": len(re.findall(r"SearchResults", page_html, re.I)),
    }


def inspect_url(label, url):
    try:
        page_html, final_url, parser = collector._sf_load_page_strict(url)
    except Exception as e:
        print(f"  {label}: ERROR {type(e).__name__}: {e}")
        return
    jobs = collector.merge_sf_page_jobs(final_url, parser)
    total = collector.parse_sf_total(parser.visible_text)
    rng = collector.parse_sf_range(parser.visible_text)
    tile = collector.sf_tile_config(page_html, final_url)
    print(f"  {label}: {final_url}")
    print(f"    total={total} range={rng} jobs={len(jobs)} tile={tile}")
    print(f"    raw={raw_signals(page_html)}")
    forms = list(dict.fromkeys(getattr(parser, 'form_actions', []) or []))
    if forms:
        print(f"    forms={forms[:10]}")
    inv_links = []
    for a in parser.anchors:
        href = collector.normalize_abs_url(final_url, a.get('href'))
        if href and collector.same_host(final_url, href):
            p = collector.urlparse(href).path.casefold()
            if any(x in p for x in ('/search', '/viewalljobs', '/go/', '/job/')):
                inv_links.append(href)
    inv_links = list(dict.fromkeys(inv_links))
    print(f"    inventory_links={inv_links[:20]}")
    for s in snippets(page_html):
        print(f"    snippet={s}")


def trace_zurich(company):
    print("\n--- ZURICH PAGINATION TRACE ---")
    source = urljoin((company.get('ats') or {}).get('inventory_url') or '', '/search/')
    try:
        page_html, current_url, parser = collector._sf_load_page_strict(source)
        expected = collector.parse_sf_total(parser.visible_text)
        visited = set()
        inventory = {}
        for page_no in range(1, 40):
            rng = collector.parse_sf_range(parser.visible_text)
            rows = collector.merge_sf_page_jobs(current_url, parser)
            missing = sum(1 for x in rows if not collector.clean_text(x.get('location')))
            before = len(inventory)
            for row in rows:
                inventory[row['url']] = row
            print(f"  page={page_no} url={current_url} range={rng} rows={len(rows)} missing_loc={missing} unique={len(inventory)}")
            if expected is not None and len(inventory) >= expected:
                break
            visited.add(current_url)
            nxt = collector._sf_fetch_validated_next(current_url, parser, expected, visited)
            if not nxt:
                print(f"  STOP no-next after page={page_no}, unique={len(inventory)}, expected={expected}")
                break
            page_html, current_url, parser = nxt
    except Exception as e:
        print(f"  TRACE ERROR {type(e).__name__}: {e}")


def main():
    found = companies()
    missing = TARGETS - set(found)
    if missing:
        print("MISSING", sorted(missing))
    for name in sorted(found):
        company = found[name]
        inv = (company.get("ats") or {}).get("inventory_url")
        print("\n===", name, "===")
        print("mapped", inv)
        urls = []
        if inv:
            urls.append(("mapped", inv))
            urls.append(("root-search", urljoin(inv, "/search/")))
            urls.append(("root-viewalljobs", urljoin(inv, "/viewalljobs/")))
        seen = set()
        for label, url in urls:
            if not url or url in seen:
                continue
            seen.add(url)
            inspect_url(label, url)
    if "Zurich" in found:
        trace_zurich(found["Zurich"])


if __name__ == "__main__":
    main()
