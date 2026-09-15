#!/usr/bin/env python3
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse

import collector as base
import collector_v14b  # noqa: F401 - installs Oracle + Workday hardening

TEAMTAILOR_SCOPE_NAME = "Teamtailor public career board"
TT_COUNT_RE = re.compile(r"\b([\d.,]+)\s+jobs?\b", re.I)
TT_JOB_PATH_RE = re.compile(r"/jobs/(\d+)(?:[-/]|$)", re.I)

_previous_choose = base.choose
_previous_collect_batch = base.collect_batch


class TeamtailorPageParser(HTMLParser):
    """Capture the rendered public job cards without fetching job-detail pages."""

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.visible_parts: list[str] = []
        self.jobs: list[dict] = []
        self.current: dict | None = None
        self.in_job_anchor = False

    def _finish_current(self) -> None:
        if self.current is None:
            return
        title = base.clean_text(" ".join(self.current.get("title_parts") or []))
        parts = [base.clean_text(x) for x in self.current.get("context_parts") or []]
        parts = [x for x in parts if x and x != title]
        self.current["title"] = title
        self.current["context_parts"] = parts
        self.jobs.append(self.current)
        self.current = None
        self.in_job_anchor = False

    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "a":
            return
        a = {str(k).casefold(): v for k, v in attrs if k}
        href = a.get("href")
        if not href:
            return
        absolute = urljoin(self.base_url, href)
        p = urlparse(absolute)
        if p.netloc.casefold() != urlparse(self.base_url).netloc.casefold():
            return
        m = TT_JOB_PATH_RE.search(unquote(p.path))
        if not m:
            return
        self._finish_current()
        self.current = {
            "source_id": m.group(1),
            "url": absolute,
            "title_parts": [],
            "context_parts": [],
        }
        self.in_job_anchor = True

    def handle_endtag(self, tag):
        if tag.casefold() == "a" and self.in_job_anchor:
            self.in_job_anchor = False

    def handle_data(self, data):
        s = base.clean_text(data)
        if not s:
            return
        self.visible_parts.append(s)
        if self.current is not None:
            self.current["context_parts"].append(s)
            if self.in_job_anchor:
                self.current["title_parts"].append(s)

    def close(self):
        super().close()
        self._finish_current()

    @property
    def visible_text(self) -> str:
        return " ".join(self.visible_parts)


def teamtailor_total(text: str) -> int | None:
    matches = []
    for m in TT_COUNT_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(1))
        if digits:
            matches.append(int(digits))
    # Job-board pages normally expose one explicit '<N> jobs' counter. If the
    # page contains conflicting counters, completeness cannot be proven.
    unique = sorted(set(matches))
    return unique[0] if len(unique) == 1 else None


def teamtailor_location(parts: list[str]) -> str | None:
    candidates = [x for x in parts if base.TARGET_LOCATION_RE.search(x or "")]
    if not candidates:
        return None
    # Teamtailor renders department/location/remote metadata as separate short
    # text nodes. The shortest matching node is normally the location label.
    return min(candidates, key=len)


def collect_teamtailor(company: dict):
    name = company.get("company")
    ats = company.get("ats") or {}
    inventory = base.clean_text(ats.get("inventory_url"))
    if not inventory:
        raise base.CollectorError("Teamtailor inventory URL missing")
    p = urlparse(inventory)
    if p.scheme not in {"http", "https"} or not p.netloc:
        raise base.NotCheckable("Teamtailor inventory URL is not a public HTTP(S) board")

    try:
        page_html, final_url = base.get_html(inventory)
    except Exception as e:
        raise base.NotCheckable(f"Teamtailor public board could not be read safely: {e}") from e

    parser = TeamtailorPageParser(final_url)
    parser.feed(page_html)
    parser.close()
    expected = teamtailor_total(parser.visible_text)
    if expected is None:
        raise base.NotCheckable("Teamtailor board does not expose one reconcilable public job total")

    unique: dict[str, dict] = {}
    for raw in parser.jobs:
        sid = base.clean_text(raw.get("source_id"))
        url = base.clean_text(raw.get("url"))
        title = base.clean_text(raw.get("title"))
        if not sid or not url or not title:
            continue
        unique[sid] = raw

    if len(unique) != expected:
        raise base.NotCheckable(
            f"Teamtailor board count mismatch: retrieved={len(unique)}, total={expected}"
        )

    jobs = []
    for sid, raw in unique.items():
        loc = teamtailor_location(raw.get("context_parts") or [])
        if not base.location_matches(loc):
            continue
        jobs.append(
            base.compact_job(
                name,
                sid,
                title=raw.get("title"),
                location=loc,
                canonical=raw.get("url"),
                apply_url=raw.get("url"),
            )
        )

    return {
        "coverage": "VERIFIED",
        "collector": "teamtailor_public_board_metadata",
        "inventory_count": len(unique),
        "jobs": jobs,
        "source_url": final_url,
    }


def verified_smartrecruiters_feed(company: dict) -> bool:
    ats = company.get("ats") or {}
    family = (base.clean_text(ats.get("family")) or "").casefold()
    if "smartrecruiters" not in family or "attrax" in family:
        return False
    tenant = base.clean_text(ats.get("tenant"))
    feed = base.clean_text(ats.get("public_api_or_feed"))
    verification = company.get("verification") or {}
    if verification.get("full_inventory_possible") is not True:
        return False
    if not tenant or not base.SAFE_TENANT_RE.fullmatch(tenant):
        return False
    if not feed:
        return False
    return urlparse(feed).netloc.casefold() == "api.smartrecruiters.com"


def choose(company: dict):
    fn = _previous_choose(company)
    if fn is not None:
        return fn

    ats = company.get("ats") or {}
    family = (base.clean_text(ats.get("family")) or "").casefold()
    verification = company.get("verification") or {}

    if verified_smartrecruiters_feed(company):
        return base.collect_smartrecruiters

    if "teamtailor" in family and verification.get("full_inventory_possible") is True:
        inventory = base.clean_text(ats.get("inventory_url")) or ""
        if "/jobs" in urlparse(inventory).path.casefold():
            return collect_teamtailor

    return None


def collect_batch(batch: str, workers: int = base.DEFAULT_WORKERS):
    payload = _previous_collect_batch(batch, workers=workers)
    scope = list(payload.get("collector_scope") or [])
    if TEAMTAILOR_SCOPE_NAME not in scope:
        scope.append(TEAMTAILOR_SCOPE_NAME)
    payload["collector_scope"] = scope
    base.write_json(base.ROOT / f"current_jobs_{batch}.json", payload)
    return payload


base.choose = choose
base.collect_batch = collect_batch


def main(argv=None):
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
