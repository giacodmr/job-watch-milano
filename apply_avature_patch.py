from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
COLLECTOR = ROOT / 'collector.py'

AVATURE_CODE = r'''

# === JOB WATCH V1.7 AVATURE STRICT PUBLIC-INVENTORY COLLECTOR ===
AVATURE_SCOPE_NAME = "Avature server-rendered public inventory"
AVATURE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}
AVATURE_RANGE_RE = re.compile(
    r"\b([\d,]+)\s*[-–—]\s*([\d,]+)\s+of\s+([\d,]+)(\+?)\s*(?:results?|jobs?|positions?)?\b",
    re.I,
)
AVATURE_ZERO_RE = re.compile(r"^\s*0\s+(?:results?|jobs?|positions?)\s*$", re.I)
AVATURE_PAGE_WORKERS = 4
AVATURE_MAX_PAGES = 200


def avature_family(company) -> bool:
    family = clean_text(((company.get("ats") or {}).get("family"))) or ""
    return "avature" in family.casefold()


class AvaturePageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.legends = []
        self.cards = []
        self.next_href = None
        self._legend_tag = None
        self._legend_depth = 0
        self._legend_parts = []
        self._card = None
        self._anchor = None
        self._capture_location = False
        self._location_tag = None
        self._location_parts = []
        self._capture_posted = False
        self._posted_tag = None
        self._posted_parts = []
        self._capture_ref = False
        self._ref_tag = None
        self._ref_parts = []

    @staticmethod
    def _attrs(attrs):
        return {str(k).casefold(): (v or "") for k, v in attrs}

    @staticmethod
    def _classes(attrs_dict):
        return {x.casefold() for x in str(attrs_dict.get("class") or "").split() if x}

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        d = self._attrs(attrs)
        classes = self._classes(d)

        if self._legend_tag is None and "list-controls__text__legend" in classes:
            self._legend_tag = tag
            self._legend_depth = 1
            self._legend_parts = []
        elif self._legend_tag is not None and tag == self._legend_tag:
            self._legend_depth += 1

        if tag == "article" and "article--result" in classes and self._card is None:
            self._card = {"text": [], "anchors": [], "location": None, "posted": None, "ref": None}

        if self._card is not None:
            if tag == "a":
                self._anchor = {"href": d.get("href"), "text": []}
            if "list-item-location" in classes:
                self._capture_location = True
                self._location_tag = tag
                self._location_parts = []
            if "list-item-posted" in classes:
                self._capture_posted = True
                self._posted_tag = tag
                self._posted_parts = []
            if "list-item-ref" in classes:
                self._capture_ref = True
                self._ref_tag = tag
                self._ref_parts = []

        if tag == "a" and "paginationnextlink" in classes and d.get("href"):
            self.next_href = d["href"]

    def handle_data(self, data):
        if self._legend_tag is not None:
            self._legend_parts.append(data)
        if self._card is not None:
            self._card["text"].append(data)
        if self._anchor is not None:
            self._anchor["text"].append(data)
        if self._capture_location:
            self._location_parts.append(data)
        if self._capture_posted:
            self._posted_parts.append(data)
        if self._capture_ref:
            self._ref_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.casefold()
        if self._anchor is not None and tag == "a":
            self._anchor["text"] = " ".join(" ".join(self._anchor["text"]).split())
            self._card["anchors"].append(self._anchor)
            self._anchor = None

        if self._capture_location and tag == self._location_tag:
            self._card["location"] = " ".join(" ".join(self._location_parts).split()) or None
            self._capture_location = False
            self._location_tag = None
            self._location_parts = []
        if self._capture_posted and tag == self._posted_tag:
            self._card["posted"] = " ".join(" ".join(self._posted_parts).split()) or None
            self._capture_posted = False
            self._posted_tag = None
            self._posted_parts = []
        if self._capture_ref and tag == self._ref_tag:
            self._card["ref"] = " ".join(" ".join(self._ref_parts).split()) or None
            self._capture_ref = False
            self._ref_tag = None
            self._ref_parts = []

        if self._card is not None and tag == "article":
            self._card["text"] = " ".join(" ".join(self._card["text"]).split())
            self.cards.append(self._card)
            self._card = None
            self._anchor = None

        if self._legend_tag is not None and tag == self._legend_tag:
            self._legend_depth -= 1
            if self._legend_depth == 0:
                value = " ".join(" ".join(self._legend_parts).split())
                if value:
                    self.legends.append(value)
                self._legend_tag = None
                self._legend_parts = []


def _avature_get(url: str):
    try:
        r = get_session().get(url, headers=AVATURE_HEADERS, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as e:
        raise NotCheckable(f"Avature public inventory request unavailable: {e}") from e
    if r.status_code != 200:
        raise NotCheckable(f"Avature public inventory unavailable: HTTP {r.status_code}")
    ctype = (r.headers.get("content-type") or "").casefold()
    if "html" not in ctype and "xhtml" not in ctype:
        raise NotCheckable(f"Avature public inventory returned non-HTML content: {ctype or 'unknown'}")
    return r


def _avature_stable_id(base_url: str, href: str | None):
    if not href:
        return None, None
    url = urljoin(base_url, html.unescape(href))
    path = urlparse(url).path.rstrip("/")
    folded = path.casefold()
    if "/jobdetail/" not in folded and "/folderdetail/" not in folded:
        return None, None
    tail = path.rsplit("/", 1)[-1]
    if not tail.isdigit():
        return None, None
    return tail, url


def _avature_parse_range(parser: AvaturePageParser):
    values = set()
    saw_capped = False
    for legend in parser.legends:
        m = AVATURE_RANGE_RE.search(legend)
        if m:
            start = int(m.group(1).replace(",", ""))
            end = int(m.group(2).replace(",", ""))
            total = int(m.group(3).replace(",", ""))
            capped = bool(m.group(4))
            saw_capped = saw_capped or capped
            values.add((start, end, total, capped))
        elif AVATURE_ZERO_RE.fullmatch(legend):
            values.add((0, 0, 0, False))
    if saw_capped:
        raise NotCheckable("Avature inventory exposes only a capped result total")
    if len(values) != 1:
        raise NotCheckable(f"Avature inventory does not expose one exact reconciliable result range: {sorted(values)}")
    return next(iter(values))


def _avature_parse_card(base_url: str, card: dict):
    candidates = {}
    title = None
    canonical = None
    for anchor in card.get("anchors") or []:
        sid, url = _avature_stable_id(base_url, anchor.get("href"))
        if not sid:
            continue
        candidates[sid] = url
        text = clean_text(anchor.get("text"))
        if text and text.casefold() not in {"apply", "view", "view job", "learn more"} and title is None:
            title = text
            canonical = url
    if len(candidates) != 1:
        raise NotCheckable(f"Avature result card does not expose exactly one stable numeric requisition ID: {sorted(candidates)}")
    source_id = next(iter(candidates))
    canonical = canonical or candidates[source_id]

    ref = clean_text(card.get("ref"))
    if ref:
        m = re.search(r"\b(?:Job|Requisition)\s*ID\s*:\s*(\d+)\b", ref, re.I)
        if m and m.group(1) != source_id:
            raise NotCheckable(f"Avature card ID mismatch: link={source_id}, displayed={m.group(1)}")

    location = clean_text(card.get("location"))
    posted = clean_text(card.get("posted"))
    if not location:
        # Strict fallback for Avature themes that render the same labelled ID line
        # without list-item-location class. It is used only when title + displayed
        # Job ID delimit an unambiguous location string.
        text = clean_text(card.get("text")) or ""
        m = re.search(rf"^(.*?)\s*[•·|]\s*(?:Job|Requisition)\s*ID\s*:\s*{re.escape(source_id)}\b", text, re.I)
        if m and title:
            prefix = m.group(1).strip()
            if prefix.startswith(title):
                location = clean_text(prefix[len(title):].strip(" -–—|•·"))
    if not title:
        raise NotCheckable(f"Avature requisition {source_id} has no stable public title")
    return {
        "source_id": source_id,
        "url": canonical,
        "title": title,
        "location": location,
        "published_at": posted,
    }


def _avature_parse_page(response):
    parser = AvaturePageParser()
    parser.feed(response.text)
    page_range = _avature_parse_range(parser)
    rows = [_avature_parse_card(response.url, card) for card in parser.cards]
    ids = [row["source_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise NotCheckable("Avature page repeats a requisition ID within the same result range")
    next_url = urljoin(response.url, parser.next_href) if parser.next_href else None
    return page_range, rows, next_url


def _avature_offset_contract(next_url: str | None, page_size: int):
    if not next_url:
        return None, None
    parsed = urlparse(next_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    found = []
    for key in ("jobOffset", "folderOffset"):
        if key in params and len(params[key]) == 1:
            try:
                found.append((key, int(params[key][0])))
            except (TypeError, ValueError):
                pass
    if len(found) != 1 or found[0][1] != page_size:
        raise NotCheckable(f"Avature pagination does not expose the expected zero-based offset contract: {found}")
    return found[0][0], next_url


def _avature_page_url(template_url: str, offset_key: str, offset: int) -> str:
    from urllib.parse import parse_qsl, urlencode, urlunparse
    p = urlparse(template_url)
    pairs = parse_qsl(p.query, keep_blank_values=True)
    replaced = False
    out = []
    for key, value in pairs:
        if key == offset_key:
            if not replaced:
                out.append((key, str(int(offset))))
                replaced = True
        else:
            out.append((key, value))
    if not replaced:
        out.append((offset_key, str(int(offset))))
    return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(out), p.fragment))


def _avature_fetch_offset(template_url: str, offset_key: str, offset: int):
    url = _avature_page_url(template_url, offset_key, offset)
    r = _avature_get(url)
    page_range, rows, _next = _avature_parse_page(r)
    return offset, page_range, rows


def _collect_avature_once(company):
    name = company.get("company")
    ats = company.get("ats") or {}
    verification = company.get("verification") or {}
    inventory = clean_text(ats.get("inventory_url"))
    if not inventory:
        raise NotCheckable("Avature inventory URL missing")
    if verification.get("full_inventory_possible") is not True:
        raise NotCheckable("Mapped Avature portal is not proven to cover the full public company inventory")

    first = _avature_get(inventory)
    first_range, first_rows, next_url = _avature_parse_page(first)
    start, end, expected_total, capped = first_range
    if capped:
        raise NotCheckable("Avature inventory exposes only a capped result total")
    if expected_total == 0:
        if first_rows:
            raise NotCheckable("Avature zero-result inventory unexpectedly exposes requisitions")
        return {
            "coverage": "VERIFIED",
            "collector": "avature_public_html_v17",
            "inventory_count": 0,
            "jobs": [],
            "source_url": first.url,
        }
    if start != 1 or end < start:
        raise NotCheckable(f"Avature initial range is not exhaustive-from-zero: {first_range}")
    page_size = end - start + 1
    if len(first_rows) != page_size:
        raise NotCheckable(f"Avature first-page reconciliation mismatch: rows={len(first_rows)}, range={first_range}")
    if expected_total < page_size:
        raise NotCheckable(f"Avature invalid total/range contract: {first_range}")
    pages = (expected_total + page_size - 1) // page_size
    if pages > AVATURE_MAX_PAGES:
        raise NotCheckable(f"Avature inventory exceeds safe exhaustive-page limit: pages={pages}")

    page_rows = {0: first_rows}
    if expected_total > page_size:
        offset_key, template_url = _avature_offset_contract(next_url, page_size)
        offsets = list(range(page_size, expected_total, page_size))
        with ThreadPoolExecutor(max_workers=min(AVATURE_PAGE_WORKERS, len(offsets))) as pool:
            futures = {
                pool.submit(_avature_fetch_offset, template_url, offset_key, offset): offset
                for offset in offsets
            }
            for fut in as_completed(futures):
                offset = futures[fut]
                try:
                    actual_offset, page_range, rows = fut.result()
                except NotCheckable:
                    raise
                except Exception as e:
                    raise NotCheckable(f"Avature page offset {offset} could not be validated: {e}") from e
                expected_start = actual_offset + 1
                expected_end = min(actual_offset + page_size, expected_total)
                expected_range = (expected_start, expected_end, expected_total, False)
                if page_range != expected_range:
                    raise NotCheckable(f"Avature range/total changed during enumeration: offset={actual_offset}, got={page_range}, expected={expected_range}")
                expected_count = expected_end - expected_start + 1
                if len(rows) != expected_count:
                    raise NotCheckable(f"Avature page reconciliation mismatch at offset {actual_offset}: rows={len(rows)}, expected={expected_count}")
                page_rows[actual_offset] = rows
    elif next_url:
        raise NotCheckable("Avature single-page inventory unexpectedly exposes a Next page")

    inventory_rows = []
    seen = set()
    for offset in sorted(page_rows):
        for row in page_rows[offset]:
            sid = row["source_id"]
            if sid in seen:
                raise NotCheckable(f"Avature pagination overlaps requisition ID {sid}")
            seen.add(sid)
            inventory_rows.append(row)
    if len(seen) != expected_total:
        raise NotCheckable(f"Avature global reconciliation mismatch: unique_ids={len(seen)}, total={expected_total}")

    missing_locations = [row["source_id"] for row in inventory_rows if not clean_text(row.get("location"))]
    if missing_locations:
        raise NotCheckable(
            f"Avature inventory reconciled but structured location metadata is incomplete: missing={len(missing_locations)}, total={expected_total}"
        )

    # Stable-total and stable-front-page check after exhaustive enumeration.
    final = _avature_get(first.url)
    final_range, final_rows, _final_next = _avature_parse_page(final)
    if final_range != first_range:
        raise NotCheckable(f"Avature total/range changed during enumeration: {first_range}->{final_range}")
    if [x["source_id"] for x in final_rows] != [x["source_id"] for x in first_rows]:
        raise NotCheckable("Avature first-page requisitions changed during enumeration")

    jobs = []
    for row in inventory_rows:
        if not location_matches(row.get("location")):
            continue
        jobs.append(
            compact_job(
                name,
                row["source_id"],
                title=row.get("title"),
                location=row.get("location"),
                published_at=row.get("published_at"),
                canonical=row.get("url"),
                apply_url=row.get("url"),
            )
        )
    return {
        "coverage": "VERIFIED",
        "collector": "avature_public_html_v17",
        "inventory_count": expected_total,
        "jobs": jobs,
        "source_url": first.url,
    }


def collect_avature(company):
    last_error = None
    for attempt in range(2):
        try:
            return _collect_avature_once(company)
        except NotCheckable as e:
            last_error = e
            msg = str(e).casefold()
            retryable = any(
                token in msg
                for token in (
                    "changed during enumeration",
                    "pagination overlaps",
                    "reconciliation mismatch",
                    "first-page requisitions changed",
                )
            )
            if not retryable or attempt:
                raise
    raise NotCheckable(f"Avature inventory remained unstable after retry: {last_error}")


_choose_v16 = choose
def choose(company):
    if avature_family(company):
        return collect_avature
    return _choose_v16(company)


_collect_batch_v16 = collect_batch
def collect_batch(batch: str, workers: int = DEFAULT_WORKERS):
    payload = _collect_batch_v16(batch, workers=workers)
    payload["version"] = "1.7"
    scope = list(payload.get("collector_scope") or [])
    if AVATURE_SCOPE_NAME not in scope:
        scope.append(AVATURE_SCOPE_NAME)
    payload["collector_scope"] = scope
    write_json(ROOT / f"current_jobs_{batch}.json", payload)
    return payload
'''

text = COLLECTOR.read_text(encoding='utf-8')
marker = '\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
if 'JOB WATCH V1.7 AVATURE STRICT PUBLIC-INVENTORY COLLECTOR' not in text:
    if text.count(marker) != 1:
        raise SystemExit('collector main marker not found exactly once')
    text = text.replace(marker, AVATURE_CODE + marker)
    COLLECTOR.write_text(text, encoding='utf-8')


def load(path):
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def save(path, data):
    with path.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')


def company(data, name):
    matches = [x for x in data.get('companies', []) if x.get('company') == name]
    if len(matches) != 1:
        raise SystemExit(f'{name}: expected one mapping, got {len(matches)}')
    return matches[0]


def recompute_summary(data):
    levels = {'FULL': 0, 'STRONG': 0, 'PARTIAL': 0, 'OPAQUE': 0}
    for row in data.get('companies', []):
        level = ((row.get('verification') or {}).get('level'))
        if level in levels:
            levels[level] += 1
    summary = data.setdefault('summary', {})
    summary['companies_analyzed'] = len(data.get('companies', []))
    for k, v in levels.items():
        summary[k] = v

# MetLife: exact global public inventory proved 462/462 on 2026-09-15.
p = ROOT / 'ats_mapping_jw1.json'; d = load(p); row = company(d, 'MetLife')
if 'avature' not in str((row.get('ats') or {}).get('family') or '').casefold(): raise SystemExit('MetLife ATS family changed')
v = row.setdefault('verification', {})
v.update({
    'level': 'FULL',
    'method': 'official_avature_searchjobs_exact_reconciliation',
    'location_filter_supported': True,
    'total_count_available': True,
    'full_inventory_possible': True,
    'pagination': 'Server-rendered SearchJobs inventory; tenant-fixed page size 6; zero-based jobOffset; numeric stable JobDetail ID.',
})
row['job_watch_method'] = {
    'primary': 'Enumerate the official Avature SearchJobs inventory across every jobOffset page; require exact range/total reconciliation, unique stable IDs, stable reread, and structured list-item-location metadata.',
    'fallback': 'If the public SearchJobs contract is capped, unstable, blocked, or loses structured location metadata, return NOT_CHECKED rather than infer completeness.'
}
row['limitations'] = [
    'Validated from GitHub Actions on 2026-09-15: 462 declared results, 462 result articles, 462 unique stable IDs across 77 pages, no overlap/gap, and stable first page/total on reread.',
    'Avature emits both /JobDetail/<slug>/<id> and /JobDetail/<id>; the stable ID is the numeric final path segment.',
    'jobRecordsPerPage is tenant-fixed at 6 on this portal; larger requested sizes are ignored, so exhaustive enumeration follows jobOffset.',
    'Location is structurally exposed on each result card as list-item-location.'
]
row['last_mapped'] = '2026-09-15'; recompute_summary(d); save(p, d)

# Siemens Energy: live portal is public Avature but cannot satisfy strict global reconciliation.
p = ROOT / 'ats_mapping_jw3.json'; d = load(p); row = company(d, 'Siemens Energy')
if 'avature' not in str((row.get('ats') or {}).get('family') or '').casefold(): raise SystemExit('Siemens Energy ATS family changed')
v = row.setdefault('verification', {})
v.update({
    'level': 'STRONG',
    'method': 'official_avature_inventory_capped_nonreconcilable',
    'total_count_available': False,
    'full_inventory_possible': False,
    'pagination': 'Server-rendered Jobs inventory; tenant-fixed page size 20; zero-based folderOffset; numeric stable FolderDetail ID.',
})
row['job_watch_method'] = {
    'primary': 'Use the official Siemens Energy Avature Jobs inventory only for discovery; do not claim exhaustive coverage while the global legend is capped or pages overlap.',
    'fallback': 'Keep NOT_CHECKED unless a future public contract exposes an exact stable total and gap-free unique-ID enumeration.'
}
row['limitations'] = [
    'Live GitHub Actions probe on 2026-09-15 exposed only a capped global legend (1-20 of 999+), not an exact total.',
    'folderRecordsPerPage remained fixed at 20 even when larger values were requested.',
    'Live paging showed a repeated stable requisition ID within the first 60 displayed positions, so gap-free global enumeration was not demonstrated.',
    'Detail pages expose structured Country / State-Province-County / City location data, but that does not repair the global completeness failure.'
]
row['last_mapped'] = '2026-09-15'; recompute_summary(d); save(p, d)

# Deloitte CM: technical tenant inventory reconciles, but it is not the whole Deloitte/Monitor company scope (notably UK/London).
p = ROOT / 'ats_mapping_jw2.json'; d = load(p); row = company(d, 'Deloitte / Monitor Deloitte')
if 'avature' not in str((row.get('ats') or {}).get('family') or '').casefold(): raise SystemExit('Deloitte ATS family changed')
v = row.setdefault('verification', {})
v.update({
    'level': 'PARTIAL',
    'method': 'official_avature_tenant_exact_but_company_scope_segmented',
    'total_count_available': True,
    'full_inventory_possible': False,
    'pagination': 'Deloitte Central Mediterranean Avature tenant: page size 6, zero-based jobOffset, exact total and numeric stable JobDetail IDs.',
})
row['limitations'] = [
    'Deloitte Central Mediterranean Avature was technically reconciled on 2026-09-15: 395 declared results and 395 unique stable IDs through the last page with stable reread.',
    'That tenant is a regional/member-firm inventory and does not prove the complete Deloitte / Monitor Deloitte public company inventory, including UK/London roles.',
    'Company-level coverage therefore remains NOT_CHECKED despite the tenant-level enumeration proof.'
]
row['last_mapped'] = '2026-09-15'; recompute_summary(d); save(p, d)

print('Avature v1.7 collector and mapping evidence applied')
