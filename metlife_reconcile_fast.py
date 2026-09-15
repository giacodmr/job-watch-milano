import concurrent.futures
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup

BASE = "https://www.metlifecareers.com/en_US/ml/SearchJobs"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
RANGE_RE = re.compile(r"([\d,]+)\s*[-–—]\s*([\d,]+)\s+of\s+([\d,]+)(\+?)", re.I)


def stable_id(href):
    path = urllib.parse.urlparse(href).path.rstrip("/")
    if "/JobDetail/" not in path and "/FolderDetail/" not in path:
        return None
    tail = path.rsplit("/", 1)[-1]
    return tail if tail.isdigit() else None


def parse(response, show_dom=False):
    soup = BeautifulSoup(response.text, "html.parser")
    legend = soup.select_one(".list-controls__text__legend")
    legend_text = legend.get_text(" ", strip=True) if legend else ""
    m = RANGE_RE.search(legend_text)
    rg = None
    if m:
        rg = tuple(int(x.replace(",", "")) for x in m.groups()[:3]) + (bool(m.group(4)),)
    jobs = []
    page_seen = set()
    articles = soup.select("article.article--result")
    for art in articles:
        chosen = None
        for a in art.find_all("a", href=True):
            href = urllib.parse.urljoin(response.url, a["href"])
            sid = stable_id(href)
            if sid:
                title = a.get_text(" ", strip=True)
                if chosen is None or (title and title.lower() != "apply"):
                    chosen = (sid, href, title, art)
                    if title and title.lower() != "apply":
                        break
        if chosen:
            sid = chosen[0]
            if sid in page_seen:
                raise RuntimeError(f"duplicate id within page: {sid}")
            page_seen.add(sid)
            jobs.append(chosen)
    if show_dom and articles:
        art = articles[0]
        print("FIRST_ARTICLE_TEXT", re.sub(r"\s+", " ", art.get_text(" ", strip=True)))
        for el in art.find_all(True):
            cls = " ".join(el.get("class") or [])
            text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
            if cls or el.name in ("span", "div", "p"):
                print("DOM", el.name, repr(cls), repr(text[:260]))
    return rg, jobs, len(articles)


def get_offset(offset):
    r = requests.get(BASE, params={"listFilterMode": 1, "jobRecordsPerPage": 6, "jobOffset": offset}, headers=HEADERS, timeout=45)
    if r.status_code != 200:
        raise RuntimeError(f"offset {offset}: HTTP {r.status_code}")
    rg, jobs, articles = parse(r)
    return offset, rg, [(j[0], j[1], j[2]) for j in jobs], articles


first = requests.get(BASE, headers=HEADERS, timeout=45)
print("FIRST_STATUS", first.status_code, first.url)
first_rg, first_jobs, first_articles = parse(first, show_dom=True)
print("FIRST_RANGE", first_rg, "ARTICLES", first_articles, "IDS", [x[0] for x in first_jobs])
if first.status_code != 200 or first_rg is None or first_rg[0] != 1 or first_rg[3]:
    raise SystemExit("initial exact total unavailable")
total = first_rg[2]
page_size = first_rg[1] - first_rg[0] + 1
offsets = list(range(0, total, page_size))
print("PLAN", "TOTAL", total, "PAGE_SIZE", page_size, "PAGES", len(offsets))

results = {}
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    futures = {pool.submit(get_offset, off): off for off in offsets}
    for fut in concurrent.futures.as_completed(futures):
        off, rg, jobs, articles = fut.result()
        results[off] = (rg, jobs, articles)

all_ids = []
seen = set()
errors = []
for off in offsets:
    rg, jobs, articles = results[off]
    expected_start = off + 1
    expected_end = min(off + page_size, total)
    expected_count = expected_end - expected_start + 1
    print("PAGE", off, "RANGE", rg, "ARTICLES", articles, "JOBS", len(jobs))
    if rg != (expected_start, expected_end, total, False):
        errors.append(f"offset {off}: range {rg} != expected {(expected_start, expected_end, total, False)}")
    if articles != expected_count:
        errors.append(f"offset {off}: articles {articles} != {expected_count}")
    if len(jobs) != expected_count:
        errors.append(f"offset {off}: IDs {len(jobs)} != {expected_count}")
    for sid, url, title in jobs:
        if sid in seen:
            errors.append(f"offset {off}: overlap {sid}")
        seen.add(sid); all_ids.append(sid)

reread = requests.get(BASE, headers=HEADERS, timeout=45)
rrg, rjobs, rarticles = parse(reread)
first_ids = [x[0] for x in first_jobs]
reread_ids = [x[0] for x in rjobs]
print("REREAD", rrg, "ARTICLES", rarticles, "FIRST_IDS_STABLE", first_ids == reread_ids)
if rrg != first_rg:
    errors.append(f"total/range changed: {first_rg} -> {rrg}")
if first_ids != reread_ids:
    errors.append("first page IDs changed during run")
if len(seen) != total:
    errors.append(f"unique IDs {len(seen)} != total {total}")
print("SUMMARY", "TOTAL", total, "UNIQUE", len(seen), "ERRORS", errors)
if errors:
    raise SystemExit(2)
