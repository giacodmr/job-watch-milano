#!/usr/bin/env python3
from __future__ import annotations

import html
import re
from urllib.parse import urljoin

import requests

TARGETS = {
    "Bolton": "https://jobs.boltongroup.net/search/",
    "Italgas": "https://carriere.italgas.it/",
    "Pirelli": "https://jobs.pirelli.com/search/",
    "Terna": "https://jobs.terna.it/",
    "ENGIE": "https://jobs.engie.com/",
    "Capgemini": "https://jobs.capgemini.com/viewalljobs/",
    "Mundys": "https://jobs.mundys.com/",
}

s = requests.Session()
s.headers.update({"User-Agent": "job-watch-milano/sf-probe", "Accept": "text/html,*/*"})

for name, url in TARGETS.items():
    print("\n" + "=" * 90)
    print(name, url)
    try:
        r = s.get(url, timeout=30)
        print("PAGE", r.status_code, r.url, len(r.text))
        r.raise_for_status()
    except Exception as e:
        print("ERROR", repr(e))
        continue
    text = html.unescape(r.text).replace("\\/", "/")

    init = re.search(r"(?is)j2w\.SearchResults\.init\s*\(\s*\{(.{0,8000}?)\}\s*\)", text)
    if init:
        print("INIT", re.sub(r"\s+", " ", init.group(1)).strip())
    else:
        print("INIT none")

    for pat in (
        r"(?:Showing|Results|Risultati|Ergebnisse|Résultats)\s+\d+\s*(?:to|–|-)\s*\d+\s+(?:of|di|von|sur)\s+[\d.,]+",
        r"jobRecordsFound\s*:\s*parseInt\s*\([^)]*\)",
        r"data-record-count\s*=\s*[\"'][^\"']+[\"']",
        r"data-record-returned\s*=\s*[\"'][^\"']+[\"']",
    ):
        vals = re.findall(pat, text, re.I)
        if vals:
            print("TOTAL_HINT", vals[:10])

    hrefs = [urljoin(r.url, x) for x in re.findall(r'''(?is)href\s*=\s*["']([^"']+)["']''', text)]
    candidates = []
    for x in hrefs:
        low = x.casefold()
        if any(k in low for k in ("/search/", "/viewalljobs/", "/go/", "/job/")) and x not in candidates:
            candidates.append(x)
    print("LINKS", len(candidates))
    for x in candidates[:40]:
        print("LINK", x)
