from pathlib import Path

path = Path("collector.py")
text = path.read_text(encoding="utf-8")
marker = "# === JOB WATCH V1.5 SUCCESSFACTORS HARDENING ==="
if marker in text:
    raise SystemExit("v1.5 SuccessFactors hardening already present")

needle = '\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
if needle not in text:
    raise SystemExit("collector.py final main guard not found")

block = r'''
# === JOB WATCH V1.5 SUCCESSFACTORS HARDENING ===
# Generic Career Site Builder / jobs2web hardening. VERIFIED still requires
# exact reconciliation of the complete public inventory. No company-specific
# endpoint or pagination hardcode is used here.

SF_MAX_PAGES = 500
SF_RANGE_PATTERNS = (
    re.compile(r"\bResults?\s+(\d+)\s*[-–—]\s*(\d+)\s+of\s+([\d.,\s]+)\b", re.I),
    re.compile(r"\bRisultati\s+(\d+)\s*[-–—]\s*(\d+)\s+(?:di|su)\s+([\d.,\s]+)\b", re.I),
    re.compile(r"\bErgebnisse\s+(\d+)\s*[-–—]\s*(\d+)\s+von\s+([\d.,\s]+)\b", re.I),
    re.compile(r"\bShowing\s+(\d+)\s+(?:to|[-–—])\s+(\d+)\s+of\s+([\d.,\s]+)\s+Jobs?\b", re.I),
    re.compile(r"\bVisualizzazione\s+da\s+(\d+)\s+a\s+(\d+)\s+di\s+([\d.,\s]+)\s+offert[ae]\b", re.I),
    re.compile(r"\bAffichage\s+de\s+(\d+)\s+[àa]\s+(\d+)\s+sur\s+([\d.,\s]+)\b", re.I),
    re.compile(r"\b(?:Es\s+werden\s+)?(\d+)\s+bis\s+(\d+)\s+von\s+([\d.,\s]+)\s+(?:Stellen|Jobs?)\b", re.I),
)
SF_SINGLE_TOTAL_PATTERNS = (
    re.compile(r"\bShowing\s+(\d+)\s+Jobs?\b", re.I),
    re.compile(r"\bVisualizzazione\s+di\s+(\d+)\s+(?:lavor[oi]|offert[ae])\b", re.I),
    re.compile(r"\bAffichage\s+de\s+(\d+)\s+(?:emploi|emplois|offres?)\b", re.I),
)
SF_LOCATION_LABELS = {
    "location", "luogo", "località", "localita", "standort", "ubicación", "ubicacion", "ubicazione",
}
SF_CITY_LABELS = {"city", "città", "citta", "stadt", "ville", "ciudad"}
SF_COUNTRY_LABELS = {
    "country", "country/region", "country / region", "paese", "paese/regione", "paese / regione",
    "land", "pays", "país", "pais",
}
SF_DATE_LABELS = {
    "date", "posting date", "data", "data di pubblicazione", "datum", "date de publication",
    "fecha", "fecha de publicación",
}
SF_ALL_FIELD_LABELS = SF_LOCATION_LABELS | SF_CITY_LABELS | SF_COUNTRY_LABELS | SF_DATE_LABELS | {
    "title", "titolo", "job title", "società", "societa", "company", "azienda", "function", "funzione",
    "department", "dipartimento", "experience", "esperienza",
}


def _sf_int(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return int(digits) if digits else None


def parse_sf_range(text: str):
    for pat in SF_RANGE_PATTERNS:
        m = pat.search(text or "")
        if not m:
            continue
        start, end, total = (_sf_int(m.group(1)), _sf_int(m.group(2)), _sf_int(m.group(3)))
        if start is not None and end is not None and total is not None and 0 < start <= end <= total:
            return start, end, total
    for pat in SF_SINGLE_TOTAL_PATTERNS:
        m = pat.search(text or "")
        if m:
            total = _sf_int(m.group(1))
            if total is not None and total >= 0:
                return (1, total, total) if total else (0, 0, 0)
    if any(p.search(text or "") for p in SF_ZERO_PATTERNS):
        return 0, 0, 0
    return None


_parse_sf_total_v14 = parse_sf_total
def parse_sf_total(text: str):
    page_range = parse_sf_range(text)
    if page_range is not None:
        return page_range[2]
    return _parse_sf_total_v14(text)


_SFPageParserV14 = SFPageParser
class SFPageParser(_SFPageParserV14):
    # Retain the v1.4 parser and add token positions around anchors.
    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag.casefold() == "a" and self._anchor is not None:
            self._anchor["start_index"] = len(self.text_parts)

    def handle_endtag(self, tag):
        if tag.casefold() == "a" and self._anchor is not None:
            self._anchor["end_index"] = len(self.text_parts)
        super().handle_endtag(tag)


def _sf_norm_label(value):
    s = clean_text(value)
    if not s:
        return ""
    s = html.unescape(s).strip().casefold()
    s = re.sub(r"[\s:：]+$", "", s)
    return re.sub(r"\s+", " ", s)


def _sf_labeled_value(tokens, labels):
    labels = {_sf_norm_label(x) for x in labels}
    all_labels = {_sf_norm_label(x) for x in SF_ALL_FIELD_LABELS}
    for i, token in enumerate(tokens):
        raw = clean_text(token)
        if not raw:
            continue
        norm = _sf_norm_label(raw)
        if norm in labels:
            for candidate in tokens[i + 1:i + 4]:
                value = clean_text(candidate)
                if value and _sf_norm_label(value) not in all_labels:
                    return value
        for label in labels:
            m = re.match(rf"^{re.escape(label)}\s*[:：]\s*(.+)$", raw, re.I)
            if m:
                value = clean_text(m.group(1))
                if value:
                    return value
    return None


def parse_sf_cards(base: str, parser: SFPageParser) -> dict[str, dict]:
    records = []
    seen = set()
    for anchor in parser.anchors:
        u = normalize_abs_url(base, anchor.get("href"))
        if not u or not same_host(base, u) or "/job/" not in urlparse(u).path.casefold() or u in seen:
            continue
        seen.add(u)
        records.append(
            {
                "url": u,
                "title": clean_text(anchor.get("text")) or clean_text(anchor.get("title")),
                "start": int(anchor.get("start_index") or 0),
                "end": int(anchor.get("end_index") or anchor.get("start_index") or 0),
            }
        )

    found = {}
    for i, record in enumerate(records):
        stop = records[i + 1]["start"] if i + 1 < len(records) else len(parser.text_parts)
        stop = min(stop, record["end"] + 120)
        tokens = parser.text_parts[record["end"]:stop]
        direct_location = _sf_labeled_value(tokens, SF_LOCATION_LABELS)
        city = _sf_labeled_value(tokens, SF_CITY_LABELS)
        country = _sf_labeled_value(tokens, SF_COUNTRY_LABELS)
        location = direct_location
        if not location and city:
            location = ", ".join(x for x in (city, country) if x)
        date_value = _sf_labeled_value(tokens, SF_DATE_LABELS)
        if date_value and not DATEISH_RE.search(date_value):
            date_value = None
        found[record["url"]] = {
            "url": record["url"],
            "title": record["title"],
            "location": clean_text(location),
            "published_at": clean_text(date_value),
        }
    return found


_merge_sf_page_jobs_v14 = merge_sf_page_jobs
def merge_sf_page_jobs(base: str, parser: SFPageParser) -> list[dict]:
    rows = {item["url"]: item for item in _merge_sf_page_jobs_v14(base, parser)}
    cards = parse_sf_cards(base, parser)
    ordered = []
    seen = set()
    for u, title in sf_job_anchors(base, parser):
        if u in seen:
            continue
        seen.add(u)
        row = rows.get(u) or {}
        card = cards.get(u) or {}
        ordered.append(
            {
                "url": u,
                "title": row.get("title") or card.get("title") or title,
                "location": row.get("location") or card.get("location"),
                "published_at": row.get("published_at") or card.get("published_at"),
            }
        )
    return ordered


def sf_page_offset(url: str) -> int:
    p = urlparse(url)
    try:
        vals = parse_qs(p.query).get("startrow") or []
        if vals:
            return max(0, int(vals[0]))
    except (TypeError, ValueError):
        pass
    parts = [unquote(x) for x in p.path.split("/") if x]
    lowered = [x.casefold() for x in parts]
    for marker in ("search", "viewalljobs"):
        if marker in lowered:
            idx = lowered.index(marker)
            if idx + 1 < len(parts) and re.fullmatch(r"\d+", parts[idx + 1]):
                return int(parts[idx + 1])
    if "go" in lowered:
        idx = lowered.index("go")
        numeric_after_go = [(j, int(parts[j])) for j in range(idx + 1, len(parts)) if re.fullmatch(r"\d+", parts[j])]
        if len(numeric_after_go) >= 2:
            return numeric_after_go[-1][1]
    return 0


def sf_startrow(url: str) -> int:
    return sf_page_offset(url)


def _sf_inventoryish(url: str) -> bool:
    path = urlparse(url).path.casefold()
    return is_sf_search_path(url) or "/go/" in path


def find_sf_next_url(base: str, parser: SFPageParser, visited: set[str]) -> str | None:
    current_offset = sf_page_offset(base)
    candidates = []
    explicit = []
    for anchor in parser.anchors:
        u = normalize_abs_url(base, anchor.get("href"))
        if not u or not same_host(base, u) or u in visited:
            continue
        offset = sf_page_offset(u)
        text = " ".join(
            x for x in (
                clean_text(anchor.get("text")),
                clean_text(anchor.get("title")),
                clean_text(anchor.get("aria_label")),
            ) if x
        ).casefold()
        rel = (clean_text(anchor.get("rel")) or "").casefold()
        if offset > current_offset and _sf_inventoryish(u):
            candidates.append((offset, u))
        if ("next" in text or "successiv" in text or "weiter" in text or "suivant" in text or "next" in rel):
            if offset > current_offset and _sf_inventoryish(u):
                explicit.append((offset, u))
    if explicit:
        explicit.sort(key=lambda x: x[0])
        return explicit[0][1]
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
    return None


def _sf_query_candidate(url: str, offset: int):
    from urllib.parse import parse_qsl, urlencode, urlunparse
    p = urlparse(url)
    query = dict(parse_qsl(p.query, keep_blank_values=True))
    query["startrow"] = str(offset)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(query), p.fragment))


def _sf_path_candidate(url: str, offset: int):
    from urllib.parse import urlunparse
    p = urlparse(url)
    parts = [unquote(x) for x in p.path.split("/") if x]
    lowered = [x.casefold() for x in parts]
    for marker in ("search", "viewalljobs"):
        if marker in lowered:
            idx = lowered.index(marker)
            if idx + 1 < len(parts) and re.fullmatch(r"\d+", parts[idx + 1]):
                parts[idx + 1] = str(offset)
            else:
                parts.insert(idx + 1, str(offset))
            path = "/" + "/".join(parts) + "/"
            return urlunparse((p.scheme, p.netloc, path, p.params, p.query, p.fragment))
    if "go" in lowered:
        idx = lowered.index("go")
        numeric_after_go = [j for j in range(idx + 1, len(parts)) if re.fullmatch(r"\d+", parts[j])]
        if numeric_after_go:
            if len(numeric_after_go) >= 2:
                parts[numeric_after_go[-1]] = str(offset)
            else:
                parts.append(str(offset))
            path = "/" + "/".join(parts) + "/"
            return urlunparse((p.scheme, p.netloc, path, p.params, p.query, p.fragment))
    return None


def _sf_parser(html_text: str):
    parser = SFPageParser()
    parser.feed(html_text)
    return parser


def _sf_fetch_validated_next(current_url, parser, expected_total, visited):
    actual = find_sf_next_url(current_url, parser, visited)
    current_range = parse_sf_range(parser.visible_text)
    candidates = []
    if actual:
        candidates.append(actual)
    if current_range is not None:
        _start, end, total = current_range
        if total == expected_total and end < total:
            for candidate in (_sf_query_candidate(current_url, end), _sf_path_candidate(current_url, end)):
                if candidate and candidate not in candidates:
                    candidates.append(candidate)

    for candidate in candidates:
        if not candidate or candidate in visited or not same_host(current_url, candidate):
            continue
        html_text, final_url = sf_get_html(candidate)
        if final_url in visited or not same_host(current_url, final_url):
            continue
        next_parser = _sf_parser(html_text)
        page_total = parse_sf_total(next_parser.visible_text)
        if page_total is not None and page_total != expected_total:
            raise NotCheckable(f"SuccessFactors total changed during pagination: {expected_total}->{page_total}")
        next_range = parse_sf_range(next_parser.visible_text)
        if current_range is not None and next_range is not None:
            cur_start, cur_end, _ = current_range
            nxt_start, nxt_end, nxt_total = next_range
            if nxt_total != expected_total or nxt_start != cur_end + 1 or nxt_end <= cur_end or nxt_start <= cur_start:
                continue
        elif candidate != actual:
            continue
        return html_text, final_url, next_parser
    return None


def sf_get_html(url: str) -> tuple[str, str]:
    # Runner/network restrictions are NOT_CHECKED, not collector bugs.
    try:
        return get_html(url)
    except requests.exceptions.SSLError as e:
        raise NotCheckable(
            "SuccessFactors public inventory is not safely enumerable because TLS validation failed"
        ) from e
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        raise NotCheckable(
            f"SuccessFactors public inventory not enumerable from runner (HTTP {status or 'error'})"
        ) from e
    except requests.RequestException as e:
        raise NotCheckable(f"SuccessFactors public inventory request unavailable from runner: {e}") from e


def _collect_successfactors_once(company):
    name = company.get("company")
    ats = company.get("ats", {})
    inventory = clean_text(ats.get("inventory_url"))
    if not inventory:
        raise NotCheckable("SuccessFactors inventory URL missing")

    html_text, current_url = sf_get_html(inventory)
    parser = _sf_parser(html_text)
    initial_jobs = merge_sf_page_jobs(current_url, parser)
    expected_total = parse_sf_total(parser.visible_text)

    if expected_total is None or (expected_total > 0 and not initial_jobs):
        discovered = find_sf_search_url(current_url, parser)
        if discovered and discovered != current_url:
            html_text, current_url = sf_get_html(discovered)
            parser = _sf_parser(html_text)
            initial_jobs = merge_sf_page_jobs(current_url, parser)
            expected_total = parse_sf_total(parser.visible_text)

    if expected_total is None:
        raise NotCheckable("SuccessFactors page does not expose a reconcilable inventory total")
    if expected_total > 0 and not initial_jobs:
        raise NotCheckable(
            f"SuccessFactors inventory exposes total={expected_total} but no stable public job links"
        )

    visited: set[str] = set()
    inventory_jobs: dict[str, dict] = {}
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
            raise NotCheckable(
                f"SuccessFactors reconciliation overflow: retrieved={len(inventory_jobs)}, total={expected_total}"
            )
        if len(inventory_jobs) == before and before:
            raise NotCheckable(
                f"SuccessFactors pagination made no inventory progress: retrieved={len(inventory_jobs)}, total={expected_total}"
            )

        nxt = _sf_fetch_validated_next(current_url, parser, expected_total, visited)
        if not nxt:
            raise NotCheckable(
                f"SuccessFactors inventory not exhaustible: retrieved={len(inventory_jobs)}, total={expected_total}"
            )
        html_text, current_url, parser = nxt

    if len(inventory_jobs) != expected_total:
        raise NotCheckable(
            f"SuccessFactors reconciliation mismatch: retrieved={len(inventory_jobs)}, total={expected_total}"
        )

    missing_location = [x for x in inventory_jobs.values() if not clean_text(x.get("location"))]
    if missing_location:
        raise NotCheckable(
            f"SuccessFactors inventory reconciled but location metadata is incomplete: "
            f"missing={len(missing_location)}, total={expected_total}"
        )

    jobs = []
    for raw in inventory_jobs.values():
        loc = clean_text(raw.get("location"))
        if not location_matches(loc):
            continue
        jobs.append(
            compact_job(
                name,
                sf_job_source_id(raw["url"]),
                title=raw.get("title"),
                location=loc,
                published_at=raw.get("published_at"),
                canonical=raw.get("url"),
                apply_url=raw.get("url"),
            )
        )

    return {
        "coverage": "VERIFIED",
        "collector": "successfactors_jobs2web_metadata_v15",
        "inventory_count": len(inventory_jobs),
        "jobs": jobs,
        "source_url": inventory,
    }


def collect_successfactors(company):
    last_error = None
    for attempt in range(2):
        try:
            return _collect_successfactors_once(company)
        except NotCheckable as e:
            message = str(e).casefold()
            retryable = any(
                token in message
                for token in (
                    "total changed",
                    "reconciliation mismatch",
                    "reconciliation overflow",
                    "pagination made no inventory progress",
                )
            )
            if not retryable or attempt:
                raise
            last_error = e
    raise NotCheckable(f"SuccessFactors inventory remained unstable after retry: {last_error}")


_collect_batch_v14 = collect_batch
def collect_batch(batch: str, workers: int = DEFAULT_WORKERS):
    payload = _collect_batch_v14(batch, workers=workers)
    payload["version"] = "1.5"
    write_json(ROOT / f"current_jobs_{batch}.json", payload)
    return payload
'''

text = text.replace(needle, "\n" + block.strip() + "\n" + needle)
path.write_text(text, encoding="utf-8")
print("Applied generic SuccessFactors v1.5 hardening")
