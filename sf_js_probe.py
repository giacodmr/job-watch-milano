#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin, urlparse

import collector

URLS = {
    "Italgas": "https://carriere.italgas.it/search/?createNewAlert=false&q=&optionsFacetsDD_customfield2=&optionsFacetsDD_customfield1=&locationsearch=",
    "Bolton": "https://jobs.boltongroup.net/search/",
    "Boehringer": "https://jobs.boehringer-ingelheim.com/search/",
}
KEYS = (
    "data-record-returned", "data-per-page", "job-tile-list", "loadmore",
    "load-more", "showmore", "show-more", "startrow", "pagination", "ajax",
)


def script_urls(base, page):
    urls = []
    for src in re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", page, re.I):
        u = urljoin(base, html.unescape(src).strip())
        if urlparse(u).scheme in {"http", "https"}:
            urls.append(u)
    return list(dict.fromkeys(urls))


def snippets(text):
    out = []
    low = text.casefold()
    for key in KEYS:
        start = 0
        while True:
            pos = low.find(key, start)
            if pos < 0:
                break
            chunk = re.sub(r"\s+", " ", text[max(0, pos - 500):pos + 900]).strip()
            if chunk not in out:
                out.append(chunk[:1400])
            if len(out) >= 20:
                return out
            start = pos + len(key)
    return out


def main():
    session = collector.get_session()
    for company, url in URLS.items():
        result = {"company": company}
        try:
            page, final = collector.sf_get_html(url)
            result["page_snippets"] = snippets(page)[:8]
            found = []
            for js_url in script_urls(final, page):
                try:
                    r = session.get(js_url, timeout=collector.TIMEOUT)
                    if r.status_code != 200 or len(r.text) > 8_000_000:
                        continue
                    hits = snippets(r.text)
                    if hits:
                        found.append({"url": js_url, "snippets": hits[:8]})
                    if len(found) >= 8:
                        break
                except Exception:
                    continue
            result["scripts"] = found
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
