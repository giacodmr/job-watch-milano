#!/usr/bin/env python3
import html as htmlmod
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, parse_qs

import requests

BOARD = "https://kearney.recsolu.com/job_boards/1"
TIMEOUT = 30
TAB = "job-watch-yello-v16-diagnostic"


class BoardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.anchors.append(dict(attrs))

    def handle_data(self, data):
        s = " ".join(data.split())
        if s:
            self.text.append(s)


def get(session, url, params=None):
    r = session.get(
        url,
        params=params,
        timeout=TIMEOUT,
        headers={
            "User-Agent": "job-watch-milano/yello-diagnostic",
            "Accept": "application/json, text/html, */*",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    print("HTTP", r.status_code, len(r.content), r.url, r.headers.get("content-type"))
    r.raise_for_status()
    return r


def job_ids(fragment):
    fragment = htmlmod.unescape(fragment or "")
    return re.findall(r'href=["\']/jobs/([^?"\']+)\?job_board_id=([^&"\']+)', fragment, re.I)


def main():
    s = requests.Session()
    r = get(s, BOARD)
    p = BoardParser()
    p.feed(r.text)
    visible = " ".join(p.text)
    totals = [int(x.replace(",", "")) for x in re.findall(r"\b([\d,]+)\s+Results\b", visible, re.I)]
    expected = totals[0] if totals else None

    first_jobs = []
    for a in p.anchors:
        href = a.get("href")
        if not href:
            continue
        u = urljoin(r.url, href)
        if "/jobs/" in urlparse(u).path:
            q = parse_qs(urlparse(u).query)
            board_id = (q.get("job_board_id") or [None])[0]
            source_id = urlparse(u).path.rstrip("/").split("/")[-1]
            if board_id and source_id:
                first_jobs.append((source_id, board_id))
    first_jobs = list(dict.fromkeys(first_jobs))
    board_ids = sorted({x[1] for x in first_jobs})
    print("BOARD_TOTAL", expected)
    print("SSR_ROWS", len(first_jobs))
    print("BOARD_IDS", board_ids)
    if expected is None or len(board_ids) != 1:
        raise SystemExit("Missing reconcilable total or unique board id")

    board_id = board_ids[0]
    search = f"https://kearney.recsolu.com/job_boards/{board_id}/search"
    all_ids = []
    page = 1
    while page <= 50:
        params = {
            "query": "",
            "filters": "[]",
            "page_number": page,
            "job_board_tab_identifier": TAB,
        }
        rr = get(s, search, params=params)
        data = rr.json()
        pairs = job_ids(data.get("html"))
        ids = [sid for sid, bid in pairs if bid == board_id]
        print(
            "PAGE",
            json.dumps(
                {
                    "page": page,
                    "keys": sorted(data.keys()),
                    "rows": len(ids),
                    "unique_page": len(set(ids)),
                    "more_requisitions": data.get("more_requisitions"),
                    "query": data.get("query"),
                    "filters": data.get("filters"),
                    "text_filters": data.get("text_filters"),
                    "first": ids[:2],
                    "last": ids[-2:],
                },
                ensure_ascii=False,
            ),
        )
        if len(ids) != len(set(ids)):
            raise SystemExit(f"Duplicate IDs inside page {page}")
        all_ids.extend(ids)
        if not data.get("more_requisitions"):
            break
        if not ids:
            raise SystemExit(f"No rows while more_requisitions=true on page {page}")
        page += 1

    uniq = set(all_ids)
    print(
        "RECONCILE",
        {
            "pages": page,
            "raw_rows": len(all_ids),
            "unique_ids": len(uniq),
            "expected": expected,
            "duplicates_across_pages": len(all_ids) - len(uniq),
            "exact": len(uniq) == expected and len(all_ids) == expected,
        },
    )
    if len(uniq) != expected or len(all_ids) != expected:
        raise SystemExit("Yello inventory did not reconcile exactly")

    # Repeat once to prove deterministic exhaustive inventory, allowing a live
    # total change only by rejecting the run rather than guessing.
    r2 = get(s, BOARD)
    p2 = BoardParser(); p2.feed(r2.text)
    totals2 = [int(x.replace(",", "")) for x in re.findall(r"\b([\d,]+)\s+Results\b", " ".join(p2.text), re.I)]
    print("TOTAL_RECHECK", totals2)
    if not totals2 or totals2[0] != expected:
        raise SystemExit(f"Yello total changed during enumeration: {expected}->{totals2[0] if totals2 else None}")
    print("YELLO_EXHAUSTIVE_OK", expected)


if __name__ == "__main__":
    main()
