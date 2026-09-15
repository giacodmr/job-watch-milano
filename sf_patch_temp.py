from pathlib import Path

p = Path('collector.py')
s = p.read_text(encoding='utf-8')
old = 'SF_MAX_PAGES = MAX_PAGES'
assert s.count(old) == 1, s.count(old)
s = s.replace(old, 'SF_MAX_PAGES = 500', 1)
marker = '\n# === JOB WATCH V1.6 YELLO / RECSOLU ===\n'
assert marker in s
assert 'JOB WATCH V1.7 SUCCESSFACTORS EVIDENCED JOBS SERVICE' not in s
block = r'''

# === JOB WATCH V1.7 SUCCESSFACTORS EVIDENCED JOBS SERVICE ===
# Some Career Site Builder search pages render requisitions dynamically. Use
# the public jobs service only when the portal itself evidences its widget,
# same-host searchManager asset and POST endpoint. VERIFIED still requires
# exact total/page/ID reconciliation, complete location metadata and stable
# edge pages.
SF_SERVICE_WIDGET_MARKER = "xweb/rmk-jobs-search"
SF_SERVICE_MANAGER_RE = re.compile(
    r'<script\b[^>]*\bsrc=["\']([^"\']*j2w\.searchManager[^"\']*)["\']', re.I
)
SF_SERVICE_ENDPOINT_RE = re.compile(
    r'type\s*:\s*["\']POST["\']\s*,\s*url\s*:\s*["\']([^"\']+)["\']', re.I
)


def _sf_service_search_url(base, parser):
    candidates = []
    if _sf_is_exhaustive_search_path(base) and is_unfiltered_search_url(base):
        candidates.append((0, base))
    for action in getattr(parser, "form_actions", []) or []:
        u = normalize_abs_url(base, clean_text(action))
        if u and same_host(base, u) and _sf_is_exhaustive_search_path(u) and is_unfiltered_search_url(u):
            candidates.append((1, u))
    for anchor in parser.anchors:
        u = normalize_abs_url(base, anchor.get("href"))
        if u and same_host(base, u) and _sf_is_exhaustive_search_path(u) and is_unfiltered_search_url(u):
            candidates.append((2, u))
    if not candidates:
        return None
    best = {}
    for priority, u in candidates:
        best[u] = min(priority, best.get(u, priority))
    return sorted(best, key=lambda u: (best[u], bool(urlparse(u).query), len(u)))[0]


def _sf_service_contract(company):
    inventory = clean_text((company.get("ats") or {}).get("inventory_url"))
    if not inventory:
        raise NotCheckable("SuccessFactors inventory URL missing")
    page_html, current_url, parser = _sf_load_page_strict(inventory)
    search_url = _sf_service_search_url(current_url, parser)
    if not search_url:
        raise NotCheckable("SuccessFactors portal does not evidence an unfiltered same-host search page for jobs-service enumeration")
    if search_url != current_url:
        page_html, current_url, parser = _sf_load_page_strict(search_url)
    if SF_SERVICE_WIDGET_MARKER not in page_html:
        raise NotCheckable("SuccessFactors search page does not evidence the public dynamic jobs-service widget")

    managers = []
    for raw in SF_SERVICE_MANAGER_RE.findall(page_html):
        u = normalize_abs_url(current_url, html.unescape(raw))
        if u and same_host(current_url, u) and u not in managers:
            managers.append(u)
    if len(managers) != 1:
        raise NotCheckable(f"SuccessFactors search page does not evidence exactly one same-host searchManager asset: found={len(managers)}")
    manager_html, manager_url = sf_get_html(managers[0])
    if not same_host(current_url, manager_url):
        raise NotCheckable("SuccessFactors searchManager asset redirected off-host")
    m = SF_SERVICE_ENDPOINT_RE.search(manager_html)
    if not m:
        raise NotCheckable("SuccessFactors searchManager asset does not evidence a public POST jobs endpoint")
    endpoint = normalize_abs_url(current_url, html.unescape(m.group(1)))
    if not endpoint or not same_host(current_url, endpoint) or urlparse(endpoint).path.rstrip('/').casefold() != '/services/recruiting/v1/jobs':
        raise NotCheckable("SuccessFactors evidenced jobs endpoint is not the expected same-host recruiting service")

    compact_js = re.sub(r"\s+", "", manager_html)
    for field in ("keywords", "locale", "location", "pageNumber", "sortBy"):
        if f"{field}:" not in compact_js:
            raise NotCheckable(f"SuccessFactors searchManager payload contract lacks {field}")
    if not re.search(r'sortBy:["\']recent["\']', compact_js, re.I):
        raise NotCheckable("SuccessFactors searchManager does not evidence the standard recent ordering")

    app_m = re.search(r"var\s+appParams\s*=\s*\{(.*?)\}\s*;", page_html, re.I | re.S)
    if not app_m:
        raise NotCheckable("SuccessFactors dynamic search page does not expose public appParams")
    app = app_m.group(1)
    locale_m = re.search(r'\blocale\s*:\s*["\']([A-Za-z]{2,3}_[A-Za-z]{2,3})["\']', app, re.I)
    if not locale_m:
        raise NotCheckable("SuccessFactors dynamic search page does not expose a valid public locale")
    for field in ("keywords", "location"):
        fm = re.search(rf'\b{field}\s*:\s*["\']([^"\']*)["\']', app, re.I)
        if not fm or clean_text(fm.group(1)):
            raise NotCheckable(f"SuccessFactors dynamic search page is not demonstrably unfiltered: {field}")
    return {"source_url": current_url, "endpoint": endpoint, "locale": locale_m.group(1)}


def _sf_service_post(contract, page_number):
    payload = {"keywords": "", "locale": contract["locale"], "location": "", "pageNumber": int(page_number), "sortBy": "recent"}
    try:
        r = get_session().post(
            contract["endpoint"], json=payload,
            headers={"Accept": "application/json, text/plain, */*", "Referer": contract["source_url"]},
            timeout=TIMEOUT,
        )
        if r.status_code in {401, 403, 404, 406, 410, 429, 500, 502, 503, 504}:
            raise NotCheckable(f"SuccessFactors public jobs service unavailable: HTTP {r.status_code}")
        r.raise_for_status()
    except requests.exceptions.SSLError as e:
        raise NotCheckable("SuccessFactors public jobs service TLS validation failed") from e
    except requests.RequestException as e:
        raise NotCheckable(f"SuccessFactors public jobs service request unavailable: {e}") from e
    try:
        data = r.json()
    except ValueError as e:
        raise NotCheckable("SuccessFactors public jobs service did not return JSON") from e
    if not isinstance(data, dict) or type(data.get("totalJobs")) is not int or data["totalJobs"] < 0:
        raise NotCheckable("SuccessFactors public jobs service has no valid authoritative totalJobs")
    raw_rows = data.get("jobSearchResult")
    if not isinstance(raw_rows, list):
        raise NotCheckable("SuccessFactors public jobs service has no jobSearchResult array")
    rows = []
    for wrapper in raw_rows:
        if not isinstance(wrapper, dict) or not isinstance(wrapper.get("response"), dict):
            raise NotCheckable("SuccessFactors public jobs service returned a malformed requisition row")
        rows.append(wrapper["response"])
    return data["totalJobs"], rows


def _sf_service_location(raw):
    out = []
    short = raw.get("jobLocationShort")
    values = short if isinstance(short, list) else [short]
    for item in values:
        value = clean_text(item)
        if value and value not in out:
            out.append(value)
    coords = raw.get("jobLocationShortWithCoordinates")
    if isinstance(coords, list):
        for item in coords:
            value = clean_text(item.get("value")) if isinstance(item, dict) else None
            if value and value not in out:
                out.append(value)
    return " | ".join(out) if out else None


def _sf_service_row(raw, contract):
    sid = clean_text(raw.get("id"))
    title = clean_text(raw.get("unifiedStandardTitle"))
    slug = clean_text(raw.get("unifiedUrlTitle"))
    location = _sf_service_location(raw)
    if not sid or not re.fullmatch(r"\d+", sid):
        raise NotCheckable("SuccessFactors public jobs service requisition lacks a stable numeric ID")
    if not title or not slug:
        raise NotCheckable(f"SuccessFactors public jobs service requisition {sid} lacks title or public URL slug")
    if not location:
        raise NotCheckable(f"SuccessFactors public jobs service requisition {sid} lacks complete location metadata")
    url = urljoin(contract["source_url"], f"/job/{slug}/{sid}-{contract['locale']}/")
    if not same_host(contract["source_url"], url):
        raise NotCheckable(f"SuccessFactors public jobs service requisition {sid} produced an off-host URL")
    return {"source_id": sid, "url": url, "title": title, "location": location}


def _sf_service_validate_url(row, contract):
    try:
        r = get_session().get(row["url"], headers={"Accept": "text/html,*/*"}, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code >= 400 or not same_host(contract["source_url"], r.url) or "/errorpage/" in urlparse(r.url).path.casefold():
            raise NotCheckable(f"SuccessFactors public job URL for requisition {row['source_id']} is not stable")
        if row["source_id"] not in r.text:
            raise NotCheckable(f"SuccessFactors public job URL for requisition {row['source_id']} does not evidence its requisition ID")
    except requests.exceptions.SSLError as e:
        raise NotCheckable("SuccessFactors public job URL TLS validation failed") from e
    except requests.RequestException as e:
        raise NotCheckable(f"SuccessFactors public job URL request unavailable: {e}") from e


def _collect_successfactors_service_once(company):
    name = company.get("company")
    contract = _sf_service_contract(company)
    total, first_raw = _sf_service_post(contract, 0)
    if total == 0:
        if first_raw:
            raise NotCheckable("SuccessFactors public jobs service returned rows with totalJobs=0")
        check_total, check_rows = _sf_service_post(contract, 0)
        if check_total != 0 or check_rows:
            raise NotCheckable("SuccessFactors public jobs service zero inventory changed during verification")
        return {"coverage": "VERIFIED", "collector": "successfactors_jobs_service_metadata_v17", "inventory_count": 0, "jobs": [], "source_url": contract["source_url"]}

    page_size = len(first_raw)
    if page_size <= 0 or page_size > 100:
        raise NotCheckable(f"SuccessFactors public jobs service exposes invalid page size: {page_size}")
    pages = (total + page_size - 1) // page_size
    if pages > SF_MAX_PAGES:
        raise NotCheckable("SuccessFactors public jobs service inventory exceeds safe exhaustive-page limit")

    rows, page_ids, seen = [], [], set()
    for page_number in range(pages):
        page_total, raw_rows = (total, first_raw) if page_number == 0 else _sf_service_post(contract, page_number)
        if page_total != total:
            raise NotCheckable(f"SuccessFactors public jobs service total changed during pagination: {total}->{page_total}")
        expected = page_size if page_number < pages - 1 else total - page_size * (pages - 1)
        if len(raw_rows) != expected:
            raise NotCheckable(f"SuccessFactors public jobs service page-size mismatch on page {page_number}: got={len(raw_rows)}, expected={expected}")
        ids = []
        for raw in raw_rows:
            row = _sf_service_row(raw, contract)
            sid = row["source_id"]
            if sid in seen:
                raise NotCheckable(f"SuccessFactors public jobs service repeated requisition ID {sid}; exhaustive inventory cannot be proven")
            seen.add(sid)
            ids.append(sid)
            rows.append(row)
        page_ids.append(ids)
    if len(rows) != total or len(seen) != total:
        raise NotCheckable(f"SuccessFactors public jobs service reconciliation mismatch: rows={len(rows)}, unique_ids={len(seen)}, total={total}")

    first_total, first_check = _sf_service_post(contract, 0)
    last_total, last_check = (first_total, first_check) if pages == 1 else _sf_service_post(contract, pages - 1)
    first_ids = [clean_text(x.get("id")) or "" for x in first_check]
    last_ids = [clean_text(x.get("id")) or "" for x in last_check]
    if first_total != total or last_total != total or first_ids != page_ids[0] or last_ids != page_ids[-1]:
        raise NotCheckable("SuccessFactors public jobs service edge pages changed during enumeration")

    _sf_service_validate_url(rows[0], contract)
    if len(rows) > 1:
        _sf_service_validate_url(rows[-1], contract)
    jobs = []
    for row in rows:
        if location_matches(row["location"]):
            jobs.append(compact_job(name, row["source_id"], title=row["title"], location=row["location"], canonical=row["url"], apply_url=row["url"]))
    return {"coverage": "VERIFIED", "collector": "successfactors_jobs_service_metadata_v17", "inventory_count": total, "jobs": jobs, "source_url": contract["source_url"]}


_collect_successfactors_strict_v15 = collect_successfactors
def collect_successfactors(company):
    try:
        return _collect_successfactors_strict_v15(company)
    except NotCheckable as strict_error:
        message = str(strict_error).casefold()
        eligible = any(token in message for token in (
            "no evidenced same-host exhaustive /search/ or /viewalljobs/ inventory exposed by portal",
            "evidenced successfactors search page has no reconcilable inventory total",
            "successfactors inventory exposes total=",
            "successfactors search exposes total=",
        ))
        if not eligible:
            raise
        try:
            return _collect_successfactors_service_once(company)
        except NotCheckable as service_error:
            raise NotCheckable(
                f"SuccessFactors static inventory not provable ({strict_error}); dynamic jobs-service proof also failed ({service_error})"
            ) from service_error
'''
s = s.replace(marker, block + marker, 1)
p.write_text(s, encoding='utf-8')
