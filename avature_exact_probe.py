import re
import urllib.parse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
RANGE_RE = re.compile(r"([\d,]+)\s*[-–—]\s*([\d,]+)\s+of\s+([\d,]+)(\+?)\s*(?:results?|jobs?|positions?)?", re.I)
DETAIL_RE = re.compile(r"/(?:JobDetail|FolderDetail)/[^?#]+/(\d+)(?:[/?#]|$)", re.I)


def parse(response):
    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    ranges = [
        (int(a.replace(",", "")), int(b.replace(",", "")), int(c.replace(",", "")), bool(plus))
        for a, b, c, plus in RANGE_RE.findall(text)
    ]
    jobs = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = urllib.parse.urljoin(response.url, anchor["href"])
        match = DETAIL_RE.search(urllib.parse.urlparse(href).path)
        if match and match.group(1) not in seen:
            seen.add(match.group(1))
            jobs.append((match.group(1), href, anchor.get_text(" ", strip=True), anchor))
    next_url = None
    link = soup.select_one("a.paginationNextLink")
    if link and link.get("href"):
        next_url = urllib.parse.urljoin(response.url, link["href"])
    return soup, ranges, jobs, next_url


def card_context(anchor):
    out = []
    node = anchor
    for _ in range(6):
        node = node.parent
        if node is None:
            break
        classes = " ".join(node.get("class") or []) if hasattr(node, "get") else ""
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))[:900] if hasattr(node, "get_text") else ""
        out.append((getattr(node, "name", None), classes, text))
    return out


def detail_fields(session, url):
    response = session.get(url, timeout=30)
    soup = BeautifulSoup(response.text, "html.parser")
    fields = []
    for field in soup.select(".article__content__view__field"):
        label = field.select_one(".article__content__view__field__label")
        value = field.select_one(".article__content__view__field__value")
        if label and value:
            fields.append((label.get_text(" ", strip=True), value.get_text(" ", strip=True)))
    return response.status_code, fields


def enumerate_exact(label, start_url):
    session = requests.Session()
    session.headers.update(HEADERS)
    first = session.get(start_url, timeout=30)
    soup, ranges, jobs, next_url = parse(first)
    print("\nCASE", label, "STATUS", first.status_code, "FIRST_RANGE", ranges[:3], "FIRST_JOBS", len(jobs), "NEXT", next_url)
    if first.status_code != 200 or not ranges:
        return
    if jobs:
        print("CARD_CONTEXT", label, jobs[0][0], card_context(jobs[0][3]))
        print("DETAIL_FIELDS", label, jobs[0][0], detail_fields(session, jobs[0][1]))
    initial = ranges[0]
    if initial[0] != 1 or initial[3]:
        print("NOT_EXACT_INITIAL", initial)
        return
    total = initial[2]
    unique = set()
    expected_start = 1
    response = first
    first_ids = [row[0] for row in jobs]
    page = 0
    while True:
        _, page_ranges, page_jobs, page_next = parse(response)
        current = page_ranges[0] if page_ranges else None
        print("PAGE", page + 1, "RANGE", current, "JOBS", len(page_jobs), "NEXT", bool(page_next))
        if current is None or current[2] != total or current[3] or current[0] != expected_start:
            print("RANGE_INCONSISTENCY", current, "EXPECTED", expected_start)
            return
        expected_count = current[1] - current[0] + 1
        if len(page_jobs) != expected_count:
            print("PAGE_COUNT_MISMATCH", len(page_jobs), expected_count)
            return
        overlap = [row[0] for row in page_jobs if row[0] in unique]
        if overlap:
            print("OVERLAP", overlap[:20])
            return
        unique.update(row[0] for row in page_jobs)
        expected_start = current[1] + 1
        if current[1] == total:
            if page_next:
                print("UNEXPECTED_NEXT_ON_LAST_PAGE", page_next)
                return
            break
        if not page_next:
            print("MISSING_NEXT_BEFORE_TOTAL")
            return
        response = session.get(page_next, timeout=30)
        if response.status_code != 200:
            print("NEXT_HTTP_ERROR", response.status_code, response.url)
            return
        page += 1
        if page > 200:
            print("PAGE_LIMIT")
            return
    reread = session.get(start_url, timeout=30)
    _, reread_ranges, reread_jobs, _ = parse(reread)
    stable_first = first_ids == [row[0] for row in reread_jobs]
    stable_total = bool(reread_ranges) and reread_ranges[0][2] == total and not reread_ranges[0][3]
    print("SUMMARY", label, "TOTAL", total, "UNIQUE", len(unique), "STABLE_TOTAL", stable_total, "STABLE_FIRST_PAGE", stable_first)


enumerate_exact("MetLife", "https://www.metlifecareers.com/en_US/ml/SearchJobs")
enumerate_exact("DeloitteCM", "https://deloittecm.avature.net/en_US/careers/SearchJobs/")
