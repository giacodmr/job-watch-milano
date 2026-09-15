#!/usr/bin/env python3
from __future__ import annotations

import html
import re
from urllib.parse import urljoin

import requests

TARGETS = {
    "Italgas-search": "https://carriere.italgas.it/search/?createNewAlert=false&q=&optionsFacetsDD_customfield2=&optionsFacetsDD_customfield1=&locationsearch=",
    "Terna-search": "https://jobs.terna.it/search/?locale=it_IT",
    "ENGIE-search": "https://jobs.engie.com/search/?createNewAlert=false&q=&locationsearch=",
    "Pirelli-search": "https://jobs.pirelli.com/search/",
    "Capgemini-all": "https://jobs.capgemini.com/go/All-Jobs/5354901/",
    "Capgemini-viewall": "https://jobs.capgemini.com/viewalljobs/",
}

s = requests.Session()
s.headers.update({"User-Agent": "job-watch-milano/sf-probe", "Accept": "text/html,*/*"})

for name, url in TARGETS.items():
    print("\n" + "=" * 100)
    print(name, url)
    try:
        r = s.get(url, timeout=30)
        print("PAGE", r.status_code, r.url, len(r.text))
        r.raise_for_status()
    except Exception as e:
        print("ERROR", repr(e))
        continue
    text = html.unescape(r.text).replace("\\/", "/")

    init = re.search(r"(?is)j2w\.SearchResults\.init\s*\(\s*\{(.{0,12000}?)\}\s*\)", text)
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

    # Show the first complete modern job tile so location markup can be parsed generically.
    tile = re.search(r'''(?is)<li\b[^>]*class=["'][^"']*\bjob-tile\b[^"']*["'][^>]*>.*?</li>''', text)
    if tile:
        snippet = re.sub(r"\s+", " ", tile.group(0)).strip()
        print("FIRST_TILE", snippet[:12000])
    else:
        print("FIRST_TILE none")

    # Show one classic job link and its nearby table/card context.
    jm = re.search(r'''(?is)<a\b[^>]*href=["']([^"']*/job/[^"']+)["'][^>]*>.*?</a>''', text)
    if jm:
        pos = jm.start()
        print("JOB_CONTEXT", re.sub(r"\s+", " ", text[max(0,pos-1500):pos+3500]).strip())

    hrefs = [urljoin(r.url, x) for x in re.findall(r'''(?is)href\s*=\s*["']([^"']+)["']''', text)]
    candidates = []
    for x in hrefs:
        low = x.casefold()
        if any(k in low for k in ("/search/", "/viewalljobs/", "/go/", "/job/")) and x not in candidates:
            candidates.append(x)
    print("LINKS", len(candidates))
    for x in candidates[:60]:
        print("LINK", x)
