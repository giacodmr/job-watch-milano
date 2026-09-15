#!/usr/bin/env python3
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, parse_qs

import requests

BOARD = "https://kearney.recsolu.com/job_boards/1"
TIMEOUT = 30


class ProbeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors = []
        self.scripts = []
        self.forms = []
        self.inputs = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        t = tag.lower()
        if t == "a":
            self.anchors.append(a)
        elif t == "script" and a.get("src"):
            self.scripts.append(a.get("src"))
        elif t == "form":
            self.forms.append(a)
        elif t == "input":
            self.inputs.append(a)

    def handle_data(self, data):
        s = " ".join(data.split())
        if s:
            self.text.append(s)


def fetch(session, url):
    r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": "job-watch-milano/yello-diagnostic"})
    print("HTTP", r.status_code, len(r.content), r.url)
    r.raise_for_status()
    return r


def interesting_asset(text):
    patterns = [
        r"https?://[^\"'\s<>]+",
        r"/[A-Za-z0-9_./-]*(?:api|job_board|jobs|search|filter|pagination|page)[A-Za-z0-9_?=&./:{}\[\]-]*",
    ]
    out = set()
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            v = m.group(0)
            if any(k in v.lower() for k in ("api", "job_board", "jobs", "search", "filter", "page", "pagination")):
                out.add(v[:500])
    return sorted(out)


def main():
    s = requests.Session()
    r = fetch(s, BOARD)
    html = r.text
    p = ProbeParser()
    p.feed(html)
    visible = " ".join(p.text)

    totals = re.findall(r"\b([\d,]+)\s+Results\b", visible, re.I)
    job_hrefs = []
    for a in p.anchors:
        href = a.get("href")
        if not href:
            continue
        u = urljoin(r.url, href)
        if "/jobs/" in urlparse(u).path:
            job_hrefs.append(u)
    uniq_jobs = list(dict.fromkeys(job_hrefs))
    board_ids = sorted({
        (parse_qs(urlparse(u).query).get("job_board_id") or [None])[0]
        for u in uniq_jobs
        if (parse_qs(urlparse(u).query).get("job_board_id") or [None])[0]
    })

    print("TOTAL_MARKERS", totals)
    print("JOB_LINKS", len(uniq_jobs))
    print("BOARD_IDS", board_ids)
    print("FIRST_JOBS", uniq_jobs[:5])
    print("LAST_JOBS", uniq_jobs[-5:])
    print("FORMS", p.forms[:10])
    print("INPUT_NAMES", sorted({x.get("name") for x in p.inputs if x.get("name")}))

    pageish = []
    for a in p.anchors:
        href = a.get("href") or ""
        txt = " ".join(str(a.get(k) or "") for k in ("title", "aria-label", "rel", "class"))
        if re.search(r"page|next|prev|pagination|offset|start", href + " " + txt, re.I):
            pageish.append((href, txt))
    print("PAGEISH_ANCHORS", pageish[:50])

    scripts = list(dict.fromkeys(urljoin(r.url, src) for src in p.scripts))
    print("SCRIPT_COUNT", len(scripts))
    print("SCRIPTS", scripts)

    inline_hits = interesting_asset(html)
    print("HTML_ENDPOINT_HINTS", inline_hits[:100])

    # Inspect only same-site / Yello JavaScript assets declared by the page.
    inspected = 0
    for src in scripts:
        host = urlparse(src).netloc.lower()
        if not (host.endswith("recsolu.com") or host.endswith("yello.co") or "recsolu" in host or "yello" in host):
            continue
        if inspected >= 12:
            break
        inspected += 1
        try:
            rr = fetch(s, src)
        except Exception as e:
            print("SCRIPT_ERROR", src, type(e).__name__, str(e))
            continue
        hits = interesting_asset(rr.text)
        print("SCRIPT_HINTS", src, hits[:120])


if __name__ == "__main__":
    main()
