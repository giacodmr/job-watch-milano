from pathlib import Path

path = Path("collector.py")
text = path.read_text(encoding="utf-8")
marker = "# === JOB WATCH V1.5 SUCCESSFACTORS STRICT INVENTORY ==="
if marker in text:
    raise SystemExit("strict SuccessFactors patch already present")

needle = '\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
if needle not in text:
    raise SystemExit("collector.py final main guard not found")

block = r'''
# === JOB WATCH V1.5 SUCCESSFACTORS STRICT INVENTORY ===
# Tighten discovery and add Career Site Builder tile pagination. A mapped /go/
# URL is acceptable when the mapping itself points there and the page proves a
# total + inventory. Discovery from a generic landing page is restricted to an
# evidenced same-host /search/ or /viewalljobs/ endpoint; arbitrary category
# /go/ links are never promoted to exhaustive inventory automatically.

SF_MAX_PAGES = MAX_PAGES
SF_TILE_INIT_RE = re.compile(r"j2w\.SearchResults\.init\s*\(\s*\{(.*?)\}\s*\)\s*;?", re.I | re.S)
SF_TILE_PER_PAGE_RE = re.compile(r'data-per-page=["\'](\d+)["\']', re.I)

_SFPageParser_pre_strict = SFPageParser
class SFPageParser(_SFPageParser_pre_strict):
    FIELD_ID_RE = re.compile(r"^job-(\d+)-desktop-section-([A-Za-z0-9_-]+)-(label|value)$", re.I)

    def __init__(self):
        super().__init__()
        self.form_actions = []
        self.card_fields = {}
        self._sf_field_capture = None

    def handle_starttag(self, tag, attrs):
        a = self._attrs(attrs)
        if tag.casefold() == "form" and a.get("action"):
            self.form_actions.append(a.get("action"))
        if self._sf_field_capture is not None:
            self._sf_field_capture["depth"] += 1
        else:
            field_id = a.get("id")
            m = self.FIELD_ID_RE.match(field_id or "")
            if m:
                self._sf_field_capture = {
                    "job_id": m.group(1),
                    "field": m.group(2).casefold(),
                    "kind": m.group(3).casefold(),
                    "depth": 1,
                    "text": [],
                }
        super().handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self._sf_field_capture is not None:
            s = clean_text(data)
            if s:
                self._sf_field_capture["text"].append(s)
        super().handle_data(data)

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if self._sf_field_capture is None:
            return
        self._sf_field_capture["depth"] -= 1
        if self._sf_field_capture["depth"] > 0:
            return
        cap = self._sf_field_capture
        value = clean_text(" ".join(cap.get("text") or []))
        if value:
            fields = self.card_fields.setdefault(cap["job_id"], {})
            fields.setdefault(cap["field"], {})[cap["kind"]] = value
        self._sf_field_capture = None


def _sf_card_values(parser, job_url):
    return getattr(parser, "card_fields", {}).get(str(sf_job_source_id(job_url)), {}) or {}


def _sf_card_location(parser, job_url):
    fields = _sf_card_values(parser, job_url)
    primary, secondary = [], []
    for field, pair in fields.items():
        value = clean_text((pair or {}).get("value"))
        label = clean_text((pair or {}).get("label")) or ""
        if not value:
            continue
        key = f"{field} {label}".casefold()
        if any(token in key for token in ("location", "località", "localita", "luogo", "city", "città", "citta", "stadt", "ville", "ciudad")):
            primary.append(value)
        elif any(token in key for token in ("country", "paese", "region", "regione", "land", "pays", "país", "pais")):
            secondary.append(value)
    out = []
    for value in primary + secondary:
        if value not in out:
            out.append(value)
    return " | ".join(out) if out else None


def _sf_card_date(parser, job_url):
    for field, pair in _sf_card_values(parser, job_url).items():
        value = clean_text((pair or {}).get("value"))
        label = clean_text((pair or {}).get("label")) or ""
        key = f"{field} {label}".casefold()
        if value and any(token in key for token in ("date", "data", "datum", "posting", "publication", "fecha")):
            return value
    return None


_merge_sf_page_jobs_pre_strict = merge_sf_page_jobs
def merge_sf_page_jobs(base: str, parser: SFPageParser) -> list[dict]:
    jobs = _merge_sf_page_jobs_pre_strict(base, parser)
    for job in jobs:
        if not clean_text(job.get("location")):
            job["location"] = _sf_card_location(parser, job["url"])
        if not clean_text(job.get("published_at")):
            job["published_at"] = _sf_card_date(parser, job["url"])
    return jobs


def _sf_load_page_strict(url: str):
    html_text, final_url = sf_get_html(url)
    parser = SFPageParser()
    parser.feed(html_text)
    return html_text, final_url, parser


def _sf_is_exhaustive_search_path(url: str) -> bool:
    path = urlparse(url).path.casefold().rstrip("/")
    return path.endswith("/search") or path.endswith("/viewalljobs") or "/search/" in (path + "/") or "/viewalljobs/" in (path + "/")


def _sf_find_exhaustive_search_url(base: str, parser: SFPageParser) -> str | None:
    candidates = []
    # Form actions are stronger evidence than navigation links.
    for action in getattr(parser, "form_actions", []) or []:
        u = normalize_abs_url(base, clean_text(action))
        if u and same_host(base, u) and _sf_is_exhaustive_search_path(u) and is_unfiltered_search_url(u):
            candidates.append((0, u))
    for anchor in parser.anchors:
        u = normalize_abs_url(base, anchor.get("href"))
        if u and same_host(base, u) and _sf_is_exhaustive_search_path(u) and is_unfiltered_search_url(u):
            candidates.append((1, u))
    if not candidates:
        return None
    dedup = {}
    for priority, u in candidates:
        dedup[u] = min(priority, dedup.get(u, priority))
    return sorted(dedup, key=lambda u: (dedup[u], 0 if not urlparse(u).query else 1, len(urlparse(u).path), len(u)))[0]


def _sf_prepare_inventory_strict(company):
    ats = company.get("ats", {})
    inventory = clean_text(ats.get("inventory_url"))
    if not inventory:
        raise NotCheckable("SuccessFactors inventory URL missing")

    page_html, current_url, parser = _sf_load_page_strict(inventory)
    jobs = merge_sf_page_jobs(current_url, parser)
    total = parse_sf_total(parser.visible_text)

    # Trust a mapped URL (including mapped /go/) only when it proves an inventory.
    if total is not None and (total == 0 or jobs):
        return page_html, current_url, parser, jobs, total

    discovered = _sf_find_exhaustive_search_url(current_url, parser)
    if not discovered or discovered == current_url:
        if total is not None and total > 0 and not jobs:
            raise NotCheckable(f"SuccessFactors inventory exposes total={total} but no stable public job links")
        raise NotCheckable("No evidenced same-host exhaustive /search/ or /viewalljobs/ inventory exposed by portal")

    d_html, d_url, d_parser = _sf_load_page_strict(discovered)
    d_jobs = merge_sf_page_jobs(d_url, d_parser)
    d_total = parse_sf_total(d_parser.visible_text)
    if d_total is None:
        raise NotCheckable("Evidenced SuccessFactors search page has no reconcilable inventory total")
    if d_total > 0 and not d_jobs:
        raise NotCheckable(f"SuccessFactors search exposes total={d_total} but no stable public job links")
    return d_html, d_url, d_parser, d_jobs, d_total


def _sf_require_complete_locations(inventory_jobs, expected_total):
    missing = [u for u, item in inventory_jobs.items() if not clean_text(item.get("location"))]
    if missing:
        raise NotCheckable(
            f"SuccessFactors inventory reconciled but location metadata is incomplete: missing={len(missing)}, total={expected_total}"
        )


def _sf_finish_verified(name, inventory_jobs, source_url, collector_name):
    expected_total = len(inventory_jobs)
    _sf_require_complete_locations(inventory_jobs, expected_total)
    jobs = []
    for raw in inventory_jobs.values():
        loc = clean_text(raw.get("location"))
        if not location_matches(loc):
            continue
        jobs.append(compact_job(
            name,
            sf_job_source_id(raw["url"]),
            title=raw.get("title"),
            location=loc,
            published_at=raw.get("published_at"),
            canonical=raw.get("url"),
            apply_url=raw.get("url"),
        ))
    return {
        "coverage": "VERIFIED",
        "collector": collector_name,
        "inventory_count": expected_total,
        "jobs": jobs,
        "source_url": source_url,
    }


def _collect_successfactors_paged_strict(company):
    name = company.get("company")
    page_html, current_url, parser, first_jobs, expected_total = _sf_prepare_inventory_strict(company)
    source_url = current_url
    if expected_total == 0:
        return {
            "coverage": "VERIFIED",
            "collector": "successfactors_jobs2web_metadata_v15",
            "inventory_count": 0,
            "jobs": [],
            "source_url": source_url,
        }

    visited = set()
    inventory_jobs = {}
    page_count = 0
    while True:
        page_count += 1
        if page_count > SF_MAX_PAGES:
            raise NotCheckable("SuccessFactors inventory exceeds safe exhaustive-page limit")
        visited.add(current_url)
        page_total = parse_sf_total(parser.visible_text)
        if page_total is not None and page_total != expected_total:
            raise NotCheckable(f"SuccessFactors total changed during pagination: {expected_total}->{page_total}")
        before = len(inventory_jobs)
        for item in merge_sf_page_jobs(current_url, parser):
            inventory_jobs[item["url"]] = item
        if len(inventory_jobs) == expected_total:
            break
        if len(inventory_jobs) > expected_total:
            raise NotCheckable(f"SuccessFactors reconciliation overflow: retrieved={len(inventory_jobs)}, total={expected_total}")
        if len(inventory_jobs) == before and before:
            raise NotCheckable(f"SuccessFactors pagination repeated a page: retrieved={len(inventory_jobs)}, total={expected_total}")
        nxt = _sf_fetch_validated_next(current_url, parser, expected_total, visited)
        if not nxt:
            raise NotCheckable(f"SuccessFactors inventory not exhaustible: retrieved={len(inventory_jobs)}, total={expected_total}")
        page_html, current_url, parser = nxt

    # Stable-total check after enumeration.
    _final_html, _final_url, final_parser = _sf_load_page_strict(source_url)
    final_total = parse_sf_total(final_parser.visible_text)
    if final_total != expected_total:
        raise NotCheckable(f"SuccessFactors total changed during enumeration: {expected_total}->{final_total}")
    return _sf_finish_verified(name, inventory_jobs, source_url, "successfactors_jobs2web_metadata_v15")


def sf_tile_config(page_html: str, base_url: str):
    blocks = SF_TILE_INIT_RE.findall(page_html)
    if len(blocks) != 1:
        return None
    block = blocks[0]
    endpoint_m = re.search(r'\bapiEndpoint\s*:\s*["\']([^"\']+)["\']', block, re.I)
    query_m = re.search(r'\bsearchQuery\s*:\s*["\']([^"\']*)["\']', block, re.I)
    per_m = SF_TILE_PER_PAGE_RE.search(page_html)
    if not endpoint_m or not query_m or not per_m:
        return None
    endpoint = clean_text(endpoint_m.group(1))
    query = html.unescape(query_m.group(1)).strip()
    if not endpoint or not re.fullmatch(r"[A-Za-z0-9_-]+", endpoint) or "startrow=" in query.casefold():
        return None
    try:
        per_page = int(per_m.group(1))
    except (TypeError, ValueError):
        return None
    if per_page <= 0 or per_page > 100:
        return None

    brand = ""
    brand_matches = re.findall(r"[\"']brand[\"']\s*:\s*[\"']([^\"']*)[\"']", page_html, re.I)
    if brand_matches:
        unique_brands = {clean_text(x) or "" for x in brand_matches}
        if len(unique_brands) != 1:
            return None
        brand = next(iter(unique_brands))
    if brand:
        if not SAFE_TENANT_RE.fullmatch(brand):
            return None
        endpoint_url = urljoin(base_url, f"/{brand}/{endpoint}/")
    else:
        endpoint_url = urljoin(base_url, f"/{endpoint}/")
    if not same_host(base_url, endpoint_url):
        return None
    return {"endpoint": endpoint_url, "query": query, "per_page": per_page}


def sf_tile_url(config: dict, startrow: int) -> str:
    from urllib.parse import parse_qsl, urlencode, urlunparse
    p = urlparse(config["endpoint"])
    pairs = parse_qsl(config["query"].lstrip("?"), keep_blank_values=True)
    pairs = [(k, v) for k, v in pairs if k.casefold() != "startrow"]
    pairs.append(("startrow", str(int(startrow))))
    return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(pairs), p.fragment))


def _collect_successfactors_tile_strict(company):
    name = company.get("company")
    page_html, source_url, parser, first_jobs, expected_total = _sf_prepare_inventory_strict(company)
    if expected_total == 0:
        return {
            "coverage": "VERIFIED",
            "collector": "successfactors_jobs2web_tile_metadata_v15",
            "inventory_count": 0,
            "jobs": [],
            "source_url": source_url,
        }
    if not first_jobs:
        raise NotCheckable("SuccessFactors tile inventory exposes no initial public requisitions")
    config = sf_tile_config(page_html, source_url)
    if not config:
        raise NotCheckable("SuccessFactors tile pagination contract is not safely evidenced by the public page")

    inventory_jobs = {item["url"]: item for item in first_jobs}
    startrow = config["per_page"]
    pages = 1
    while len(inventory_jobs) < expected_total:
        pages += 1
        if pages > SF_MAX_PAGES:
            raise NotCheckable("SuccessFactors tile inventory exceeds safe exhaustive-page limit")
        url = sf_tile_url(config, startrow)
        try:
            r = get_session().get(url, headers={"Accept": "text/html; charset=UTF-8"}, timeout=TIMEOUT)
            if r.status_code in {401, 403, 404, 406, 410, 429, 500, 502, 503, 504}:
                raise NotCheckable(f"SuccessFactors tile endpoint unavailable: HTTP {r.status_code}")
            r.raise_for_status()
        except requests.exceptions.SSLError as e:
            raise NotCheckable("SuccessFactors tile endpoint TLS validation failed") from e
        except requests.RequestException as e:
            raise NotCheckable(f"SuccessFactors tile endpoint request unavailable: {e}") from e
        page_parser = SFPageParser()
        page_parser.feed(r.text)
        page_jobs = merge_sf_page_jobs(source_url, page_parser)
        if not page_jobs:
            raise NotCheckable(f"SuccessFactors tile pagination stopped early: retrieved={len(inventory_jobs)}, total={expected_total}")
        before = len(inventory_jobs)
        for item in page_jobs:
            inventory_jobs[item["url"]] = item
        if len(inventory_jobs) == before:
            raise NotCheckable(f"SuccessFactors tile pagination repeated a page: retrieved={len(inventory_jobs)}, total={expected_total}")
        if len(inventory_jobs) > expected_total:
            raise NotCheckable(f"SuccessFactors tile reconciliation overflow: retrieved={len(inventory_jobs)}, total={expected_total}")
        startrow += config["per_page"]

    if len(inventory_jobs) != expected_total:
        raise NotCheckable(f"SuccessFactors tile reconciliation mismatch: retrieved={len(inventory_jobs)}, total={expected_total}")
    _final_html, _final_url, final_parser = _sf_load_page_strict(source_url)
    final_total = parse_sf_total(final_parser.visible_text)
    if final_total != expected_total:
        raise NotCheckable(f"SuccessFactors tile total changed during enumeration: {expected_total}->{final_total}")
    return _sf_finish_verified(name, inventory_jobs, source_url, "successfactors_jobs2web_tile_metadata_v15")


def collect_successfactors(company):
    last_error = None
    for attempt in range(2):
        try:
            return _collect_successfactors_paged_strict(company)
        except NotCheckable as paged_error:
            last_error = paged_error
            message = str(paged_error).casefold()
            if any(token in message for token in ("inventory not exhaustible", "pagination repeated a page")):
                try:
                    return _collect_successfactors_tile_strict(company)
                except NotCheckable as tile_error:
                    last_error = tile_error
                    tmsg = str(tile_error).casefold()
                    retryable = any(token in tmsg for token in ("total changed", "reconciliation", "stopped early", "repeated a page"))
                    if retryable and attempt == 0:
                        continue
                    raise
            retryable = any(token in message for token in ("total changed", "reconciliation", "repeated a page"))
            if retryable and attempt == 0:
                continue
            raise
    raise NotCheckable(f"SuccessFactors inventory remained unstable after retry: {last_error}")
'''

text = text.replace(needle, "\n" + block.strip() + "\n" + needle)
path.write_text(text, encoding="utf-8")
print("Applied strict SuccessFactors inventory and tile pagination patch")
