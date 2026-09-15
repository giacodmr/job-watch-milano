#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

PATH = Path("collector.py")
MARKER = "# === JOB WATCH V1.5 SUCCESSFACTORS ENHANCEMENTS ==="

CODE = r'''

# === JOB WATCH V1.5 SUCCESSFACTORS ENHANCEMENTS ===
# Generic support for additional SAP SuccessFactors Career Site Builder templates:
# - inventory links exposed through same-host form actions
# - /go/<category>/<id>/<offset>/ pagination
# - Italian result-count wording
# - card-style metadata identified by stable job-<id>-desktop-section-* DOM ids

SF_TOTAL_PATTERNS = tuple(SF_TOTAL_PATTERNS) + (
    re.compile(r"\bVisualizzazione\s+da\s+\d+\s+a\s+\d+\s+di\s+([\d.,\s]+)\s+offerte\b", re.I),
    re.compile(r"\bVisualizzazione\s+\d+\s+(?:a|-)\s+\d+\s+di\s+([\d.,\s]+)\s+offerte\b", re.I),
)

_SFPageParser_v14 = SFPageParser

class SFPageParserV15(_SFPageParser_v14):
    FIELD_ID_RE = re.compile(
        r"^job-(\d+)-desktop-section-([A-Za-z0-9_-]+)-(label|value)$",
        re.I,
    )

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
            pair = fields.setdefault(cap["field"], {})
            pair[cap["kind"]] = value
        self._sf_field_capture = None

SFPageParser = SFPageParserV15

_find_sf_search_url_v14 = find_sf_search_url

def find_sf_search_url(base: str, parser: SFPageParser) -> str | None:
    existing = _find_sf_search_url_v14(base, parser)
    if existing:
        return existing
    candidates = []
    for action in getattr(parser, "form_actions", []) or []:
        u = normalize_abs_url(base, clean_text(action))
        if not u or not same_host(base, u):
            continue
        if "/search/" in urlparse(u).path.casefold() or urlparse(u).path.casefold().endswith("/search"):
            candidates.append(u)
    if not candidates:
        return None
    candidates = list(dict.fromkeys(candidates))
    candidates.sort(key=lambda u: (0 if not urlparse(u).query else 1, len(urlparse(u).path), len(u)))
    return candidates[0]

_sf_startrow_v14 = sf_startrow

def sf_startrow(url: str) -> int:
    query_offset = _sf_startrow_v14(url)
    if query_offset:
        return query_offset
    parts = [unquote(x) for x in urlparse(url).path.split("/") if x]
    try:
        go_index = next(i for i, x in enumerate(parts) if x.casefold() == "go")
    except StopIteration:
        return 0
    tail = parts[go_index + 1:]
    # Standard jobs2web category pagination: /go/<slug>/<category-id>/<offset>/
    if len(tail) >= 3 and tail[-1].isdigit() and tail[-2].isdigit():
        return int(tail[-1])
    return 0


def sf_card_field_values(parser: SFPageParser, job_url: str):
    job_id = sf_job_source_id(job_url)
    return getattr(parser, "card_fields", {}).get(str(job_id), {}) or {}


def sf_card_location(parser: SFPageParser, job_url: str) -> str | None:
    fields = sf_card_field_values(parser, job_url)
    if not fields:
        return None
    primary = []
    secondary = []
    for field, pair in fields.items():
        value = clean_text((pair or {}).get("value"))
        label = clean_text((pair or {}).get("label")) or ""
        if not value:
            continue
        key = f"{field} {label}".casefold()
        if any(token in key for token in ("location", "località", "localita", "luogo", "city", "città", "citta")):
            primary.append(value)
        elif any(token in key for token in ("country", "paese", "region", "regione")):
            secondary.append(value)
    values = []
    for value in primary + secondary:
        if value not in values:
            values.append(value)
    return " | ".join(values) if values else None


def sf_card_date(parser: SFPageParser, job_url: str) -> str | None:
    fields = sf_card_field_values(parser, job_url)
    for field, pair in fields.items():
        value = clean_text((pair or {}).get("value"))
        label = clean_text((pair or {}).get("label")) or ""
        key = f"{field} {label}".casefold()
        if value and any(token in key for token in ("date", "data", "reference date", "posting date")):
            return value
    return None

_merge_sf_page_jobs_v14 = merge_sf_page_jobs

def merge_sf_page_jobs(base: str, parser: SFPageParser) -> list[dict]:
    jobs = _merge_sf_page_jobs_v14(base, parser)
    for job in jobs:
        if not clean_text(job.get("location")):
            job["location"] = sf_card_location(parser, job["url"])
        if not clean_text(job.get("published_at")):
            job["published_at"] = sf_card_date(parser, job["url"])
    return jobs


def _sf_load_page(url: str):
    html_text, final_url = sf_get_html(url)
    parser = SFPageParser()
    parser.feed(html_text)
    return html_text, final_url, parser


def collect_successfactors(company):
    name = company.get("company")
    ats = company.get("ats", {})
    inventory = clean_text(ats.get("inventory_url"))
    if not inventory:
        raise NotCheckable("SuccessFactors inventory URL missing")

    html_text, current_url, parser = _sf_load_page(inventory)
    initial_jobs = merge_sf_page_jobs(current_url, parser)
    initial_total = parse_sf_total(parser.visible_text)

    # Some Career Site Builder /viewalljobs landing pages expose a total but no
    # actual requisition links. Follow only an evidenced same-host /search/ link
    # or form action and adopt it only when it exposes real job links.
    discovered = find_sf_search_url(current_url, parser)
    should_probe_search = (
        not is_sf_search_path(current_url)
        or (initial_total not in (None, 0) and not initial_jobs)
    )
    if discovered and should_probe_search and discovered != current_url:
        d_html, d_url, d_parser = _sf_load_page(discovered)
        d_jobs = merge_sf_page_jobs(d_url, d_parser)
        if d_jobs or parse_sf_total(d_parser.visible_text) == 0:
            html_text, current_url, parser = d_html, d_url, d_parser
            initial_jobs = d_jobs
            initial_total = parse_sf_total(parser.visible_text)

    if not is_sf_search_path(current_url):
        if not discovered:
            raise NotCheckable("No same-host exhaustive /search/, /viewalljobs/ or /go/ inventory exposed by portal")
        if not initial_jobs:
            raise NotCheckable("Evidenced SuccessFactors inventory does not expose public requisition links")

    expected_total = parse_sf_total(parser.visible_text)
    if expected_total is None:
        raise NotCheckable("SuccessFactors page does not expose a reconcilable inventory total")

    visited: set[str] = set()
    inventory_jobs: dict[str, dict] = {}
    page_count = 0

    while True:
        page_count += 1
        if page_count > MAX_PAGES:
            raise NotCheckable("SuccessFactors inventory exceeds safe exhaustive-page limit")
        visited.add(current_url)

        page_total = parse_sf_total(parser.visible_text)
        if page_total is not None and page_total != expected_total:
            raise NotCheckable(f"SuccessFactors total changed during pagination: {expected_total}->{page_total}")

        for item in merge_sf_page_jobs(current_url, parser):
            inventory_jobs[item["url"]] = item

        if len(inventory_jobs) >= expected_total:
            break
        nxt = find_sf_next_url(current_url, parser, visited)
        if not nxt:
            raise NotCheckable(
                f"SuccessFactors inventory not exhaustible: retrieved={len(inventory_jobs)}, total={expected_total}"
            )
        html_text, current_url, parser = _sf_load_page(nxt)

    if len(inventory_jobs) != expected_total:
        raise NotCheckable(
            f"SuccessFactors reconciliation mismatch: retrieved={len(inventory_jobs)}, total={expected_total}"
        )

    if expected_total and not any(clean_text(x.get("location")) for x in inventory_jobs.values()):
        raise NotCheckable("SuccessFactors inventory was exhaustive but location metadata could not be extracted safely")

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
        "source_url": current_url,
    }

_collect_batch_v14_final = collect_batch

def collect_batch(batch: str, workers: int = DEFAULT_WORKERS):
    payload = _collect_batch_v14_final(batch, workers=workers)
    payload["version"] = "1.5"
    write_json(ROOT / f"current_jobs_{batch}.json", payload)
    return payload
'''


def main():
    text = PATH.read_text(encoding="utf-8")
    if MARKER in text:
        print("v1.5 enhancements already present")
        return
    text = text.replace('COLLECTOR_VERSION = "1.4"', 'COLLECTOR_VERSION = "1.5"')
    text = text.replace('job-watch-milano/1.4', 'job-watch-milano/1.5')
    m = re.search(r'\nif __name__ == ["\']__main__["\']:\n\s+raise SystemExit\(main\(\)\)\s*$', text)
    if not m:
        raise SystemExit("Final main guard not found")
    text = text[:m.start()] + CODE + text[m.start():]
    PATH.write_text(text, encoding="utf-8")
    print("Applied generic SuccessFactors v1.5 enhancements")


if __name__ == "__main__":
    main()
