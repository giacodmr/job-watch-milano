#!/usr/bin/env python3
from __future__ import annotations

import html
import re
from urllib.parse import urljoin

import requests

TARGETS = {
    "Boehringer": "https://jobs.boehringer-ingelheim.com/search/",
    "EON": "https://careers.eon.com/italia/go/italia-tutte-le-posizioni/3727301/",
}

s = requests.Session()
s.headers.update({"User-Agent": "job-watch-milano/sf-probe", "Accept": "text/html,*/*"})

for name, url in TARGETS.items():
    print("\n" + "=" * 90)
    print(name, url)
    r = s.get(url, timeout=30)
    print("PAGE", r.status_code, r.url, len(r.text))
    r.raise_for_status()
    text = html.unescape(r.text).replace("\\/", "/")

    init = re.search(r"(?is)j2w\.SearchResults\.init\s*\(\s*\{(.{0,5000}?)\}\s*\)", text)
    if init:
        print("INIT", re.sub(r"\s+", " ", init.group(1)).strip())

    scripts = [urljoin(r.url, x) for x in re.findall(r'''(?is)<script\b[^>]*?src\s*=\s*["']([^"']+)["']''', text)]
    js_urls = [x for x in scripts if "j2w.searchResults" in x]
    print("SEARCH_RESULTS_JS", js_urls)
    if not js_urls:
        continue
    jr = s.get(js_urls[0], timeout=30)
    print("JS_STATUS", jr.status_code, "LEN", len(jr.text))
    jr.raise_for_status()
    js = jr.text
    low = js.casefold()
    for key in ("apiendpoint", "searchquery", "record", "offset", "startrow", "tile-more-results", "ajax", "$.get", "$.post"):
        print("\nTOKEN", key)
        start = 0
        shown = 0
        while shown < 8:
            pos = low.find(key.casefold(), start)
            if pos < 0:
                break
            a = max(0, pos - 500)
            b = min(len(js), pos + 900)
            snippet = re.sub(r"\s+", " ", js[a:b]).strip()
            print(snippet)
            shown += 1
            start = pos + len(key)
