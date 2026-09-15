#!/usr/bin/env python3
from pathlib import Path

path = Path("collector.py")
text = path.read_text(encoding="utf-8")

marker = "# === JOB WATCH V1.6 YELLO / RECSOLU ==="
if marker in text:
    print("Yello v1.6 patch already applied")
    raise SystemExit(0)

needle = '\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
if needle not in text:
    raise SystemExit("collector.py final main marker not found")

block = r'''

# === JOB WATCH V1.6 YELLO / RECSOLU ===
# Yello/Recsolu boards expose a public, paginated JSON search contract.
# VERIFIED requires two independent proofs:
#   1) the unfiltered board reconciles exactly to its public Results total;
#   2) the board's own Office Location filter is used to enumerate the target
#      cities, and the response explicitly echoes those selected filter IDs.
# This avoids inferring target membership from titles or free-text descriptions.

YELLO_SCOPE_NAME = "Yello / Recsolu public board"
YELLO_TOTAL_RE = re.compile(r"\b([\d,]+)\s+Results?\b", re.I)
YELLO_BOARD_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")
YELLO_TARGET_LABELS = {
    "milan": {"milan", "milano"},
    "rome": {"rome", "roma"},
    "london": {"london"},
}


class YelloBoardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.job_links = []
        self.search_urls = []
        self.office_filter_values = []

    def handle_starttag(self, tag, attrs):
        a = {str(k).casefold(): v for k, v in attrs}
        t = tag.casefold()
        href = clean_text(a.get("href"))
        if t == "a" and href:
            self.job_links.append(href)
        search_url = clean_text(a.get("data-search-url"))
        if search_url and "/job_boards/" in search_url and "/search" in search_url:
            self.search_urls.append(search_url)
        if t == "defined-field-answers-filter-container":
            label = clean_text(a.get("field-label")) or ""
            if label.casefold() == "office location":
                value = clean_text(a.get("v-bind:filters"))
                if value:
                    self.office_filter_values.append(value)

    def handle_data(self, data):
        s = clean_text(data)
        if s:
            self.text_parts.append(s)

    @property
    def visible_text(self):
        return " ".join(self.text_parts)


def yello_family(company) -> bool:
    ats = company.get("ats") or {}
    family = (clean_text(ats.get("family")) or "").casefold()
    verification = company.get("verification") or {}
    inventory = clean_text(ats.get("inventory_url")) or ""
    p = urlparse(inventory)
    host = p.netloc.casefold().split(":", 1)[0]
    return bool(
        verification.get("full_inventory_possible") is True
        and ("yello" in family or "recsolu" in family)
        and (host == "recsolu.com" or host.endswith(".recsolu.com"))
        and "/job_boards/" in p.path.casefold()
    )


def _yello_get(url: str, params=None, xhr=False):
    headers = {"Accept": "application/json, text/html, */*"}
    if xhr:
        headers["X-Requested-With"] = "XMLHttpRequest"
    try:
        r = get_session().get(url, params=params, headers=headers, timeout=TIMEOUT)
        if r.status_code in {401, 403, 404, 406, 410, 429, 500, 502, 503, 504}:
            raise NotCheckable(f"Yello public inventory unavailable from runner (HTTP {r.status_code})")
        r.raise_for_status()
        return r
    except requests.exceptions.SSLError as e:
        raise NotCheckable("Yello public inventory TLS validation failed") from e
    except requests.RequestException as e:
        raise NotCheckable(f"Yello public inventory request unavailable from runner: {e}") from e


def _yello_parse_total(text: str):
    matches = YELLO_TOTAL_RE.findall(text or "")
    totals = []
    for raw in matches:
        try:
            totals.append(int(raw.replace(",", "")))
        except (TypeError, ValueError):
            continue
    unique = set(totals)
    if len(unique) != 1:
        raise NotCheckable("Yello board does not expose one unambiguous public Results total")
    return next(iter(unique))


def _yello_board_metadata(inventory: str):
    r = _yello_get(inventory)
    parser = YelloBoardParser()
    parser.feed(r.text)
    total = _yello_parse_total(parser.visible_text)

    tokens = set()
    for href in parser.job_links:
        u = urljoin(r.url, href)
        p = urlparse(u)
        if p.netloc.casefold() != urlparse(r.url).netloc.casefold() or "/jobs/" not in p.path.casefold():
            continue
        token = (parse_qs(p.query).get("job_board_id") or [None])[0]
        if token and YELLO_BOARD_TOKEN_RE.fullmatch(token):
            tokens.add(token)

    search_urls = []
    for raw in parser.search_urls:
        u = urljoin(r.url, raw)
        if urlparse(u).netloc.casefold() == urlparse(r.url).netloc.casefold():
            search_urls.append(u)
            m = re.search(r"/job_boards/([A-Za-z0-9_-]+)/search/?$", urlparse(u).path, re.I)
            if m:
                tokens.add(m.group(1))

    if len(tokens) != 1:
        raise NotCheckable(f"Yello board token is not uniquely evidenced: found={len(tokens)}")
    token = next(iter(tokens))
    if search_urls:
        valid = [u for u in search_urls if f"/job_boards/{token}/search" in urlparse(u).path]
        if not valid:
            raise NotCheckable("Yello public search endpoint does not match evidenced board token")
        search_url = valid[0]
    else:
        base = f"{urlparse(r.url).scheme}://{urlparse(r.url).netloc}"
        search_url = f"{base}/job_boards/{token}/search"

    office_answers = None
    for raw in parser.office_filter_values:
        try:
            value = json.loads(html.unescape(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(value, list):
            continue
        parsed = []
        for item in value:
            if not isinstance(item, dict):
                continue
            try:
                answer_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            label = clean_text(item.get("label"))
            if label:
                parsed.append({"id": answer_id, "label": label})
        if parsed:
            if office_answers is not None and parsed != office_answers:
                raise NotCheckable("Yello board exposes conflicting Office Location filter inventories")
            office_answers = parsed
    if office_answers is None:
        raise NotCheckable("Yello board does not expose a complete public Office Location filter inventory")

    return {
        "page_url": r.url,
        "total": total,
        "token": token,
        "search_url": search_url,
        "office_answers": office_answers,
    }


def _yello_strip(value):
    return html_to_text(value) or ""


def _yello_parse_cards(fragment: str, base_url: str, board_token: str):
    decoded = html.unescape(fragment or "")
    blocks = re.findall(
        r'<li[^>]*class=["\'][^"\']*search-results__item[^"\']*["\'][^>]*>(.*?)</li>',
        decoded,
        re.I | re.S,
    )
    rows = []
    for block in blocks:
        m = re.search(
            r'<a[^>]*class=["\'][^"\']*search-results__req_title[^"\']*["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            block,
            re.I | re.S,
        )
        if not m:
            raise NotCheckable("Yello search result card lacks a stable requisition link")
        u = urljoin(base_url, html.unescape(m.group(1)))
        p = urlparse(u)
        token = (parse_qs(p.query).get("job_board_id") or [None])[0]
        sid = p.path.rstrip("/").split("/")[-1] if "/jobs/" in p.path.casefold() else None
        if token != board_token or not sid:
            raise NotCheckable("Yello search result does not match the evidenced board token")
        spans = [_yello_strip(x) for x in re.findall(r"<span[^>]*>(.*?)</span>", block, re.I | re.S)]
        rows.append(
            {
                "source_id": sid,
                "url": u,
                "title": _yello_strip(m.group(2)),
                "employment_type": spans[0] if len(spans) > 0 else None,
                "region": spans[1] if len(spans) > 1 else None,
                "location": spans[2] if len(spans) > 2 else None,
            }
        )
    return rows


def _yello_parse_display_count(value):
    m = re.fullmatch(r"\s*([\d,]+)\s+Results?\s*", str(value or ""), re.I)
    if not m:
        raise NotCheckable("Yello filtered search does not expose a strict result count")
    return int(m.group(1).replace(",", ""))


def _yello_validate_echoed_filters(data: dict, expected_ids: set[int]):
    value = data.get("filters")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError) as e:
            raise NotCheckable("Yello search response has invalid echoed filter metadata") from e
    if not isinstance(value, list):
        raise NotCheckable("Yello search response does not echo applied filters")
    office_fields = [
        x for x in value
        if isinstance(x, dict) and (clean_text(x.get("label")) or "").casefold() == "office location"
    ]
    if len(office_fields) != 1:
        raise NotCheckable("Yello search response does not echo exactly one Office Location filter")
    answers = office_fields[0].get("answers")
    if not isinstance(answers, list):
        raise NotCheckable("Yello echoed Office Location filter has no answer list")
    actual_ids = set()
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        try:
            actual_ids.add(int(answer.get("id")))
        except (TypeError, ValueError):
            continue
    if actual_ids != expected_ids:
        raise NotCheckable(f"Yello echoed Office Location IDs differ from request: {sorted(actual_ids)}")


def _yello_search_pages(search_url: str, board_token: str, filter_ids=None):
    filter_ids = list(filter_ids or [])
    filter_string = ",".join(str(int(x)) for x in filter_ids)
    rows = []
    seen = set()
    expected_count = None
    expected_ids = {int(x) for x in filter_ids}

    for page in range(1, MAX_PAGES + 1):
        params = {
            "query": "",
            "filters": filter_string,
            "page_number": page,
            "job_board_tab_identifier": "job-watch",
        }
        r = _yello_get(search_url, params=params, xhr=True)
        try:
            data = r.json()
        except ValueError as e:
            raise NotCheckable("Yello public search endpoint did not return JSON") from e
        if not isinstance(data, dict):
            raise NotCheckable("Yello public search response is not an object")
        if clean_text(data.get("query")):
            raise NotCheckable("Yello public search unexpectedly applied a text query")
        text_filters = data.get("text_filters")
        if text_filters not in (None, "", "[]", []):
            raise NotCheckable("Yello public search unexpectedly applied text filters")
        if filter_ids:
            _yello_validate_echoed_filters(data, expected_ids)
            page_count = _yello_parse_display_count(data.get("display_count_text"))
            if expected_count is None:
                expected_count = page_count
            elif page_count != expected_count:
                raise NotCheckable(f"Yello filtered total changed during pagination: {expected_count}->{page_count}")
        page_rows = _yello_parse_cards(data.get("html") or "", search_url, board_token)
        for row in page_rows:
            sid = row["source_id"]
            if sid in seen:
                raise NotCheckable(f"Yello pagination repeated requisition ID {sid}")
            seen.add(sid)
            rows.append(row)
        more = data.get("more_requisitions")
        if more is False:
            break
        if more is not True:
            raise NotCheckable("Yello pagination does not expose a boolean more_requisitions flag")
        if not page_rows:
            raise NotCheckable("Yello pagination made no inventory progress")
    else:
        raise NotCheckable("Yello inventory exceeds safe exhaustive-page limit")

    if filter_ids and expected_count is not None and len(rows) != expected_count:
        raise NotCheckable(f"Yello filtered reconciliation mismatch: retrieved={len(rows)}, total={expected_count}")
    return rows, expected_count


def _yello_target_filter_ids(office_answers):
    found = {key: [] for key in YELLO_TARGET_LABELS}
    for answer in office_answers:
        label = (clean_text(answer.get("label")) or "").casefold()
        for key, aliases in YELLO_TARGET_LABELS.items():
            if label in aliases:
                found[key].append(int(answer["id"]))
    if any(len(ids) != 1 for ids in found.values()):
        detail = {k: v for k, v in found.items()}
        raise NotCheckable(f"Yello target Office Location IDs are not uniquely evidenced: {detail}")
    return [found["milan"][0], found["rome"][0], found["london"][0]]


def _collect_yello_once(company):
    name = company.get("company")
    ats = company.get("ats") or {}
    inventory = clean_text(ats.get("inventory_url"))
    if not inventory:
        raise NotCheckable("Yello inventory URL missing")

    meta = _yello_board_metadata(inventory)
    global_rows, _unused = _yello_search_pages(meta["search_url"], meta["token"], filter_ids=[])
    global_ids = {x["source_id"] for x in global_rows}
    if len(global_rows) != meta["total"] or len(global_ids) != meta["total"]:
        raise NotCheckable(
            f"Yello global reconciliation mismatch: retrieved={len(global_ids)}, total={meta['total']}"
        )

    # Re-read the public board after global enumeration to reject live changes.
    final_meta = _yello_board_metadata(inventory)
    if final_meta["token"] != meta["token"] or final_meta["total"] != meta["total"]:
        raise NotCheckable(
            f"Yello board changed during enumeration: total={meta['total']}->{final_meta['total']}"
        )

    target_filter_ids = _yello_target_filter_ids(meta["office_answers"])
    target_rows, target_total = _yello_search_pages(
        meta["search_url"], meta["token"], filter_ids=target_filter_ids
    )
    if target_total is None or len(target_rows) != target_total:
        raise NotCheckable("Yello target inventory did not reconcile exactly")
    if any(row["source_id"] not in global_ids for row in target_rows):
        raise NotCheckable("Yello target filter returned requisitions outside global inventory")
    if any(not location_matches(row.get("location")) for row in target_rows):
        raise NotCheckable("Yello target filter returned a requisition without target location metadata")

    jobs = []
    for row in target_rows:
        jobs.append(
            compact_job(
                name,
                row["source_id"],
                title=row.get("title"),
                location=row.get("location"),
                employment_type=row.get("employment_type"),
                canonical=row.get("url"),
                apply_url=row.get("url"),
            )
        )
    return {
        "coverage": "VERIFIED",
        "collector": "yello_recsolu_public_board_metadata_v16",
        "inventory_count": meta["total"],
        "jobs": jobs,
        "source_url": meta["page_url"],
    }


def collect_yello(company):
    last_error = None
    for attempt in range(2):
        try:
            return _collect_yello_once(company)
        except NotCheckable as e:
            last_error = e
            msg = str(e).casefold()
            retryable = any(
                token in msg
                for token in (
                    "changed during enumeration",
                    "total changed during pagination",
                    "reconciliation mismatch",
                    "repeated requisition",
                    "pagination made no inventory progress",
                )
            )
            if not retryable or attempt:
                raise
    raise NotCheckable(f"Yello inventory remained unstable after retry: {last_error}")


_choose_v15 = choose
def choose(company):
    if yello_family(company):
        return collect_yello
    return _choose_v15(company)


_collect_batch_v15 = collect_batch
def collect_batch(batch: str, workers: int = DEFAULT_WORKERS):
    payload = _collect_batch_v15(batch, workers=workers)
    payload["version"] = "1.6"
    scope = list(payload.get("collector_scope") or [])
    if YELLO_SCOPE_NAME not in scope:
        scope.append(YELLO_SCOPE_NAME)
    payload["collector_scope"] = scope
    write_json(ROOT / f"current_jobs_{batch}.json", payload)
    return payload
'''

text = text.replace(needle, block + needle)
path.write_text(text, encoding="utf-8")
print("Applied generic Yello/Recsolu v1.6 collector")
