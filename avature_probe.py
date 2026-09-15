import json
import re
import urllib.parse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}
TIMEOUT = 30

CASES = {
    "siemens": {
        "url": "https://jobs.siemens-energy.com/en_US/jobs/Jobs",
        "size_param": "folderRecordsPerPage",
        "offset_param": "folderOffset",
        "detail_re": re.compile(r"/FolderDetail/[^?#]+/(\d+)(?:[/?#]|$)", re.I),
        "sizes": [20, 50, 100, 200, 500, 1000],
    },
    "metlife": {
        "url": "https://www.metlifecareers.com/en_US/ml/SearchJobs",
        "size_param": "jobRecordsPerPage",
        "offset_param": "jobOffset",
        "detail_re": re.compile(r"/JobDetail/[^?#]+/(\d+)(?:[/?#]|$)", re.I),
        "sizes": [6, 20, 50, 100, 200, 500],
    },
    "deloitte": {
        "url": "https://deloittecm.avature.net/en_US/careers/SearchJobs/",
        "size_param": "jobRecordsPerPage",
        "offset_param": "jobOffset",
        "detail_re": re.compile(r"/JobDetail/[^?#]+/(\d+)(?:[/?#]|$)", re.I),
        "sizes": [6, 20, 50, 100, 200, 500],
    },
}

RANGE_RE = re.compile(r"\b([\d,.]+)\s*[-–—]\s*([\d,.]+)\s+of\s+([\d,.]+)(\+?)\s*(?:results?|jobs?|positions?)?\b", re.I)
TOTAL_RE = re.compile(r"\bof\s+([\d,.]+)(\+?)\s+(?:results?|jobs?|positions?)\b", re.I)
LOC_WORD_RE = re.compile(r"\b(location|city|country|state|province|region|office|work location|primary location)\b", re.I)
TARGET_RE = re.compile(r"\b(Milan|Milano|Rome|Roma|London)\b", re.I)


def nint(s):
    return int(re.sub(r"\D", "", s))


def fetch(session, url, params=None):
    r = session.get(url, params=params, timeout=TIMEOUT, allow_redirects=True)
    return r


def parse_page(r, detail_re):
    soup = BeautifulSoup(r.text, "html.parser")
    visible = soup.get_text(" ", strip=True)
    ranges = []
    for m in RANGE_RE.finditer(visible):
        ranges.append((nint(m.group(1)), nint(m.group(2)), nint(m.group(3)), bool(m.group(4)), m.group(0)))
    totals = []
    for m in TOTAL_RE.finditer(visible):
        totals.append((nint(m.group(1)), bool(m.group(2)), m.group(0)))
    jobs = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urllib.parse.urljoin(r.url, a["href"])
        m = detail_re.search(urllib.parse.urlparse(href).path)
        if not m:
            continue
        sid = m.group(1)
        if sid in seen:
            continue
        seen.add(sid)
        jobs.append((sid, href, a.get_text(" ", strip=True)))
    nexts = []
    offsets = []
    for a in soup.find_all("a", href=True):
        href = urllib.parse.urljoin(r.url, a["href"])
        text = " ".join(x for x in [a.get_text(" ", strip=True), a.get("title"), a.get("aria-label"), a.get("rel") if isinstance(a.get("rel"), str) else " ".join(a.get("rel") or [])] if x)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        for k in ("folderOffset", "jobOffset"):
            if k in q:
                try:
                    offsets.append((k, int(q[k][0]), href, text))
                except Exception:
                    pass
        if re.search(r"(?i)\bnext\b|>>|>$", text.strip()):
            nexts.append((href, text))
    return soup, visible, ranges, totals, jobs, nexts, offsets


def nearest_context(anchor, max_levels=6):
    out = []
    node = anchor
    for level in range(max_levels):
        node = getattr(node, "parent", None)
        if node is None or getattr(node, "name", None) in (None, "html", "body"):
            break
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))[:900]
        attrs = {k: v for k, v in node.attrs.items() if k in ("class", "id", "data-job-id", "data-id", "data-field")}
        out.append({"level": level + 1, "tag": node.name, "attrs": attrs, "text": text})
    return out


def print_job_context(label, r, detail_re):
    soup = BeautifulSoup(r.text, "html.parser")
    emitted = 0
    for a in soup.find_all("a", href=True):
        href = urllib.parse.urljoin(r.url, a["href"])
        m = detail_re.search(urllib.parse.urlparse(href).path)
        if not m:
            continue
        print(label, "CARD_CONTEXT", m.group(1), json.dumps(nearest_context(a), ensure_ascii=False))
        emitted += 1
        if emitted >= 2:
            break


def print_detail_structure(session, label, jobs):
    for sid, url, title in jobs[:2]:
        r = fetch(session, url)
        print(label, "DETAIL", sid, "STATUS", r.status_code, "FINAL", r.url, "LEN", len(r.text), "TITLE", title)
        if r.status_code != 200:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for dt in soup.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                items.append((dt.get_text(" ", strip=True), dd.get_text(" ", strip=True)))
        for tr in soup.find_all("tr"):
            cells = [x.get_text(" ", strip=True) for x in tr.find_all(["th", "td"])]
            if len(cells) >= 2 and LOC_WORD_RE.search(cells[0]):
                items.append((cells[0], " | ".join(cells[1:])))
        # Generic label/value-looking DOM blocks.
        for el in soup.find_all(["div", "span", "li", "p"]):
            tx = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
            if len(tx) <= 250 and (LOC_WORD_RE.search(tx) or TARGET_RE.search(tx)):
                cls = " ".join(el.get("class") or [])
                if cls and re.search(r"(?i)(field|label|value|location|job|detail|info)", cls):
                    items.append((f"<{el.name} class={cls}>", tx))
        dedup = []
        used = set()
        for item in items:
            key = tuple(item)
            if key not in used:
                used.add(key); dedup.append(item)
        print(label, "DETAIL_FIELDS", sid, json.dumps(dedup[:80], ensure_ascii=False))


def enumerate_case(label, cfg):
    print("\n" + "=" * 120)
    print("CASE", label)
    s = requests.Session(); s.headers.update(HEADERS)
    best = None
    for size in cfg["sizes"]:
        params = {cfg["size_param"]: size, "listFilterMode": 1}
        r = fetch(s, cfg["url"], params=params)
        soup, visible, ranges, totals, jobs, nexts, offsets = parse_page(r, cfg["detail_re"])
        print("SIZE_TEST", size, "STATUS", r.status_code, "FINAL", r.url, "LEN", len(r.text), "RANGES", ranges[:5], "TOTALS", totals[:5], "JOBS", len(jobs), "NEXT", nexts[:2], "MAX_OFFSET_LINK", max([x[1] for x in offsets], default=None))
        if r.status_code == 200 and jobs and (best is None or len(jobs) > best[0]):
            best = (len(jobs), size, r, ranges, totals, jobs)
    if best is None:
        print("NO_ENUMERABLE_PAGE")
        return

    _, size, first_r, ranges, totals, first_jobs = best
    print("CHOSEN_SIZE", size)
    print_job_context(label, first_r, cfg["detail_re"])
    print_detail_structure(s, label, first_jobs)

    # Exact total is accepted only if the range/total has no '+' cap.
    initial_total = None
    for start, end, total, capped, raw in ranges:
        if start == 1 and not capped:
            initial_total = total
            break
    if initial_total is None:
        for total, capped, raw in totals:
            if not capped:
                initial_total = total
                break
    print("INITIAL_TOTAL_EXACT", initial_total)

    rows = []
    seen = set()
    offset = 0
    page = 0
    prior_end = 0
    max_pages = 300
    final_range = None
    while page < max_pages:
        params = {cfg["size_param"]: size, cfg["offset_param"]: offset, "listFilterMode": 1}
        r = fetch(s, cfg["url"], params=params)
        if r.status_code != 200:
            print("ENUM_HTTP_STOP", page, offset, r.status_code, r.url); break
        soup, visible, pranges, ptotals, jobs, nexts, offsets = parse_page(r, cfg["detail_re"])
        chosen_range = pranges[0] if pranges else None
        print("ENUM_PAGE", page + 1, "OFFSET", offset, "RANGE", chosen_range, "JOBS", len(jobs), "NEXT", nexts[:1])
        if chosen_range:
            final_range = chosen_range
            start, end, total, capped, raw = chosen_range
            if page and start != prior_end + 1:
                print("RANGE_GAP", prior_end, start)
                break
            prior_end = end
            if initial_total is not None and (capped or total != initial_total):
                print("TOTAL_CHANGED", initial_total, chosen_range)
                break
        if not jobs:
            print("NO_JOBS_STOP"); break
        overlap = [sid for sid, _, _ in jobs if sid in seen]
        if overlap:
            print("OVERLAP", overlap[:20]); break
        for row in jobs:
            seen.add(row[0]); rows.append(row)
        # Prefer actual Next contract from rendered page.
        next_offset = None
        for href, text in nexts:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            if cfg["offset_param"] in q:
                try:
                    next_offset = int(q[cfg["offset_param"]][0]); break
                except Exception:
                    pass
        if next_offset is None:
            print("ENUM_END_NO_NEXT", "UNIQUE", len(seen), "FINAL_RANGE", final_range)
            break
        if next_offset <= offset:
            print("NON_ADVANCING_NEXT", offset, next_offset); break
        offset = next_offset
        page += 1
    else:
        print("MAX_PAGE_STOP", max_pages)

    reread = fetch(s, cfg["url"], params={cfg["size_param"]: size, "listFilterMode": 1})
    _, _, rranges, rtotals, rjobs, _, _ = parse_page(reread, cfg["detail_re"])
    print("REREAD", "STATUS", reread.status_code, "RANGES", rranges[:3], "TOTALS", rtotals[:3], "JOBS", len(rjobs))
    print("ENUM_SUMMARY", "UNIQUE", len(seen), "INITIAL_EXACT", initial_total, "FINAL_RANGE", final_range, "FIRST_IDS_STABLE", [x[0] for x in first_jobs[:5]] == [x[0] for x in rjobs[:5]])


for label, cfg in CASES.items():
    enumerate_case(label, cfg)
