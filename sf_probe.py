#!/usr/bin/env python3
from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlparse

import requests

TARGETS = {
    "Intesa": "https://jobs.intesasanpaolo.com/viewalljobs/?locale=it_IT",
    "Worldline": "https://jobs.worldline.com/viewalljobs/",
    "Boehringer": "https://jobs.boehringer-ingelheim.com/search/",
    "EON": "https://careers.eon.com/italia/go/italia-tutte-le-posizioni/3727301/",
}

KEYS = (
    "startrow", "joblist", "jobsearch", "searchresult", "loadmore", "more search results",
    "careersitecompanyid", "ajax", "jobs2web", "job/", "searchjobs", "pagination",
)

s = requests.Session()
s.headers.update({"User-Agent": "job-watch-milano/sf-probe", "Accept": "text/html,*/*"})

for name, url in TARGETS.items():
    print("\n" + "=" * 90)
    print(name, url)
    r = s.get(url, timeout=30)
    print("STATUS", r.status_code, "FINAL", r.url, "LEN", len(r.text), "CTYPE", r.headers.get("content-type"))
    r.raise_for_status()
    text = html.unescape(r.text).replace("\\/", "/")

    # Inventory/job/pagination links actually exposed by the page.
    hrefs = re.findall(r'''(?is)href\s*=\s*["']([^"']+)["']''', text)
    interesting_hrefs = []
    for href in hrefs:
        absolute = urljoin(r.url, href)
        low = absolute.casefold()
        if any(k in low for k in ("/job/", "startrow=", "/viewalljobs/", "/search/", "/go/")):
            if absolute not in interesting_hrefs:
                interesting_hrefs.append(absolute)
    print("INTERESTING_HREFS", len(interesting_hrefs))
    for x in interesting_hrefs[:80]:
        print("HREF", x)

    # Form actions and buttons often back the JS-driven list.
    for m in re.finditer(r'''(?is)<form\b[^>]*?action\s*=\s*["']([^"']+)["'][^>]*>''', text):
        print("FORM", urljoin(r.url, m.group(1)))
    for m in re.finditer(r'''(?is)<(?:button|a)\b([^>]{0,800})>''', text):
        attrs = m.group(1)
        low = attrs.casefold()
        if any(k in low for k in ("startrow", "load", "more", "page", "job")):
            compact = re.sub(r"\s+", " ", attrs).strip()
            print("CONTROL", compact[:800])

    # Context snippets for known SuccessFactors loader/config tokens.
    low_text = text.casefold()
    printed = set()
    for key in KEYS:
        start = 0
        hits = 0
        while hits < 12:
            pos = low_text.find(key, start)
            if pos < 0:
                break
            a = max(0, pos - 220)
            b = min(len(text), pos + 420)
            snippet = re.sub(r"\s+", " ", text[a:b]).strip()
            sig = snippet[:160]
            if sig not in printed:
                printed.add(sig)
                print("CTX", key, snippet)
                hits += 1
            start = pos + len(key)

    scripts = re.findall(r'''(?is)<script\b[^>]*?src\s*=\s*["']([^"']+)["']''', text)
    print("SCRIPTS", len(scripts))
    for src in scripts[:50]:
        print("SCRIPT", urljoin(r.url, src))
