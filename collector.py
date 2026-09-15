#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1", "jw2", "jw3", "jw4")
TIMEOUT = 30
MAX_PAGES = 250
DEFAULT_WORKERS = 6
COLLECTOR_VERSION = "1.4"
TARGET_LOCATION_RE = re.compile(r"(?<!\w)(milan|milano|rome|roma|london)(?!\w)", re.I)
OPEN_STATUSES = {"NEW", "STILL_OPEN", "UPDATED"}

LOCALE_SEGMENT_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
SAFE_TENANT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
DATEISH_RE = re.compile(
    r"(?:\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|"
    r"\b\d{4}[./-]\d{1,2}[./-]\d{1,2}\b|"
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,\s*\d{4})?\b|"
    r"\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)(?:\s+\d{4})?\b)",
    re.I,
)

SF_TOTAL_PATTERNS = (
    re.compile(r"\bResults?\s+\d+\s*[-–—]\s*\d+\s+of\s+([\d.,\s]+)\b", re.I),
    re.compile(r"\bRisultati\s+\d+\s*[-–—]\s*\d+\s+(?:di|su)\s+([\d.,\s]+)\b", re.I),
    re.compile(r"\bErgebnisse\s+\d+\s*[-–—]\s*\d+\s+von\s+([\d.,\s]+)\b", re.I),
)
SF_ZERO_PATTERNS = (
    re.compile(r"\b0\s+results?\b", re.I),
    re.compile(r"\bno\s+(?:jobs|results?)\b", re.I),
    re.compile(r"\b0\s+risultati\b", re.I),
)

# Explicitly known bad/stale structured mappings. These are intentionally NOT
# requested: a known-wrong tenant/token is not an HTTP failure.
KNOWN_NOT_CHECKED = {
    "bolt": "Known Greenhouse token `bolt` is not a verified public board; skipped without HTTP request.",
    "unilever": "Known Lever tenant `unilever` is not a verified public board; skipped without HTTP request.",
}

# Greenhouse board tokens already exercised successfully by collector v1.2.
# Bolt is deliberately excluded: its old `bolt` token returned 404.
KNOWN_GREENHOUSE_TOKENS = {
    "Adyen": "adyen",
    "N26": "n26",
    "SumUp": "sumup",
    "Trade Republic": "traderepublicbank",
}

_thread_local = threading.local()


class CollectorError(RuntimeError):
    """The selected structured collector should have worked, but failed."""


class NotCheckable(RuntimeError):
    """The portal cannot be proven exhaustive by this generic collector."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def get_session() -> requests.Session:
    """One requests.Session per worker thread: connection reuse without shared-session races."""
    s = getattr(_thread_local, "session", None)
    if s is not None:
        return s

    s = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update(
        {
            "User-Agent": "job-watch-milano/1.4",
            "Accept": "application/json, text/plain, text/html, */*",
        }
    )
    _thread_local.session = s
    return s


def get_response(url: str, params=None, headers=None) -> requests.Response:
    r = get_session().get(url, params=params, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def get_json(url: str, params=None, headers=None):
    return get_response(url, params=params, headers=headers).json()


def get_html(url: str, params=None, headers=None) -> tuple[str, str]:
    r = get_response(url, params=params, headers=headers)
    return r.text, r.url


def post_json(url: str, payload, headers=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    r = get_session().post(url, json=payload, headers=h, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def clean_text(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def html_to_text(v):
    if not v:
        return None
    s = html.unescape(str(v))
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def location_matches(location) -> bool:
    """Match target cities while excluding obvious North-American namesakes."""
    if not location:
        return False
    s = str(location)
    if not TARGET_LOCATION_RE.search(s):
        return False
    if re.search(r"\bLondon\s*,\s*(?:ON|Ontario)(?:\s*,|\b)", s, re.I):
        return False
    if re.search(r"\bLondon\b.*\bCanada\b", s, re.I):
        return False
    if re.search(r"\b(?:Milan|Rome)\s*,\s*[A-Z]{2}\s*,\s*(?:US|USA|United States)\b", s, re.I):
        return False
    return True

def epoch_millis_to_iso(v):
    try:
        n = int(v)
        if n <= 0:
            return None
        if n > 10_000_000_000:
            n /= 1000
        return datetime.fromtimestamp(n, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def canonical_url(job: dict) -> str | None:
    return clean_text(job.get("canonical_url")) or clean_text(job.get("url"))


def metadata_fingerprint(job: dict) -> str:
    """Metadata-only fingerprint, intentionally independent of full job descriptions."""
    effective_date = clean_text(job.get("updated_at")) or clean_text(job.get("published_at"))
    fields = {
        "title": clean_text(job.get("title")),
        "location": clean_text(job.get("location")),
        "department": clean_text(job.get("department")),
        "team": clean_text(job.get("team")),
        "employment_type": clean_text(job.get("employment_type")),
        "date": effective_date,
        "url": canonical_url(job),
    }
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def infer_token(url, hosts):
    if not url:
        return None
    p = urlparse(url)
    if not any(h in p.netloc.casefold() for h in hosts):
        return None
    parts = [x for x in p.path.split("/") if x]
    return parts[-1] if parts else None


def key(company, source_id):
    return f"{company}::{source_id}"


def compact_job(
    company_name: str,
    source_id: Any,
    title=None,
    location=None,
    department=None,
    team=None,
    employment_type=None,
    published_at=None,
    updated_at=None,
    canonical=None,
    apply_url=None,
) -> dict:
    """Canonical metadata-first schema. `url` is retained as a v1.2 compatibility alias."""
    c = clean_text(canonical)
    return {
        "source_id": str(source_id),
        "company": company_name,
        "title": clean_text(title),
        "location": clean_text(location),
        "department": clean_text(department),
        "team": clean_text(team),
        "employment_type": clean_text(employment_type),
        "published_at": clean_text(published_at),
        "updated_at": clean_text(updated_at),
        "canonical_url": c,
        "url": c,
        "apply_url": clean_text(apply_url),
    }


# ---------------------------------------------------------------------------
# Existing structured ATS collectors, metadata-first
# ---------------------------------------------------------------------------

def collect_lever(company):
    name = company.get("company")
    ats = company.get("ats", {})
    tenant = clean_text(ats.get("tenant")) or infer_token(ats.get("inventory_url"), ("jobs.lever.co", "jobs.eu.lever.co"))
    if not tenant:
        raise CollectorError("Lever tenant missing")
    eu = "jobs.eu.lever.co" in (ats.get("inventory_url") or "").casefold()
    base = "https://api.eu.lever.co/v0/postings" if eu else "https://api.lever.co/v0/postings"
    url = f"{base}/{tenant}"
    all_jobs = []
    skip = 0
    limit = 100
    for _ in range(MAX_PAGES):
        page = get_json(url, {"mode": "json", "skip": skip, "limit": limit})
        if not isinstance(page, list):
            raise CollectorError("Unexpected Lever response")
        all_jobs.extend(page)
        if len(page) < limit:
            break
        skip += len(page)
    else:
        raise CollectorError("Lever pagination safety limit")

    jobs = []
    for raw in all_jobs:
        c = raw.get("categories") or {}
        locs = c.get("allLocations") or []
        loc = " | ".join(map(str, locs)) if locs else c.get("location")
        j = compact_job(
            name,
            raw.get("id"),
            title=raw.get("text"),
            location=loc,
            department=c.get("department"),
            team=c.get("team"),
            employment_type=c.get("commitment"),
            published_at=epoch_millis_to_iso(raw.get("createdAt")),
            updated_at=epoch_millis_to_iso(raw.get("updatedAt")),
            canonical=raw.get("hostedUrl"),
            apply_url=raw.get("applyUrl"),
        )
        if location_matches(j["location"]):
            jobs.append(j)
    return {"coverage": "VERIFIED", "collector": "lever_api_metadata", "inventory_count": len(all_jobs), "jobs": jobs, "source_url": url}


def collect_ashby(company):
    name = company.get("company")
    ats = company.get("ats", {})
    tenant = clean_text(ats.get("tenant")) or infer_token(ats.get("inventory_url"), ("jobs.ashbyhq.com",))
    if not tenant:
        raise CollectorError("Ashby board name missing")
    url = f"https://api.ashbyhq.com/posting-api/job-board/{tenant}"
    data = get_json(url, {"includeCompensation": "false"})
    all_jobs = data.get("jobs")
    if not isinstance(all_jobs, list):
        raise CollectorError("Unexpected Ashby response")

    jobs = []
    for raw in all_jobs:
        locs = [clean_text(raw.get("location"))]
        for item in raw.get("secondaryLocations") or []:
            if isinstance(item, dict):
                locs.append(clean_text(item.get("location")))
        loc = " | ".join(x for x in locs if x)
        source_id = raw.get("id") or raw.get("jobPostingId") or raw.get("title")
        j = compact_job(
            name,
            source_id,
            title=raw.get("title"),
            location=loc,
            department=raw.get("department"),
            team=raw.get("team"),
            employment_type=raw.get("employmentType"),
            published_at=raw.get("publishedAt"),
            updated_at=raw.get("updatedAt"),
            canonical=raw.get("jobUrl") or raw.get("url"),
            apply_url=raw.get("applyUrl"),
        )
        if location_matches(j["location"]):
            jobs.append(j)
    return {"coverage": "VERIFIED", "collector": "ashby_public_api_metadata", "inventory_count": len(all_jobs), "jobs": jobs, "source_url": url}


def greenhouse_token(company):
    ats = company.get("ats", {})
    token = clean_text(ats.get("tenant")) or infer_token(ats.get("inventory_url"), ("greenhouse.io",))
    if token and SAFE_TENANT_RE.fullmatch(token):
        return token
    return KNOWN_GREENHOUSE_TOKENS.get(company.get("company"))


def collect_greenhouse(company):
    name = company.get("company")
    token = greenhouse_token(company)
    if not token:
        raise CollectorError("Greenhouse token missing")
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    # No content=true: the inventory metadata is enough for reconciliation.
    data = get_json(url)
    all_jobs = data.get("jobs")
    if not isinstance(all_jobs, list):
        raise CollectorError("Unexpected Greenhouse response")
    total = (data.get("meta") or {}).get("total")
    if total is not None and int(total) != len(all_jobs):
        raise CollectorError(f"Greenhouse count mismatch {total}!={len(all_jobs)}")

    jobs = []
    for raw in all_jobs:
        deps = raw.get("departments") or []
        dept = " | ".join(
            clean_text(x.get("name")) for x in deps if isinstance(x, dict) and clean_text(x.get("name"))
        )
        loc = clean_text((raw.get("location") or {}).get("name"))
        j = compact_job(
            name,
            raw.get("id"),
            title=raw.get("title"),
            location=loc,
            department=dept,
            updated_at=raw.get("updated_at"),
            canonical=raw.get("absolute_url"),
            apply_url=raw.get("absolute_url"),
        )
        if location_matches(loc):
            jobs.append(j)
    return {"coverage": "VERIFIED", "collector": "greenhouse_job_board_api_metadata", "inventory_count": len(all_jobs), "jobs": jobs, "source_url": url}


def sr_identifier(ats):
    if clean_text(ats.get("tenant")):
        return clean_text(ats.get("tenant"))
    for u in (ats.get("inventory_url"), ats.get("career_site")):
        if not u:
            continue
        p = urlparse(u)
        if "smartrecruiters.com" not in p.netloc.casefold():
            continue
        parts = [x for x in p.path.split("/") if x]
        if parts:
            return parts[0]
    return None


def collect_smartrecruiters(company):
    name = company.get("company")
    ats = company.get("ats", {})
    ident = sr_identifier(ats)
    if not ident:
        raise CollectorError("SmartRecruiters identifier missing")
    url = f"https://api.smartrecruiters.com/v1/companies/{ident}/postings"
    offset = 0
    limit = 100
    all_jobs = []
    total = None
    for _ in range(MAX_PAGES):
        data = get_json(url, {"limit": limit, "offset": offset, "destination": "PUBLIC"})
        page = data.get("content")
        if not isinstance(page, list):
            raise CollectorError("Unexpected SmartRecruiters response")
        if total is None:
            total = int(data.get("totalFound", len(page)))
        all_jobs.extend(page)
        if len(all_jobs) >= total:
            break
        if not page:
            raise CollectorError("SmartRecruiters paging stopped early")
        offset += len(page)
    else:
        raise CollectorError("SmartRecruiters pagination safety limit")
    if total is not None and len(all_jobs) != total:
        raise CollectorError(f"SmartRecruiters count mismatch {total}!={len(all_jobs)}")

    jobs = []
    for raw in all_jobs:
        loc = raw.get("location") or {}
        loc_text = ", ".join(str(x) for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)
        if not location_matches(loc_text):
            continue
        dept = raw.get("department") or {}
        employment = raw.get("typeOfEmployment") or {}
        ref = clean_text(raw.get("ref"))
        canonical = ref if ref and ref.startswith(("http://", "https://")) else None
        j = compact_job(
            name,
            raw.get("id") or raw.get("uuid"),
            title=raw.get("name"),
            location=loc_text,
            department=dept.get("label") if isinstance(dept, dict) else dept,
            employment_type=employment.get("label") if isinstance(employment, dict) else employment,
            published_at=raw.get("releasedDate"),
            updated_at=raw.get("updatedDate") or raw.get("lastUpdatedDate"),
            canonical=canonical,
            apply_url=raw.get("applyUrl"),
        )
        jobs.append(j)
    return {"coverage": "VERIFIED", "collector": "smartrecruiters_posting_api_metadata", "inventory_count": len(all_jobs), "jobs": jobs, "source_url": url}


def workday_config(company):
    ats = company.get("ats", {})
    inventory = clean_text(ats.get("inventory_url"))
    if not inventory:
        raise CollectorError("Workday inventory URL missing")
    p = urlparse(inventory)
    host = p.netloc
    if "myworkdayjobs.com" not in host.casefold():
        raise CollectorError("Workday inventory is not a myworkdayjobs.com URL")
    tenant = host.split(".")[0]
    parts = [unquote(x) for x in p.path.split("/") if x]
    while parts and LOCALE_SEGMENT_RE.fullmatch(parts[0]):
        parts.pop(0)
    if not parts:
        raise CollectorError("Workday career-site name missing from URL")
    site = parts[0]
    return host, tenant, site


def workday_source_id(raw: dict, external_path: str) -> str:
    for field in ("jobReqId", "jobRequisitionId", "requisitionId"):
        if clean_text(raw.get(field)):
            return str(raw[field])
    tail = unquote(urlparse(external_path).path).rstrip("/").split("/")[-1]
    # Common Workday public paths end in _R12345, _JR-12345, _REQ12345, etc.
    m = re.search(r"(?:_|-)((?:JR-|REQ-?|R-?)?\d{4,})$", tail, re.I)
    if m:
        return m.group(1)
    return external_path


def collect_workday(company):
    name = company.get("company")
    host, tenant, site = workday_config(company)
    search_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    referer = f"https://{host}/{site}"
    limit = 20
    offset = 0
    total = None
    all_jobs = []

    for _ in range(MAX_PAGES):
        payload = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""}
        data = post_json(
            search_url,
            payload,
            headers={"Accept": "application/json", "Referer": referer, "Origin": f"https://{host}"},
        )
        page = data.get("jobPostings")
        if not isinstance(page, list):
            raise CollectorError("Unexpected Workday CXS response")
        if total is None:
            total = int(data.get("total", len(page)))
        all_jobs.extend(page)
        if len(all_jobs) >= total:
            break
        if not page:
            raise CollectorError(f"Workday paging stopped early: retrieved={len(all_jobs)}, total={total}")
        offset += len(page)
    else:
        raise CollectorError("Workday pagination safety limit")

    if total is not None and len(all_jobs) != total:
        raise CollectorError(f"Workday count mismatch: total={total}, retrieved={len(all_jobs)}")

    jobs = []
    for raw in all_jobs:
        loc = clean_text(raw.get("locationsText"))
        if not location_matches(loc):
            continue
        external_path = clean_text(raw.get("externalPath"))
        if not external_path:
            # Inventory entry without a public path cannot be stably reconciled.
            continue
        canonical = f"https://{host}/{site}{external_path}"
        bullet_fields = raw.get("bulletFields") or []
        employment = None
        if isinstance(bullet_fields, list):
            # Some Workday inventories expose time type in bulletFields. Keep it
            # only when it is explicit; never infer from title/description.
            for value in bullet_fields:
                s = clean_text(value)
                if s and re.search(r"\b(full[ -]?time|part[ -]?time|intern(?:ship)?|temporary|contract)\b", s, re.I):
                    employment = s
                    break
        j = compact_job(
            name,
            workday_source_id(raw, external_path),
            title=raw.get("title"),
            location=loc,
            employment_type=employment,
            published_at=raw.get("postedOn"),
            updated_at=raw.get("updatedOn"),
            canonical=canonical,
            apply_url=canonical,
        )
        jobs.append(j)

    return {"coverage": "VERIFIED", "collector": "workday_cxs_metadata", "inventory_count": len(all_jobs), "jobs": jobs, "source_url": search_url}


# ---------------------------------------------------------------------------
# Workable public board
# ---------------------------------------------------------------------------

def workable_tenant(ats: dict) -> str | None:
    tenant = clean_text(ats.get("tenant"))
    if tenant and SAFE_TENANT_RE.fullmatch(tenant):
        return tenant
    inventory = clean_text(ats.get("inventory_url"))
    if not inventory:
        return None
    p = urlparse(inventory)
    if "apply.workable.com" not in p.netloc.casefold():
        return None
    parts = [x for x in p.path.split("/") if x]
    if parts and SAFE_TENANT_RE.fullmatch(parts[0]):
        return parts[0]
    return None


def collect_workable(company):
    name = company.get("company")
    ats = company.get("ats", {})
    tenant = workable_tenant(ats)
    if not tenant:
        raise CollectorError("Workable public board tenant missing")
    # Official unauthenticated public-jobs endpoint; details=false omits descriptions.
    url = f"https://www.workable.com/api/accounts/{tenant}"
    data = get_json(url, {"details": "false"})
    all_jobs = data.get("jobs")
    if not isinstance(all_jobs, list):
        raise CollectorError("Unexpected Workable public account response")

    jobs = []
    for raw in all_jobs:
        loc = ", ".join(str(x) for x in (raw.get("city"), raw.get("state"), raw.get("country")) if x)
        j = compact_job(
            name,
            raw.get("shortcode") or raw.get("code") or raw.get("id"),
            title=raw.get("title"),
            location=loc,
            department=raw.get("department"),
            employment_type=raw.get("employment_type"),
            published_at=raw.get("published_on") or raw.get("created_at"),
            updated_at=raw.get("updated_at"),
            # Workable docs: application_url is the public job page; url is the application form.
            canonical=raw.get("application_url") or raw.get("shortlink"),
            apply_url=raw.get("url"),
        )
        if location_matches(j["location"]):
            jobs.append(j)
    return {"coverage": "VERIFIED", "collector": "workable_public_jobs_metadata", "inventory_count": len(all_jobs), "jobs": jobs, "source_url": url}


# ---------------------------------------------------------------------------
# SAP SuccessFactors / Recruiting Marketing (jobs2web-style public inventories)
# ---------------------------------------------------------------------------

class SFPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.anchors: list[dict] = []
        self.rows: list[dict] = []
        self._anchor: dict | None = None
        self._row: dict | None = None
        self._cell: list[str] | None = None

    @staticmethod
    def _attrs(attrs) -> dict:
        return {str(k).casefold(): v for k, v in attrs if k}

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        a = self._attrs(attrs)
        if tag == "tr":
            self._row = {"cells": [], "anchors": []}
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "a":
            self._anchor = {
                "href": a.get("href"),
                "title": a.get("title"),
                "aria_label": a.get("aria-label"),
                "rel": a.get("rel"),
                "text": [],
            }

    def handle_data(self, data):
        s = clean_text(data)
        if not s:
            return
        self.text_parts.append(s)
        if self._cell is not None:
            self._cell.append(s)
        if self._anchor is not None:
            self._anchor["text"].append(s)

    def handle_endtag(self, tag):
        tag = tag.casefold()
        if tag == "a" and self._anchor is not None:
            anchor = dict(self._anchor)
            anchor["text"] = clean_text(" ".join(anchor.get("text") or []))
            self.anchors.append(anchor)
            if self._row is not None:
                self._row["anchors"].append(anchor)
            self._anchor = None
        elif tag in ("td", "th") and self._cell is not None:
            if self._row is not None:
                self._row["cells"].append(clean_text(" ".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None

    @property
    def visible_text(self) -> str:
        return " ".join(self.text_parts)


def parse_sf_total(text: str) -> int | None:
    for pat in SF_TOTAL_PATTERNS:
        m = pat.search(text)
        if m:
            digits = re.sub(r"\D", "", m.group(1))
            if digits:
                return int(digits)
    if any(p.search(text) for p in SF_ZERO_PATTERNS):
        return 0
    return None


def sf_job_source_id(url: str) -> str:
    path = unquote(urlparse(url).path).rstrip("/")
    for token in reversed([x for x in path.split("/") if x]):
        if re.fullmatch(r"\d{4,}", token):
            return token
    return hashlib.sha256(url.encode()).hexdigest()[:20]


def normalize_abs_url(base: str, href: str | None) -> str | None:
    if not href:
        return None
    u = urljoin(base, href)
    p = urlparse(u)
    if p.scheme not in ("http", "https"):
        return None
    return u


def same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc.casefold() == urlparse(b).netloc.casefold()


def is_sf_search_path(url: str) -> bool:
    p = urlparse(url).path.casefold()
    return "/search/" in p or p.endswith("/search") or "/viewalljobs/" in p or p.endswith("/viewalljobs")


def find_sf_search_url(base: str, parser: SFPageParser) -> str | None:
    candidates = []
    for a in parser.anchors:
        u = normalize_abs_url(base, a.get("href"))
        if not u or not same_host(base, u):
            continue
        if is_sf_search_path(u):
            candidates.append(u)
    if not candidates:
        return None
    # Prefer an unfiltered /search/ or /viewalljobs/ link, then the shortest path/query.
    candidates = list(dict.fromkeys(candidates))
    candidates.sort(key=lambda u: (0 if not urlparse(u).query else 1, len(urlparse(u).path), len(u)))
    return candidates[0]


def sf_job_anchors(base: str, parser: SFPageParser) -> list[tuple[str, str | None]]:
    out = []
    seen = set()
    for a in parser.anchors:
        u = normalize_abs_url(base, a.get("href"))
        if not u or not same_host(base, u):
            continue
        path = urlparse(u).path.casefold()
        if "/job/" not in path:
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append((u, clean_text(a.get("text")) or clean_text(a.get("title"))))
    return out


def strip_sf_title_prefix(value: str | None, title: str | None) -> str | None:
    s = clean_text(value)
    t = clean_text(title)
    if not s or not t:
        return s
    for _ in range(3):
        if s[:len(t)].casefold() != t.casefold():
            break
        s = clean_text(s[len(t):])
        if not s:
            break
    return s


def parse_sf_rows(base: str, parser: SFPageParser) -> dict[str, dict]:
    """Extract jobs from classic SuccessFactors grid rows (Title / Location / Date)."""
    found: dict[str, dict] = {}
    for row in parser.rows:
        job_anchor = None
        for a in row.get("anchors") or []:
            u = normalize_abs_url(base, a.get("href"))
            if u and same_host(base, u) and "/job/" in urlparse(u).path.casefold():
                job_anchor = (u, clean_text(a.get("text")) or clean_text(a.get("title")))
                break
        if not job_anchor:
            continue
        u, title = job_anchor
        cells = [clean_text(x) for x in row.get("cells") or [] if clean_text(x)]
        non_title = []
        for value in cells:
            if value == title:
                continue
            cleaned = strip_sf_title_prefix(value, title)
            if cleaned:
                non_title.append(cleaned)
        date_value = next(
            (x for x in reversed(non_title) if len(x) <= 40 and DATEISH_RE.search(x or "")),
            None,
        )
        location = next((x for x in non_title if x != date_value), None)
        found[u] = {"url": u, "title": title, "location": location, "published_at": date_value}
    return found

def merge_sf_page_jobs(base: str, parser: SFPageParser) -> list[dict]:
    rows = parse_sf_rows(base, parser)
    jobs = []
    for u, title in sf_job_anchors(base, parser):
        row = rows.get(u) or {}
        jobs.append(
            {
                "url": u,
                "title": row.get("title") or title,
                "location": row.get("location"),
                "published_at": row.get("published_at"),
            }
        )
    return jobs


def sf_startrow(url: str) -> int:
    try:
        vals = parse_qs(urlparse(url).query).get("startrow") or []
        return int(vals[0]) if vals else 0
    except Exception:
        return 0


def find_sf_next_url(base: str, parser: SFPageParser, visited: set[str]) -> str | None:
    explicit = []
    paged = []
    current_start = sf_startrow(base)
    for a in parser.anchors:
        u = normalize_abs_url(base, a.get("href"))
        if not u or not same_host(base, u) or u in visited:
            continue
        text = " ".join(
            x for x in (clean_text(a.get("text")), clean_text(a.get("title")), clean_text(a.get("aria_label"))) if x
        ).casefold()
        rel = (clean_text(a.get("rel")) or "").casefold()
        if "next" in text or "successiv" in text or "weiter" in text or "next" in rel:
            # Do not follow a generic same-host "next" link unless it is still
            # clearly part of the SuccessFactors inventory/pagination surface.
            if is_sf_search_path(u) or sf_startrow(u) > current_start:
                explicit.append(u)
            continue
        start = sf_startrow(u)
        if start > current_start:
            paged.append((start, u))
    if explicit:
        return explicit[0]
    if paged:
        paged.sort(key=lambda x: x[0])
        return paged[0][1]
    return None


def sf_get_html(url: str) -> tuple[str, str]:
    """SAP access-denied pages are uncheckable, not collector failures."""
    try:
        return get_html(url)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in {401, 403, 404, 410}:
            raise NotCheckable(
                f"SuccessFactors public inventory not enumerable from runner (HTTP {status})"
            ) from e
        raise

    except requests.exceptions.SSLError as e:
        raise NotCheckable(
            "SuccessFactors public inventory is not safely enumerable because TLS validation failed"
        ) from e

def collect_successfactors(company):
    name = company.get("company")
    ats = company.get("ats", {})
    inventory = clean_text(ats.get("inventory_url"))
    if not inventory:
        raise NotCheckable("SuccessFactors inventory URL missing")

    # We only follow URLs actually present in the mapped portal. No guessed API endpoint.
    html_text, current_url = sf_get_html(inventory)
    parser = SFPageParser()
    parser.feed(html_text)

    if not is_sf_search_path(current_url):
        discovered = find_sf_search_url(current_url, parser)
        if not discovered:
            raise NotCheckable("No same-host exhaustive /search/ or /viewalljobs/ link exposed by portal")
        html_text, current_url = sf_get_html(discovered)
        parser = SFPageParser()
        parser.feed(html_text)

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
        html_text, current_url = sf_get_html(nxt)
        parser = SFPageParser()
        parser.feed(html_text)

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
        j = compact_job(
            name,
            sf_job_source_id(raw["url"]),
            title=raw.get("title"),
            location=loc,
            published_at=raw.get("published_at"),
            canonical=raw.get("url"),
            apply_url=raw.get("url"),
        )
        jobs.append(j)

    return {
        "coverage": "VERIFIED",
        "collector": "successfactors_jobs2web_metadata",
        "inventory_count": len(inventory_jobs),
        "jobs": jobs,
        "source_url": inventory,
    }


# ---------------------------------------------------------------------------
# Dispatch, reconciliation, concurrent batch execution
# ---------------------------------------------------------------------------

def known_skip_reason(company: dict) -> str | None:
    name = (clean_text(company.get("company")) or "").casefold()
    ats = company.get("ats") or {}
    family = (clean_text(ats.get("family")) or "").casefold()
    tenant = (clean_text(ats.get("tenant")) or "").casefold()
    if name == "bolt" and "greenhouse" in family and (not tenant or tenant == "bolt"):
        return KNOWN_NOT_CHECKED["bolt"]
    if name == "unilever" and "lever" in family and (not tenant or tenant == "unilever"):
        return KNOWN_NOT_CHECKED["unilever"]
    return None


def choose(company):
    ats = company.get("ats") or {}
    family = (clean_text(ats.get("family")) or "").casefold()
    inventory = clean_text(ats.get("inventory_url")) or ""
    host = urlparse(inventory).netloc.casefold()

    if "workday" in family and "myworkdayjobs.com" in host:
        return collect_workday

    if "ashby" in family and ("ashbyhq.com" in host or clean_text(ats.get("tenant"))):
        return collect_ashby

    if "greenhouse" in family and greenhouse_token(company):
        return collect_greenhouse

    if "lever" in family:
        tenant = clean_text(ats.get("tenant"))
        if "lever.co" in host or (tenant and SAFE_TENANT_RE.fullmatch(tenant) and family.strip() == "lever"):
            return collect_lever

    if "smartrecruiters" in family and "attrax" not in family:
        ident = clean_text(ats.get("tenant"))
        if "smartrecruiters.com" in host or (ident and SAFE_TENANT_RE.fullmatch(ident) and family.strip() == "smartrecruiters"):
            return collect_smartrecruiters

    # Only a direct Workable board, never "Workable embedded in custom site".
    if family.strip() == "workable" and workable_tenant(ats):
        return collect_workable

    # Generic Career Site Builder / jobs2web pages. Exclude custom frontends that
    # merely mention SuccessFactors as a backend (e.g. Phenom/Microsoft custom portal).
    sf_excluded = any(x in family for x in ("phenom", "custom candidate portal", "backend +", "embedded"))
    if "successfactors" in family and not sf_excluded:
        return collect_successfactors

    return None


def previous_index(path: Path) -> dict[str, dict]:
    """Read v1.2/v1.3 history; metadata fingerprint is recomputed on both sides."""
    prev = read_json(path, {}) or {}
    idx = {}
    for c in prev.get("companies", []):
        name = c.get("company")
        for j in c.get("jobs", []):
            if name and j.get("source_id"):
                idx[key(name, str(j["source_id"]))] = j
    return idx


def unsupported_result(company, reason=None):
    return {
        "coverage": "NOT_CHECKED",
        "collector": "unsupported_or_unverified_v1_3",
        "inventory_count": None,
        "jobs": [],
        "reason": reason or "ATS family/method is not safely enumerable by collector v1.3",
        "source_url": (company.get("ats") or {}).get("inventory_url"),
    }


def collect_company(company: dict) -> tuple[dict, bool]:
    skip = known_skip_reason(company)
    if skip:
        return unsupported_result(company, skip), False

    fn = choose(company)
    if fn is None:
        return unsupported_result(company), False

    try:
        result = fn(company)
        result["reason"] = None
        return result, True
    except NotCheckable as e:
        return {
            "coverage": "NOT_CHECKED",
            "collector": getattr(fn, "__name__", "collector"),
            "inventory_count": None,
            "jobs": [],
            "reason": f"NotCheckable: {e}",
            "source_url": (company.get("ats") or {}).get("inventory_url"),
        }, True
    except Exception as e:
        return {
            "coverage": "FAILED",
            "collector": getattr(fn, "__name__", "collector"),
            "inventory_count": None,
            "jobs": [],
            "reason": f"{type(e).__name__}: {e}",
            "source_url": (company.get("ats") or {}).get("inventory_url"),
        }, True


def reconcile_company(company: dict, result: dict, prev: dict[str, dict]) -> tuple[dict, dict[str, int]]:
    name = company.get("company")
    current = []
    ids = set()
    counts = {"target_jobs_open": 0, "NEW": 0, "STILL_OPEN": 0, "UPDATED": 0, "CLOSED": 0, "UNKNOWN": 0}

    for j in result["jobs"]:
        sid = str(j["source_id"])
        k = key(name, sid)
        old = prev.get(k)
        j["fingerprint"] = metadata_fingerprint(j)
        if old is None:
            j["status"] = "NEW"
        elif metadata_fingerprint(old) != j["fingerprint"]:
            j["status"] = "UPDATED"
        else:
            j["status"] = "STILL_OPEN"
        ids.add(sid)
        current.append(j)

    for k, old in prev.items():
        if not k.startswith(f"{name}::"):
            continue
        sid = str(old.get("source_id"))
        if sid in ids or old.get("status") not in OPEN_STATUSES:
            continue
        x = dict(old)
        # Strip heavy v1.2-only payload when carrying a closed/unknown historical row.
        x.pop("description", None)
        x.pop("compensation", None)
        x["company"] = x.get("company") or name
        x["canonical_url"] = canonical_url(x)
        x["url"] = x.get("canonical_url")
        x["fingerprint"] = metadata_fingerprint(x)
        x["status"] = "CLOSED" if result["coverage"] == "VERIFIED" else "UNKNOWN"
        current.append(x)

    for j in current:
        st = j.get("status")
        if st in counts:
            counts[st] += 1
        if st in OPEN_STATUSES:
            counts["target_jobs_open"] += 1

    company_out = {
        "company": name,
        "mapping_level": (company.get("verification") or {}).get("level"),
        "ats_family": (company.get("ats") or {}).get("family"),
        "coverage": result["coverage"],
        "collector": result["collector"],
        "inventory_count": result["inventory_count"],
        "target_jobs_count": sum(1 for j in current if j.get("status") in OPEN_STATUSES),
        "source_url": result.get("source_url"),
        "reason": result.get("reason"),
        "jobs": current,
    }
    return company_out, counts


def collect_batch(batch: str, workers: int = DEFAULT_WORKERS):
    mp = ROOT / f"ats_mapping_{batch}.json"
    out = ROOT / f"current_jobs_{batch}.json"
    mapping = read_json(mp)
    if not mapping:
        raise CollectorError(f"Missing {mp.name}")

    companies = mapping.get("companies") or []
    prev = previous_index(out)
    raw_results: list[tuple[dict, bool] | None] = [None] * len(companies)

    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), DEFAULT_WORKERS))) as pool:
        future_to_idx = {pool.submit(collect_company, c): i for i, c in enumerate(companies)}
        for future in as_completed(future_to_idx):
            i = future_to_idx[future]
            try:
                raw_results[i] = future.result()
            except Exception as e:
                # Defensive fallback: one worker must never prevent an entry for the company.
                c = companies[i]
                raw_results[i] = (
                    {
                        "coverage": "FAILED",
                        "collector": "worker_guard",
                        "inventory_count": None,
                        "jobs": [],
                        "reason": f"{type(e).__name__}: {e}",
                        "source_url": (c.get("ats") or {}).get("inventory_url"),
                    },
                    False,
                )

    summary = {
        "companies_total": len(companies),
        "collector_supported": 0,
        "VERIFIED": 0,
        "FAILED": 0,
        "NOT_CHECKED": 0,
        "target_jobs_open": 0,
        "NEW": 0,
        "STILL_OPEN": 0,
        "UPDATED": 0,
        "CLOSED": 0,
        "UNKNOWN": 0,
    }
    companies_out = []

    for company, pair in zip(companies, raw_results):
        assert pair is not None
        result, supported = pair
        if supported:
            summary["collector_supported"] += 1
        company_out, counts = reconcile_company(company, result, prev)
        coverage = result["coverage"]
        summary[coverage] += 1
        for k, v in counts.items():
            summary[k] += v
        companies_out.append(company_out)

    payload = {
        "version": COLLECTOR_VERSION,
        "batch": mapping.get("batch") or batch.upper(),
        "batch_name": mapping.get("batch_name"),
        "generated_at": utc_now(),
        "collector_scope": [
            "Lever",
            "Ashby",
            "Greenhouse",
            "SmartRecruiters",
            "Workday CXS",
            "SAP SuccessFactors / jobs2web",
            "Workable",
        ],
        "location_scope": ["Milan", "Milano", "Rome", "Roma", "London"],
        "coverage_note": (
            "VERIFIED means the structured/public inventory was exhausted and reconciled in this run. "
            "A recognized but non-exhaustible portal remains NOT_CHECKED; request/runtime failures on a "
            "valid structured method are FAILED."
        ),
        "summary": summary,
        "companies": companies_out,
    }
    write_json(out, payload)
    return payload


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Job Watch ATS collector")
    p.add_argument("--batch", default="all", choices=("all",) + BATCHES)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Concurrent companies; capped at 6")
    # Kept for workflow/backward compatibility; v1.3 does not sleep between companies.
    p.add_argument("--sleep", type=float, default=0.0, help=argparse.SUPPRESS)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    batches = BATCHES if args.batch == "all" else (args.batch,)
    workers = max(1, min(args.workers, DEFAULT_WORKERS))
    for batch in batches:
        r = collect_batch(batch, workers=workers)
        print(batch.upper(), json.dumps(r["summary"], ensure_ascii=False))
        for company in r.get("companies", []):
            if company.get("coverage") in {"FAILED", "NOT_CHECKED"} and company.get("reason"):
                # Keep the log useful without dumping job payloads.
                if company.get("coverage") == "FAILED" or company.get("company") in {"Bolt", "Unilever"}:
                    print(
                        f"  {company.get('coverage')} | {company.get('company')} | "
                        f"{company.get('collector')} | {company.get('reason')}"
                    )
    return 0
# === JOB WATCH V1.4 STANDALONE ENHANCEMENTS ===
# Generic extensions validated on the ats-oracle-v14 branch. No company-specific
# endpoint guessing lives here: verified backend URLs belong in the mapping JSONs.

ORACLE_SCOPE_NAME = "Oracle Recruiting Cloud / Oracle HCM Candidate Experience"
TEAMTAILOR_SCOPE_NAME = "Teamtailor public career board"
ORACLE_HOST_RE = re.compile(r"https?://([A-Za-z0-9.-]+\.oraclecloud\.com)(?=[:/\"'\\]|$)", re.I)
ORACLE_SITE_RE = re.compile(r"/sites/([^/?#]+)(?:/|$)", re.I)
ORACLE_PAGE_LIMIT = 25
TT_COUNT_RE = re.compile(r"\b([\d.,]+)\s+jobs?\b", re.I)
TT_JOB_PATH_RE = re.compile(r"/jobs/(\d+)(?:[-/]|$)", re.I)
SF_SHOWING_TOTAL_RE = re.compile(r"\bShowing\s+\d+\s+to\s+\d+\s+of\s+([\d.,\s]+)\s+Jobs?\b", re.I)

if not any(getattr(p, "pattern", None) == SF_SHOWING_TOTAL_RE.pattern for p in SF_TOTAL_PATTERNS):
    SF_TOTAL_PATTERNS = tuple(SF_TOTAL_PATTERNS) + (SF_SHOWING_TOTAL_RE,)

_is_sf_search_path_v13 = is_sf_search_path

def is_sf_search_path(url: str) -> bool:
    if _is_sf_search_path_v13(url):
        return True
    return "/go/" in urlparse(url).path.casefold()


_collect_workday_v13 = collect_workday

def collect_workday(company):
    last_error = None
    for _attempt in range(2):
        try:
            return _collect_workday_v13(company)
        except requests.exceptions.JSONDecodeError as e:
            last_error = e
            continue
        except CollectorError as e:
            message = str(e).casefold()
            if "pagination safety limit" in message:
                raise NotCheckable(f"Workday inventory exceeds safe exhaustive-page limit: {e}") from e
            if "paging stopped early" not in message and "count mismatch" not in message:
                raise
            last_error = e
    if isinstance(last_error, requests.exceptions.JSONDecodeError):
        raise NotCheckable(f"Workday returned non-JSON inventory data after retry: {last_error}")
    raise NotCheckable(f"Workday inventory changed during enumeration after retry: {last_error}")


_collect_smartrecruiters_v13 = collect_smartrecruiters

def collect_smartrecruiters(company):
    last_error = None
    for _attempt in range(2):
        try:
            return _collect_smartrecruiters_v13(company)
        except CollectorError as e:
            message = str(e).casefold()
            if "count mismatch" not in message and "paging stopped early" not in message:
                raise
            last_error = e
    raise NotCheckable(f"SmartRecruiters inventory changed during enumeration after retry: {last_error}")


class TeamtailorPageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.visible_parts = []
        self.jobs = []
        self.current = None
        self.in_job_anchor = False

    def _finish_current(self):
        if self.current is None:
            return
        title = clean_text(" ".join(self.current.get("title_parts") or []))
        parts = [clean_text(x) for x in self.current.get("context_parts") or []]
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
        self.current = {"source_id": m.group(1), "url": absolute, "title_parts": [], "context_parts": []}
        self.in_job_anchor = True

    def handle_endtag(self, tag):
        if tag.casefold() == "a" and self.in_job_anchor:
            self.in_job_anchor = False

    def handle_data(self, data):
        s = clean_text(data)
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
    def visible_text(self):
        return " ".join(self.visible_parts)


def teamtailor_total(text: str):
    matches = []
    for m in TT_COUNT_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(1))
        if digits:
            matches.append(int(digits))
    unique = sorted(set(matches))
    return unique[0] if len(unique) == 1 else None


def teamtailor_location(parts):
    candidates = [x for x in parts if TARGET_LOCATION_RE.search(x or "")]
    return min(candidates, key=len) if candidates else None


def collect_teamtailor(company):
    name = company.get("company")
    ats = company.get("ats") or {}
    inventory = clean_text(ats.get("inventory_url"))
    if not inventory:
        raise CollectorError("Teamtailor inventory URL missing")
    try:
        page_html, final_url = get_html(inventory)
    except Exception as e:
        raise NotCheckable(f"Teamtailor public board could not be read safely: {e}") from e
    parser = TeamtailorPageParser(final_url)
    parser.feed(page_html)
    parser.close()
    expected = teamtailor_total(parser.visible_text)
    if expected is None:
        raise NotCheckable("Teamtailor board does not expose one reconcilable public job total")
    unique = {}
    for raw in parser.jobs:
        sid = clean_text(raw.get("source_id"))
        url = clean_text(raw.get("url"))
        title = clean_text(raw.get("title"))
        if sid and url and title:
            unique[sid] = raw
    if len(unique) != expected:
        raise NotCheckable(f"Teamtailor board count mismatch: retrieved={len(unique)}, total={expected}")
    jobs = []
    for sid, raw in unique.items():
        loc = teamtailor_location(raw.get("context_parts") or [])
        if not location_matches(loc):
            continue
        jobs.append(compact_job(name, sid, title=raw.get("title"), location=loc, canonical=raw.get("url"), apply_url=raw.get("url")))
    return {"coverage": "VERIFIED", "collector": "teamtailor_public_board_metadata", "inventory_count": len(unique), "jobs": jobs, "source_url": final_url}


def oracle_family(company):
    family = (clean_text((company.get("ats") or {}).get("family")) or "").casefold()
    if "taleo" in family:
        return False
    return any(x in family for x in ("oracle recruiting cloud", "oracle hcm", "oracle fusion"))


def oracle_site_from_inventory(inventory: str):
    m = ORACLE_SITE_RE.search(urlparse(inventory).path)
    if not m:
        return None
    site = unquote(m.group(1)).strip()
    return site if site and SAFE_TENANT_RE.fullmatch(site) else None


def oracle_public_job_base(inventory: str, site: str):
    p = urlparse(inventory)
    m = re.search(rf"^(.*?/sites/{re.escape(site)})(?:/.*)?$", p.path, re.I)
    if not m:
        raise NotCheckable("Oracle Candidate Experience site path could not be normalized")
    return f"{p.scheme or 'https'}://{p.netloc}{m.group(1)}"


def oracle_backend_hosts(inventory: str):
    p = urlparse(inventory)
    hosts = [p.netloc] if p.netloc else []
    try:
        r = get_response(inventory)
        text = html.unescape(r.text).replace("\\/", "/")
        for m in ORACLE_HOST_RE.finditer(text):
            host = m.group(1)
            if host.casefold() not in {x.casefold() for x in hosts}:
                hosts.append(host)
        final_host = urlparse(r.url).netloc
        if final_host and final_host.casefold() not in {x.casefold() for x in hosts}:
            hosts.append(final_host)
    except requests.RequestException:
        pass
    return hosts


def oracle_extract_root(data):
    if not isinstance(data, dict):
        raise NotCheckable("Oracle Candidate Experience returned non-object JSON")
    items = data.get("items")
    root = items[0] if isinstance(items, list) and items else data if "requisitionList" in data else None
    if not isinstance(root, dict):
        raise NotCheckable("Oracle Candidate Experience response has no requisition inventory")
    return root


def oracle_location(raw):
    values = []
    primary = clean_text(raw.get("PrimaryLocation"))
    if primary:
        values.append(primary)
    for field in ("secondaryLocations", "otherWorkLocations"):
        for item in raw.get(field) or []:
            if not isinstance(item, dict):
                continue
            value = clean_text(item.get("Name"))
            if not value:
                pieces = [clean_text(item.get("TownOrCity")), clean_text(item.get("Region1")), clean_text(item.get("Country"))]
                value = ", ".join(x for x in pieces if x) or None
            if value and value not in values:
                values.append(value)
    return " | ".join(values) if values else None


def oracle_source_id(raw):
    for field in ("Id", "RequisitionId", "RequisitionNumber", "ExternalRequisitionId"):
        value = clean_text(raw.get(field))
        if value:
            return value
    return None


def oracle_get_page(host: str, site: str, offset: int):
    endpoint = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    finder = f"findReqs;siteNumber={site},limit={ORACLE_PAGE_LIMIT},offset={offset}"
    headers = {"Accept": "application/vnd.oracle.adf.resourcecollection+json, application/json", "Ora-Irc-Language": "en", "REST-Framework-Version": "1"}
    try:
        r = get_session().get(endpoint, params={"onlyData": "true", "expand": "requisitionList.secondaryLocations", "finder": finder}, headers=headers, timeout=TIMEOUT)
    except requests.exceptions.SSLError as e:
        raise NotCheckable(f"Oracle Candidate Experience TLS validation failed on {host}; inventory cannot be safely verified") from e
    if r.status_code in {401, 403, 404, 406, 410}:
        raise NotCheckable(f"Oracle public Candidate Experience endpoint unavailable on {host}: HTTP {r.status_code}")
    r.raise_for_status()
    try:
        return r.json(), r.url
    except ValueError as e:
        raise NotCheckable(f"Oracle endpoint on {host} did not return JSON") from e


def _collect_oracle_once(company):
    name = company.get("company")
    ats = company.get("ats") or {}
    inventory = clean_text(ats.get("inventory_url"))
    if not inventory:
        raise CollectorError("Oracle inventory URL missing")
    site = oracle_site_from_inventory(inventory)
    if not site:
        raise NotCheckable("Oracle Candidate Experience site number is not present in mapped inventory URL")
    public_base = oracle_public_job_base(inventory, site)
    hosts = oracle_backend_hosts(inventory)
    if not hosts:
        raise NotCheckable("No Oracle Candidate Experience host could be evidenced")
    selected_host = None
    first_data = None
    source_url = None
    reasons = []
    for host in hosts:
        try:
            first_data, source_url = oracle_get_page(host, site, 0)
            oracle_extract_root(first_data)
            selected_host = host
            break
        except NotCheckable as e:
            reasons.append(str(e))
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            if status in {401, 403, 404, 406, 410}:
                reasons.append(f"{host}: HTTP {status}")
                continue
            raise CollectorError(f"Oracle Candidate Experience HTTP failure on {host}: {e}") from e
        except requests.RequestException as e:
            raise CollectorError(f"Oracle Candidate Experience request failure on {host}: {e}") from e
    if selected_host is None or first_data is None:
        raise NotCheckable(f"Oracle inventory could not be safely enumerated: {'; '.join(reasons[-3:]) or 'no usable public endpoint'}")
    rows = []
    seen = set()
    total = None
    offset = 0
    for page_index in range(MAX_PAGES):
        data = first_data if page_index == 0 else oracle_get_page(selected_host, site, offset)[0]
        root = oracle_extract_root(data)
        page = root.get("requisitionList")
        if not isinstance(page, list):
            raise NotCheckable("Oracle response does not expose requisitionList as an array")
        if total is None:
            try:
                total = int(root.get("TotalJobsCount"))
            except (TypeError, ValueError) as e:
                raise NotCheckable("Oracle inventory has no valid TotalJobsCount") from e
        for raw in page:
            if not isinstance(raw, dict):
                continue
            sid = oracle_source_id(raw)
            if not sid:
                raise NotCheckable("Oracle requisition lacks a stable public identifier")
            if sid not in seen:
                seen.add(sid)
                rows.append(raw)
        if len(rows) >= total:
            break
        if not page:
            raise NotCheckable(f"Oracle pagination stopped early: retrieved={len(rows)}, total={total}")
        offset += len(page)
    else:
        raise NotCheckable("Oracle inventory exceeds safe exhaustive-page limit")
    if total is None or len(rows) != total:
        raise NotCheckable(f"Oracle count mismatch: retrieved={len(rows)}, total={total}")
    jobs = []
    for raw in rows:
        sid = oracle_source_id(raw)
        loc = oracle_location(raw)
        if not sid or not location_matches(loc):
            continue
        canonical = f"{public_base}/job/{sid}"
        jobs.append(compact_job(name, sid, title=raw.get("Title"), location=loc, department=raw.get("Department") or raw.get("Organization"), employment_type=clean_text(raw.get("JobType")) or clean_text(raw.get("ContractType")), published_at=raw.get("PostedDate"), canonical=canonical, apply_url=canonical))
    return {"coverage": "VERIFIED", "collector": "oracle_recruiting_cloud_ce_metadata", "inventory_count": len(rows), "jobs": jobs, "source_url": source_url or inventory}


def collect_oracle(company):
    last_error = None
    for _attempt in range(2):
        try:
            return _collect_oracle_once(company)
        except NotCheckable as e:
            msg = str(e).casefold()
            if not any(x in msg for x in ("pagination stopped early", "count mismatch", "total changed")):
                raise
            last_error = e
    raise NotCheckable(f"Oracle inventory changed during enumeration after retry: {last_error}")


def verified_smartrecruiters_feed(company):
    ats = company.get("ats") or {}
    family = (clean_text(ats.get("family")) or "").casefold()
    verification = company.get("verification") or {}
    tenant = clean_text(ats.get("tenant"))
    feed = clean_text(ats.get("public_api_or_feed"))
    return bool("smartrecruiters" in family and "attrax" not in family and verification.get("full_inventory_possible") is True and tenant and SAFE_TENANT_RE.fullmatch(tenant) and feed and urlparse(feed).netloc.casefold() == "api.smartrecruiters.com")


_choose_v13 = choose

def choose(company):
    if oracle_family(company):
        inventory = clean_text((company.get("ats") or {}).get("inventory_url")) or ""
        if oracle_site_from_inventory(inventory):
            return collect_oracle
    fn = _choose_v13(company)
    if fn is not None:
        return fn
    ats = company.get("ats") or {}
    family = (clean_text(ats.get("family")) or "").casefold()
    verification = company.get("verification") or {}
    if verified_smartrecruiters_feed(company):
        return collect_smartrecruiters
    if "teamtailor" in family and verification.get("full_inventory_possible") is True:
        inventory = clean_text(ats.get("inventory_url")) or ""
        if "/jobs" in urlparse(inventory).path.casefold():
            return collect_teamtailor
    return None


_unsupported_result_v13 = unsupported_result

def unsupported_result(company, reason=None):
    result = _unsupported_result_v13(company, reason)
    if result.get("collector") == "unsupported_or_unverified_v1_3":
        result["collector"] = "unsupported_or_unverified_v1_4"
    if result.get("reason"):
        result["reason"] = result["reason"].replace("collector v1.3", "collector v1.4")
    return result


_collect_batch_v13 = collect_batch

def collect_batch(batch: str, workers: int = DEFAULT_WORKERS):
    payload = _collect_batch_v13(batch, workers=workers)
    payload["version"] = "1.4"
    scope = list(payload.get("collector_scope") or [])
    for value in (ORACLE_SCOPE_NAME, TEAMTAILOR_SCOPE_NAME):
        if value not in scope:
            scope.append(value)
    payload["collector_scope"] = scope
    write_json(ROOT / f"current_jobs_{batch}.json", payload)
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
