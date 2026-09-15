#!/usr/bin/env python3
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, parse_qs

import requests

BOARD = "https://kearney.recsolu.com/job_boards/1"
TIMEOUT = 30
KEYWORDS = (
    "/search", "filter_fields", "pagination", "currentpage", "per_page",
    "page_size", "offset", "loadmore", "load_more", "job_board_id",
    "searchurl", "search_url", "$http", "fetch(", "axios",
)


class ProbeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors = []
        self.scripts = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag.lower() == "a":
            self.anchors.append(a)
        elif tag.lower() == "script" and a.get("src"):
            self.scripts.append(a.get("src"))

    def handle_data(self, data):
        s = " ".join(data.split())
        if s:
            self.text.append(s)


def fetch(session, url, **kwargs):
    headers = {"User-Agent": "job-watch-milano/yello-diagnostic", "Accept": "*/*"}
    headers.update(kwargs.pop("headers", {}) or {})
    r = session.get(url, timeout=TIMEOUT, headers=headers, **kwargs)
    print("HTTP", r.status_code, len(r.content), r.url, r.headers.get("content-type"))
    r.raise_for_status()
    return r


def contexts(label, text, keywords=KEYWORDS, radius=260, limit=120):
    compact = text.replace("\n", " ").replace("\r", " ")
    seen = set()
    count = 0
    for keyword in keywords:
        start = 0
        low = compact.lower()
        needle = keyword.lower()
        while True:
            idx = low.find(needle, start)
            if idx < 0:
                break
            snippet = compact[max(0, idx-radius): min(len(compact), idx+len(needle)+radius)]
            snippet = re.sub(r"\s+", " ", snippet)
            if snippet not in seen:
                seen.add(snippet)
                print(label, keyword, snippet)
                count += 1
                if count >= limit:
                    return
            start = idx + len(needle)


def main():
    s = requests.Session()
    r = fetch(s, BOARD)
    html = r.text
    p = ProbeParser()
    p.feed(html)
    visible = " ".join(p.text)

    totals = re.findall(r"\b([\d,]+)\s+Results\b", visible, re.I)
    jobs = []
    for a in p.anchors:
        href = a.get("href")
        if not href:
            continue
        u = urljoin(r.url, href)
        if "/jobs/" in urlparse(u).path:
            jobs.append(u)
    jobs = list(dict.fromkeys(jobs))
    board_ids = sorted({
        (parse_qs(urlparse(u).query).get("job_board_id") or [None])[0]
        for u in jobs
        if (parse_qs(urlparse(u).query).get("job_board_id") or [None])[0]
    })

    print("TOTAL_MARKERS", totals)
    print("JOB_LINKS", len(jobs))
    print("BOARD_IDS", board_ids)
    print("FIRST_JOBS", jobs[:3])
    print("LAST_JOBS", jobs[-3:])
    contexts("HTML_CONTEXT", html)

    scripts = list(dict.fromkeys(urljoin(r.url, src) for src in p.scripts))
    print("SCRIPT_COUNT", len(scripts))
    for src in scripts:
        if "job_boards" not in src:
            continue
        rr = fetch(s, src)
        print("TARGET_SCRIPT", src, len(rr.text))
        contexts("JS_CONTEXT", rr.text, radius=420, limit=160)

    if board_ids:
        token = board_ids[0]
        canonical = f"https://kearney.recsolu.com/job_boards/{token}"
        search = canonical + "/search"
        print("CANONICAL", canonical)
        print("SEARCH", search)
        # Passive GET probes only; preserve default unfiltered scope.
        for params in ({}, {"page": 2}, {"page": 1}, {"offset": 25}, {"start": 25}):
            try:
                rr = fetch(s, search, params=params, headers={"Accept": "application/json, text/html, */*"})
                head = re.sub(r"\s+", " ", rr.text[:600])
                print("SEARCH_GET", params, "BODY_HEAD", head)
            except Exception as e:
                print("SEARCH_GET_ERROR", params, type(e).__name__, str(e))


if __name__ == "__main__":
    main()
