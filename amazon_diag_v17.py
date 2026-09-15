#!/usr/bin/env python3
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

SEARCH = "https://www.amazon.jobs/en/search"
JSON_ENDPOINTS = [
    "https://www.amazon.jobs/en/search.json",
    "https://www.amazon.jobs/en/search.json/",
]
TIMEOUT = 30


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.links = []
        self.text = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag.lower() == "script" and a.get("src"):
            self.scripts.append(a["src"])
        if tag.lower() == "a" and a.get("href"):
            self.links.append(a["href"])
    def handle_data(self, data):
        s = " ".join(data.split())
        if s:
            self.text.append(s)


def get(s, url, params=None, accept="*/*"):
    r = s.get(
        url,
        params=params,
        timeout=TIMEOUT,
        headers={
            "User-Agent": "job-watch-milano/amazon-diagnostic",
            "Accept": accept,
        },
    )
    print("HTTP", r.status_code, len(r.content), r.url, r.headers.get("content-type"))
    return r


def summarize_json(data):
    if isinstance(data, dict):
        print("JSON_KEYS", sorted(data.keys()))
        for key in ("hits", "total", "total_count", "count", "number_of_results", "jobs", "results", "content"):
            if key in data:
                value = data[key]
                if isinstance(value, list):
                    print("FIELD", key, "list_len", len(value))
                    if value:
                        print("FIRST_ITEM_KEYS", sorted(value[0].keys()) if isinstance(value[0], dict) else type(value[0]).__name__)
                        print("FIRST_ITEM", json.dumps(value[0], ensure_ascii=False)[:1200])
                else:
                    print("FIELD", key, repr(value)[:500])
    else:
        print("JSON_TYPE", type(data).__name__)


def main():
    s = requests.Session()
    r = get(s, SEARCH, accept="text/html,application/xhtml+xml")
    print("SEARCH_HEAD", re.sub(r"\s+", " ", r.text[:1000]))
    if r.ok:
        p = PageParser(); p.feed(r.text)
        visible = " ".join(p.text)
        print("VISIBLE_COUNT_HINTS", re.findall(r".{0,100}(?:results|jobs).{0,100}", visible, re.I)[:20])
        print("JOB_LINK_COUNT", len({urljoin(r.url, x) for x in p.links if "/en/jobs/" in urljoin(r.url, x)}))
        print("SCRIPTS", [urljoin(r.url, x) for x in p.scripts])
        for needle in ("search.json", "result_limit", "offset", "loc_query", "base_query", "radius"):
            low = r.text.lower(); pos = low.find(needle)
            if pos >= 0:
                print("HTML_CONTEXT", needle, re.sub(r"\s+", " ", r.text[max(0,pos-400):pos+800]))

    probes = [
        {},
        {"offset": 0, "result_limit": 10},
        {"offset": 10, "result_limit": 10},
        {"base_query": "", "loc_query": "Milan, Italy", "offset": 0, "result_limit": 10},
        {"base_query": "", "loc_query": "Rome, Italy", "offset": 0, "result_limit": 10},
        {"base_query": "", "loc_query": "London, United Kingdom", "offset": 0, "result_limit": 10},
    ]
    for endpoint in JSON_ENDPOINTS:
        print("ENDPOINT", endpoint)
        for params in probes:
            rr = get(s, endpoint, params=params, accept="application/json,text/plain,*/*")
            if not rr.ok:
                print("ERROR_BODY", rr.text[:500])
                continue
            try:
                data = rr.json()
            except Exception as e:
                print("JSON_ERROR", type(e).__name__, str(e), re.sub(r"\s+", " ", rr.text[:700]))
                continue
            print("PARAMS", params)
            summarize_json(data)


if __name__ == "__main__":
    main()
