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
        if tag.lower() == "a": self.anchors.append(dict(attrs))
    def handle_data(self, data):
        s = " ".join(data.split())
        if s: self.text.append(s)


def get(session, url, params=None):
    r = session.get(url, params=params, timeout=TIMEOUT, headers={
        "User-Agent": "job-watch-milano/yello-diagnostic",
        "Accept": "application/json, text/html, */*",
        "X-Requested-With": "XMLHttpRequest",
    })
    print("HTTP", r.status_code, len(r.content), r.url, r.headers.get("content-type"))
    r.raise_for_status()
    return r


def strip_tags(value):
    if value is None: return ""
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(htmlmod.unescape(value).split())


def parse_cards(fragment, base, expected_board):
    fragment = htmlmod.unescape(fragment or "")
    cards = []
    for block in re.findall(r'<li[^>]*class=["\'][^"\']*search-results__item[^"\']*["\'][^>]*>(.*?)</li>', fragment, re.I | re.S):
        m = re.search(r'<a[^>]*class=["\'][^"\']*search-results__req_title[^"\']*["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', block, re.I | re.S)
        if not m: continue
        u = urljoin(base, htmlmod.unescape(m.group(1)))
        q = parse_qs(urlparse(u).query)
        bid = (q.get("job_board_id") or [None])[0]
        sid = urlparse(u).path.rstrip("/").split("/")[-1]
        spans = [strip_tags(x) for x in re.findall(r'<span[^>]*>(.*?)</span>', block, re.I | re.S)]
        cards.append({
            "id": sid,
            "board_id": bid,
            "url": u,
            "title": strip_tags(m.group(2)),
            "employment_type": spans[0] if len(spans) > 0 else "",
            "region": spans[1] if len(spans) > 1 else "",
            "location": spans[2] if len(spans) > 2 else "",
            "spans": spans,
        })
    return cards


def main():
    s = requests.Session()
    r = get(s, BOARD)
    p = BoardParser(); p.feed(r.text)
    visible = " ".join(p.text)
    totals = [int(x.replace(",", "")) for x in re.findall(r"\b([\d,]+)\s+Results\b", visible, re.I)]
    expected = totals[0] if totals else None
    board_ids = []
    for a in p.anchors:
        href = a.get("href")
        if not href: continue
        u = urljoin(r.url, href)
        if "/jobs/" not in urlparse(u).path: continue
        bid = (parse_qs(urlparse(u).query).get("job_board_id") or [None])[0]
        if bid: board_ids.append(bid)
    board_ids = sorted(set(board_ids))
    print("BOARD_TOTAL", expected, "BOARD_IDS", board_ids)
    if expected is None or len(board_ids) != 1: raise SystemExit("Missing reconcilable total or unique board id")
    board_id = board_ids[0]
    search = f"https://kearney.recsolu.com/job_boards/{board_id}/search"

    cards = []
    for page in range(1, 51):
        rr = get(s, search, params={"query":"", "filters":"[]", "page_number":page, "job_board_tab_identifier":TAB})
        data = rr.json()
        page_cards = parse_cards(data.get("html"), rr.url, board_id)
        print("PAGE", page, "rows", len(page_cards), "more", data.get("more_requisitions"))
        cards.extend(page_cards)
        if not data.get("more_requisitions"): break
    ids = [x["id"] for x in cards]
    print("RECONCILE", {"raw":len(ids), "unique":len(set(ids)), "expected":expected, "exact":len(ids)==len(set(ids))==expected})
    if len(ids) != len(set(ids)) or len(ids) != expected: raise SystemExit("Inventory mismatch")

    missing = [x for x in cards if not x["location"]]
    targets = [x for x in cards if re.search(r"(?<!\w)(milan|milano|rome|roma|london)(?!\w)", x["location"], re.I)]
    print("TARGET_CARDS", len(targets), [(x["title"], x["location"]) for x in targets])
    print("MISSING_LOCATION", len(missing), [(x["id"], x["title"], x["region"], x["url"]) for x in missing])

    for x in missing[:20]:
        rr = get(s, x["url"])
        text = strip_tags(rr.text)
        snippets = []
        low = text.lower()
        for needle in ("office location", "location", "norway", "milan", "rome", "london"):
            pos = low.find(needle)
            if pos >= 0:
                snippets.append(text[max(0,pos-120):pos+320])
        print("DETAIL", x["id"], x["title"], "SNIPPETS", snippets[:8])

    r2 = get(s, BOARD); p2 = BoardParser(); p2.feed(r2.text)
    totals2 = [int(x.replace(",", "")) for x in re.findall(r"\b([\d,]+)\s+Results\b", " ".join(p2.text), re.I)]
    print("TOTAL_RECHECK", totals2)
    if not totals2 or totals2[0] != expected: raise SystemExit("Total changed during enumeration")


if __name__ == "__main__": main()
