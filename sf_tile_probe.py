#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import collector

URLS = {
    "Italgas": "https://carriere.italgas.it/search/?createNewAlert=false&q=&optionsFacetsDD_customfield2=&optionsFacetsDD_customfield1=&locationsearch=",
    "Bolton": "https://jobs.boltongroup.net/search/",
    "Boehringer": "https://jobs.boehringer-ingelheim.com/search/",
}

INIT_RE = re.compile(r"j2w\.SearchResults\.init\s*\(\s*\{(.*?)\}\s*\)\s*;?", re.I | re.S)
FIELD_RE = lambda name: re.compile(rf"\b{name}\s*:\s*[\"']([^\"']*)[\"']", re.I)
PER_PAGE_RE = re.compile(r'data-per-page=["\'](\d+)["\']', re.I)


def config(page, base):
    blocks = INIT_RE.findall(page)
    if len(blocks) != 1:
        raise RuntimeError(f"expected one SearchResults init block, got {len(blocks)}")
    block = blocks[0]
    endpoint_m = FIELD_RE("apiEndpoint").search(block)
    query_m = FIELD_RE("searchQuery").search(block)
    per_m = PER_PAGE_RE.search(page)
    if not endpoint_m or not query_m or not per_m:
        raise RuntimeError("missing endpoint/searchQuery/per-page evidence")
    endpoint = endpoint_m.group(1).strip()
    query = html.unescape(query_m.group(1).strip())
    if not re.fullmatch(r"[A-Za-z0-9_-]+", endpoint):
        raise RuntimeError(f"unsafe endpoint: {endpoint}")
    return urljoin(base, f"/{endpoint}/"), query, int(per_m.group(1))


def with_startrow(endpoint, query, startrow):
    q = dict(parse_qsl(query.lstrip("?"), keep_blank_values=True))
    q["startrow"] = str(startrow)
    p = urlparse(endpoint)
    return urlunparse((p.scheme, p.netloc, p.path, "", urlencode(q), ""))


def parse_fragment(text, base):
    parser = collector.SFPageParser()
    parser.feed(text)
    jobs = collector.merge_sf_page_jobs(base, parser)
    return jobs


def main():
    for company, search_url in URLS.items():
        out = {"company": company}
        try:
            page, final = collector.sf_get_html(search_url)
            parser = collector.SFPageParser()
            parser.feed(page)
            total = collector.parse_sf_total(parser.visible_text)
            initial = collector.merge_sf_page_jobs(final, parser)
            endpoint, query, per_page = config(page, final)
            out.update({"total": total, "initial": len(initial), "per_page": per_page, "endpoint": endpoint, "query": query})
            all_jobs = {j["url"]: j for j in initial}
            pages = []
            start = per_page
            # Probe all pages only up to collector's existing safety cap.
            while total is not None and len(all_jobs) < total and len(pages) < collector.MAX_PAGES:
                url = with_startrow(endpoint, query, start)
                r = collector.get_session().get(url, headers={"Accept": "text/html; charset=UTF-8"}, timeout=collector.TIMEOUT)
                r.raise_for_status()
                jobs = parse_fragment(r.text, final)
                pages.append({"startrow": start, "jobs": len(jobs), "bytes": len(r.text)})
                before = len(all_jobs)
                for j in jobs:
                    all_jobs[j["url"]] = j
                if not jobs or len(all_jobs) == before:
                    break
                start += per_page
            out["pages"] = pages
            out["unique"] = len(all_jobs)
            out["reconciled"] = total is not None and len(all_jobs) == total
            out["locations_present"] = sum(bool(collector.clean_text(j.get("location"))) for j in all_jobs.values())
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
        print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
