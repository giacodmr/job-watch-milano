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
    ]
    found = []
    for pat in pats:
        for m in re.finditer(pat, text, re.I | re.S):
            s = re.sub(r"\s+", " ", m.group(0)).strip()
            if len(s) > 500:
                s = s[:500] + "..."
            if s not in found:
                found.append(s)
    return found[:20]


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
    print(f"    inventory_links={inv_links[:15]}")
    for s in snippets(page_html):
        print(f"    snippet={s}")
    if tile:
        try:
            for startrow in (0, tile['per_page']):
                tile_url = collector.sf_tile_url(tile, startrow)
                r = collector.get_session().get(tile_url, headers={"Accept": "text/html; charset=UTF-8"}, timeout=collector.TIMEOUT)
                print(f"    tile[{startrow}] status={r.status_code} url={r.url} bytes={len(r.text)}")
                p = collector.SFPageParser()
                p.feed(r.text)
                tj = collector.merge_sf_page_jobs(final_url, p)
                print(f"      tile_jobs={len(tj)} tile_total={collector.parse_sf_total(p.visible_text)} tile_range={collector.parse_sf_range(p.visible_text)}")
                if tj:
                    print(f"      first_job={tj[0]}")
        except Exception as e:
            print(f"    tile_probe ERROR {type(e).__name__}: {e}")


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


if __name__ == "__main__":
    main()
