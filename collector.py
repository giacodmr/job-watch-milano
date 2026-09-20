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
COLLECTOR_VERSION = "1.5"
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


def location_matches(location, company_name: str | None = None) -> bool:
    """Match standard target cities; Mastercard additionally includes Luxembourg."""
    if not location:
        return False
    s = str(location)
    mastercard_lux = (
        (company_name or "").casefold() == "mastercard"
        and re.search(r"(?<!\\w)(luxembourg|luxemburg)(?!\\w)", s, re.I)
    )
    if not TARGET_LOCATION_RE.search(s) and not mastercard_lux:
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
    """Stable metadata fingerprint, independent of descriptions and volatile relative dates."""
    effective_date = clean_text(job.get("updated_at")) or clean_text(job.get("published_at"))
    if effective_date:
        d = effective_date.casefold()
        # Workday and similar ATS expose rolling labels such as "Posted 2 Days Ago".
        # Those labels change every day even when the vacancy itself has not changed.
        # Excluding them prevents false UPDATED statuses and needless analysis resets.
        volatile_date = (
            d in {"today", "yesterday", "posted today", "posted yesterday"}
            or (d.startswith("posted ") and d.endswith(" ago"))
        )
        if volatile_date:
            effective_date = None
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
        if not location_matches(loc, name):
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
    """Return the SuccessFactors result offset from query or path pagination.

    Career Site Builder uses both ?startrow=50 and /viewalljobs/50/ depending
    on site/template. Treat both as the same official pagination contract.
    """
    try:
        parsed = urlparse(url)
        vals = parse_qs(parsed.query).get("startrow") or []
        if vals:
            return int(vals[0])
        m = re.search(r"/(?:viewalljobs|search)/(\\d+)/?$", parsed.path, re.I)
        if m:
            return int(m.group(1))
        return 0
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
            "coverage": "PARTIAL",
            "collector": getattr(fn, "__name__", "collector"),
            "inventory_count": None,
            "jobs": [],
            "reason": f"NotCheckable after attempted official check: {e}",
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
        "PARTIAL": 0,
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
            "PARTIAL means an official method was actually attempted but exhaustiveness could not be proven. "
            "NOT_CHECKED means no safe current-run collector attempt was made. Request/runtime failures on a "
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
            paged_retryable = any(
                token in message
                for token in (
                    "total changed",
                    "reconciliation",
                    "repeated a page",
                    "inventory not exhaustible",
                )
            )
            if any(token in message for token in ("inventory not exhaustible", "pagination repeated a page")):
                try:
                    return _collect_successfactors_tile_strict(company)
                except NotCheckable as tile_error:
                    last_error = tile_error
                    tmsg = str(tile_error).casefold()
                    tile_retryable = any(
                        token in tmsg
                        for token in ("total changed", "reconciliation", "stopped early", "repeated a page")
                    )
                    # If the normal paginated inventory was provably structured but
                    # one enumeration attempt stalled, retry that primary method once
                    # even when this portal has no tile fallback. This keeps transient
                    # page/range instability as NOT_CHECKED rather than a false failure.
                    if attempt == 0 and (paged_retryable or tile_retryable):
                        continue
                    raise
            if paged_retryable and attempt == 0:
                continue
            raise
    raise NotCheckable(f"SuccessFactors inventory remained unstable after retry: {last_error}")

# === JOB WATCH V1.5 SUCCESSFACTORS CONSERVATIVE METADATA ===
# Do not use proximity/token heuristics for location. Start from the v1.4
# table parser and add only the explicit Career Site Builder field-id metadata.
# This deliberately prefers NOT_CHECKED over a false location match.
def merge_sf_page_jobs(base: str, parser: SFPageParser) -> list[dict]:
    jobs = _merge_sf_page_jobs_v14(base, parser)
    for job in jobs:
        if not clean_text(job.get("location")):
            job["location"] = _sf_card_location(parser, job["url"])
        if not clean_text(job.get("published_at")):
            job["published_at"] = _sf_card_date(parser, job["url"])
    return jobs

# === JOB WATCH V1.5 SUCCESSFACTORS UNFILTERED SEARCH HELPER ===
def is_unfiltered_search_url(url: str) -> bool:
    """Accept only a demonstrably unfiltered inventory/search URL.

    Empty keyword plus sort controls are benign. A non-zero startrow, a
    non-empty keyword, or any other facet/filter parameter is not suitable as
    the starting point for an exhaustive inventory proof.
    """
    p = urlparse(url)
    params = parse_qs(p.query, keep_blank_values=True)
    allowed = {"q", "startrow", "sortcolumn", "sortdirection"}
    for key, values in params.items():
        k = key.casefold()
        if k not in allowed:
            return False
        cleaned = [clean_text(v) or "" for v in values]
        if k == "q" and any(cleaned):
            return False
        if k == "startrow" and any(v not in ("", "0") for v in cleaned):
            return False
    return True


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

# === JOB WATCH V1.7 TARGET-COVERAGE + OFFICIAL PROBES ===
# Adds first-class Amazon target-city enumeration, Banca Ifis deterministic
# pagination, and a real official-page attempt for every remaining mapped
# company. Unsupported dynamic portals become PARTIAL after an actual official
# check rather than remaining opaque NOT_CHECKED rows.

AMAZON_SCOPE_NAME = "Amazon Jobs public search.json target-city inventory"
BANCA_IFIS_SCOPE_NAME = "Banca Ifis official paginated inventory"
OFFICIAL_PROBE_SCOPE_NAME = "Official inventory reachability probe"

AMAZON_API = "https://www.amazon.jobs/en/search.json"
AMAZON_TARGETS = {
    "Milan": {"probe": "Milan", "country_codes": {"ITA", "IT"}},
    "Rome": {"probe": "Rome", "country_codes": {"ITA", "IT"}},
    "London": {"probe": "London", "country_codes": {"GBR", "GB", "UK"}},
}


class BasicTextLinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_parts = []
        self.links = []
        self._link = None

    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "a":
            return
        a = {str(k).casefold(): v for k, v in attrs if k}
        self._link = {"href": clean_text(a.get("href")), "text": []}

    def handle_data(self, data):
        value = clean_text(data)
        if not value:
            return
        self.text_parts.append(value)
        if self._link is not None:
            self._link["text"].append(value)

    def handle_endtag(self, tag):
        if tag.casefold() == "a" and self._link is not None:
            row = dict(self._link)
            row["text"] = clean_text(" ".join(row.get("text") or []))
            self.links.append(row)
            self._link = None


def amazon_family(company) -> bool:
    name = (clean_text(company.get("company")) or "").casefold()
    family = (clean_text((company.get("ats") or {}).get("family")) or "").casefold()
    return name == "amazon" or "amazon jobs" in family


def _amazon_job_id(job):
    for k in ("id", "id_icims", "job_id", "requisition_id"):
        v = job.get(k)
        if v not in (None, "", []):
            return str(v)
    path = clean_text(job.get("job_path") or job.get("url"))
    return path or None


def _amazon_job_url(job):
    path = clean_text(job.get("job_path") or job.get("url"))
    if not path:
        return None
    return path if path.startswith(("http://", "https://")) else "https://www.amazon.jobs" + path


def _amazon_norms(job):
    v = job.get("normalized_location")
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [str(x) for x in v if x]
    return []


def _amazon_country_ok(job, norm, codes):
    hay = " | ".join(
        [
            str(job.get("country_code") or ""),
            str(job.get("country") or ""),
            str(norm or ""),
            str(job.get("location") or ""),
        ]
    ).upper()
    return any(re.search(rf"(^|[^A-Z]){re.escape(c)}([^A-Z]|$)", hay) for c in codes)


def _amazon_json(params):
    try:
        r = get_session().get(
            AMAZON_API,
            params=params,
            headers={"Accept": "application/json,text/plain,*/*"},
            timeout=TIMEOUT,
        )
        if r.status_code in {401, 403, 404, 406, 410, 429, 500, 502, 503, 504}:
            raise NotCheckable(f"Amazon Jobs API unavailable from runner (HTTP {r.status_code})")
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.SSLError as e:
        raise NotCheckable("Amazon Jobs API TLS validation failed") from e
    except (requests.RequestException, ValueError) as e:
        raise NotCheckable(f"Amazon Jobs API request/JSON failed: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise NotCheckable("Amazon Jobs API returned an unexpected payload")
    return data, r.url


def _amazon_discover_norms(city, spec):
    data, _ = _amazon_json(
        {"base_query": spec["probe"], "offset": 0, "result_limit": 100, "sort": "relevant"}
    )
    norms = set()
    for job in data.get("jobs") or []:
        for norm in _amazon_norms(job):
            if city.casefold() in norm.casefold() and _amazon_country_ok(
                job, norm, spec["country_codes"]
            ):
                norms.add(norm)
    if not norms:
        raise NotCheckable(f"Amazon Jobs did not expose a normalized_location for {city}")
    return sorted(norms)


def _amazon_enumerate_norm(norm):
    offset = 0
    limit = 100
    expected = None
    rows = []
    for _ in range(MAX_PAGES):
        data, _ = _amazon_json(
            {
                "base_query": "",
                "normalized_location[]": norm,
                "offset": offset,
                "result_limit": limit,
                "sort": "relevant",
            }
        )
        page = data.get("jobs") or []
        total = int(data.get("hits") or len(page))
        if expected is None:
            expected = total
        elif total != expected:
            raise NotCheckable(
                f"Amazon Jobs count changed during pagination for {norm}: {expected}->{total}"
            )
        rows.extend(page)
        if len(rows) >= expected:
            break
        if not page:
            raise NotCheckable(
                f"Amazon Jobs pagination stopped early for {norm}: {len(rows)}/{expected}"
            )
        offset += len(page)
    else:
        raise NotCheckable(f"Amazon Jobs inventory exceeds safe page limit for {norm}")
    if len(rows) != expected:
        raise NotCheckable(
            f"Amazon Jobs reconciliation mismatch for {norm}: {len(rows)}!={expected}"
        )
    return rows


def collect_amazon(company):
    name = company.get("company") or "Amazon"
    by_id = {}
    norm_counts = {}
    for city, spec in AMAZON_TARGETS.items():
        norms = _amazon_discover_norms(city, spec)
        for norm in norms:
            rows = _amazon_enumerate_norm(norm)
            norm_counts[norm] = len(rows)
            for raw in rows:
                sid = _amazon_job_id(raw)
                if not sid:
                    raise NotCheckable("Amazon Jobs row lacks stable requisition/job ID")
                by_id[sid] = raw

    jobs = []
    for sid, raw in by_id.items():
        loc = clean_text(raw.get("location")) or ", ".join(_amazon_norms(raw))
        jobs.append(
            compact_job(
                name,
                sid,
                title=raw.get("title"),
                location=loc,
                department=raw.get("job_category") or raw.get("business_category"),
                published_at=raw.get("posted_date") or raw.get("posted_at"),
                updated_at=raw.get("updated_time"),
                canonical=_amazon_job_url(raw),
                apply_url=_amazon_job_url(raw),
            )
        )
    return {
        "coverage": "VERIFIED",
        "collector": "amazon_jobs_search_json_target_inventory_v17",
        "inventory_count": len(by_id),
        "jobs": jobs,
        "source_url": AMAZON_API,
        "reason": None,
        "target_inventory_detail": norm_counts,
    }


def banca_ifis_family(company) -> bool:
    name = (clean_text(company.get("company")) or "").casefold()
    inventory = clean_text((company.get("ats") or {}).get("inventory_url")) or ""
    return name == "banca ifis" and urlparse(inventory).netloc.casefold() == "posizioniaperte.bancaifis.it"


def _banca_ifis_detail(url):
    text, final_url = get_html(url)
    parser = BasicTextLinkParser()
    parser.feed(text)
    parts = parser.text_parts
    location = None
    for i, part in enumerate(parts):
        p = part.strip()
        if p.casefold() == "sedi" and i + 1 < len(parts):
            location = clean_text(parts[i + 1])
            break
        if p.casefold().startswith("sedi "):
            location = clean_text(p[5:])
            break
    if not location:
        for part in parts:
            if len(part) <= 100 and TARGET_LOCATION_RE.search(part):
                location = clean_text(part)
                break
    return location, final_url


def collect_banca_ifis(company):
    name = company.get("company")
    inventory = clean_text((company.get("ats") or {}).get("inventory_url"))
    if not inventory:
        raise NotCheckable("Banca Ifis inventory URL missing")

    found = {}
    saw_page = False
    for page in range(1, MAX_PAGES + 1):
        params = {"cngLanguage": "ITA"}
        if page > 1:
            params.update(
                {
                    "PagerAnnunci": page,
                    "RunDefaultAction": "true",
                    "StartupViewID": "TableView",
                }
            )
        html_text, final_url = get_html(inventory, params=params)
        parser = BasicTextLinkParser()
        parser.feed(html_text)
        page_rows = {}
        for link in parser.links:
            href = clean_text(link.get("href"))
            if not href:
                continue
            u = urljoin(final_url, href)
            p = urlparse(u)
            q = parse_qs(p.query)
            jid = (q.get("JobID") or q.get("jobid") or [None])[0]
            if (
                p.netloc.casefold() == "posizioniaperte.bancaifis.it"
                and "job-details" in p.path.casefold()
                and jid
            ):
                page_rows[str(jid)] = {
                    "url": u,
                    "title": clean_text(link.get("text")),
                }
        if not page_rows:
            if page == 1:
                raise NotCheckable("Banca Ifis first inventory page exposed no stable JobID links")
            break
        saw_page = True
        new_ids = [jid for jid in page_rows if jid not in found]
        if not new_ids:
            break
        found.update(page_rows)
    else:
        raise NotCheckable("Banca Ifis pagination exceeded safe page limit")

    if not saw_page or not found:
        raise NotCheckable("Banca Ifis inventory could not be enumerated")

    jobs = []
    for jid, row in found.items():
        loc, canonical = _banca_ifis_detail(row["url"])
        if location_matches(loc):
            jobs.append(
                compact_job(
                    name,
                    jid,
                    title=row.get("title"),
                    location=loc,
                    canonical=canonical,
                    apply_url=canonical,
                )
            )
    return {
        "coverage": "VERIFIED",
        "collector": "banca_ifis_paginated_inventory_v17",
        "inventory_count": len(found),
        "jobs": jobs,
        "source_url": inventory,
        "reason": None,
    }


def prima_family(company) -> bool:
    name = (clean_text(company.get("company")) or "").casefold()
    inventory = clean_text((company.get("ats") or {}).get("inventory_url")) or ""
    return name == "prima assicurazioni" and "helloprima.com" in urlparse(inventory).netloc.casefold()


def collect_prima_official(company):
    name = company.get("company")
    inventory = clean_text((company.get("ats") or {}).get("inventory_url"))
    if not inventory:
        raise NotCheckable("Prima official jobs URL missing")
    html_text, final_url = get_html(inventory)
    parser = BasicTextLinkParser()
    parser.feed(html_text)
    rows = {}
    for link in parser.links:
        href = clean_text(link.get("href"))
        if not href:
            continue
        u = urljoin(final_url, href)
        p = urlparse(u)
        path = p.path.rstrip("/")
        prefix = "/it/carriere/offerte-lavoro/"
        if "helloprima.com" not in p.netloc.casefold() or prefix not in path.casefold():
            continue
        slug = path.split("/")[-1]
        if not slug or slug.casefold() == "offerte-lavoro":
            continue
        rows[slug] = {"url": u, "title": clean_text(link.get("text"))}
    if not rows:
        raise NotCheckable("Prima official list is reachable but job-detail links are not server-rendered")

    jobs = []
    for sid, row in rows.items():
        detail, canonical = get_html(row["url"])
        dp = BasicTextLinkParser()
        dp.feed(detail)
        loc = None
        for part in dp.text_parts:
            if len(part) <= 100 and TARGET_LOCATION_RE.search(part):
                loc = clean_text(part)
                break
        if location_matches(loc):
            jobs.append(
                compact_job(
                    name,
                    sid,
                    title=row.get("title") or (dp.text_parts[0] if dp.text_parts else None),
                    location=loc,
                    canonical=canonical,
                    apply_url=canonical,
                )
            )
    return {
        "coverage": "PARTIAL",
        "collector": "prima_first_party_rendered_list_v17",
        "inventory_count": len(rows),
        "jobs": jobs,
        "source_url": inventory,
        "reason": (
            "Official Prima job-detail list was enumerated as rendered, but the board exposes no "
            "independent total/pagination contract; completeness cannot be certified."
        ),
    }


def probe_official_inventory(company):
    ats = company.get("ats") or {}
    inventory = clean_text(ats.get("inventory_url")) or clean_text(ats.get("career_site"))
    family = clean_text(ats.get("family")) or "unresolved ATS"
    if not inventory:
        raise NotCheckable(f"No official inventory/career URL mapped for {family}")
    try:
        r = get_session().get(
            inventory,
            headers={"Accept": "text/html,application/xhtml+xml,application/json,*/*"},
            timeout=min(TIMEOUT, 18),
            allow_redirects=True,
        )
    except requests.exceptions.SSLError as e:
        raise NotCheckable(
            f"Official inventory was attempted but TLS validation failed; no exhaustive parser for {family}"
        ) from e
    except requests.RequestException as e:
        raise NotCheckable(
            f"Official inventory was attempted but the runner request failed ({type(e).__name__}); "
            f"no exhaustive parser for {family}"
        ) from e
    if r.status_code >= 400:
        raise NotCheckable(
            f"Official inventory was attempted but returned HTTP {r.status_code}; "
            f"no exhaustive parser for {family}"
        )
    body = r.text or ""
    if not body.strip():
        raise NotCheckable(
            f"Official inventory returned an empty response; no exhaustive parser for {family}"
        )
    raise NotCheckable(
        f"Official inventory is reachable ({r.status_code}, {len(body)} bytes) but no safe exhaustive "
        f"collector is implemented yet for {family}"
    )



BOLT_SCOPE_NAME = "Bolt official paginated positions inventory"
BOLT_ROLE_RE = re.compile(
    r"^/en/careers/positions/([0-9a-f]{8}-[0-9a-f-]{27,36})/?$",
    re.I,
)


def bolt_family(company) -> bool:
    name = (clean_text(company.get("company")) or "").casefold()
    inventory = clean_text((company.get("ats") or {}).get("inventory_url")) or ""
    return name == "bolt" and urlparse(inventory).netloc.casefold().endswith("bolt.eu")


def _bolt_detail(url):
    html_text, final_url = get_html(url)
    parser = BasicTextLinkParser()
    parser.feed(html_text)
    parts = parser.text_parts
    title = None
    department = None
    location = None
    employment_type = None

    # Bolt's public detail page exposes stable uppercase field labels.
    for i, part in enumerate(parts):
        low = part.casefold()
        if i == 0 and part:
            title = part
        if low == "department" and i + 1 < len(parts):
            department = clean_text(parts[i + 1])
        elif low == "locations" and i + 1 < len(parts):
            location = clean_text(parts[i + 1])
        elif low == "type" and i + 1 < len(parts):
            employment_type = clean_text(parts[i + 1])
    if not title:
        # Fall back to the first concise non-navigation item.
        for part in parts:
            if 2 <= len(part) <= 160 and part.casefold() not in {"bolt careers", "view all roles"}:
                title = part
                break
    return {
        "title": title,
        "department": department,
        "location": location,
        "employment_type": employment_type,
        "url": final_url,
    }


def collect_bolt(company):
    name = company.get("company")
    inventory = clean_text((company.get("ats") or {}).get("inventory_url"))
    if not inventory:
        raise NotCheckable("Bolt positions URL missing")

    found = {}
    for page in range(1, MAX_PAGES + 1):
        params = {} if page == 1 else {"page": page}
        html_text, final_url = get_html(inventory, params=params)
        parser = BasicTextLinkParser()
        parser.feed(html_text)
        page_rows = {}
        for link in parser.links:
            href = clean_text(link.get("href"))
            if not href:
                continue
            u = urljoin(final_url, href)
            p = urlparse(u)
            if not p.netloc.casefold().endswith("bolt.eu"):
                continue
            m = BOLT_ROLE_RE.fullmatch(p.path)
            if not m:
                continue
            sid = m.group(1).lower()
            page_rows[sid] = u
        if not page_rows:
            if page == 1:
                raise NotCheckable("Bolt first positions page exposed no stable role links")
            break
        new_ids = [sid for sid in page_rows if sid not in found]
        if not new_ids:
            break
        found.update(page_rows)
    else:
        raise NotCheckable("Bolt positions pagination exceeded safe page limit")

    if not found:
        raise NotCheckable("Bolt positions inventory could not be enumerated")

    jobs = []
    stale_details = 0
    for sid, url in found.items():
        try:
            detail = _bolt_detail(url)
        except requests.HTTPError as e:
            if getattr(e.response, "status_code", None) == 404:
                stale_details += 1
                continue
            raise
        if location_matches(detail.get("location")):
            jobs.append(
                compact_job(
                    name,
                    sid,
                    title=detail.get("title"),
                    location=detail.get("location"),
                    department=detail.get("department"),
                    employment_type=detail.get("employment_type"),
                    canonical=detail.get("url"),
                    apply_url=detail.get("url"),
                )
            )
    return {
        "coverage": "PARTIAL" if stale_details else "VERIFIED",
        "collector": "bolt_paginated_positions_inventory_v18",
        "inventory_count": len(found),
        "jobs": jobs,
        "source_url": inventory,
        "reason": (
            f"{stale_details} Bolt role link(s) disappeared between inventory enumeration and detail verification; "
            "remaining official inventory was processed."
            if stale_details else None
        ),
    }


_choose_v16 = choose
def choose(company):
    if amazon_family(company):
        return collect_amazon
    if banca_ifis_family(company):
        return collect_banca_ifis
    if bolt_family(company):
        return collect_bolt
    if prima_family(company):
        return collect_prima_official
    fn = _choose_v16(company)
    if fn is not None:
        return fn
    return probe_official_inventory


def collect_company(company: dict) -> tuple[dict, bool]:
    fn = choose(company)
    try:
        result = fn(company)
        if "reason" not in result:
            result["reason"] = None
        return result, True
    except NotCheckable as e:
        return {
            "coverage": "PARTIAL",
            "collector": getattr(fn, "__name__", "collector"),
            "inventory_count": None,
            "jobs": [],
            "reason": f"Official check incomplete: {e}",
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


_collect_batch_v16 = collect_batch
def collect_batch(batch: str, workers: int = DEFAULT_WORKERS):
    payload = _collect_batch_v16(batch, workers=workers)
    payload["version"] = "1.8"
    scope = list(payload.get("collector_scope") or [])
    for value in (AMAZON_SCOPE_NAME, BANCA_IFIS_SCOPE_NAME, BOLT_SCOPE_NAME, OFFICIAL_PROBE_SCOPE_NAME):
        if value not in scope:
            scope.append(value)
    payload["collector_scope"] = scope
    payload["coverage_note"] = (
        "VERIFIED means the target-scope official inventory was exhausted and reconciled. "
        "The standard scope is Milan/Rome/London; Mastercard additionally includes Luxembourg. "
        "PARTIAL means the official source was actually attempted but full enumeration could not be "
        "certified or only a rendered subset could be collected. FAILED is reserved for a supported "
        "structured collector that unexpectedly failed. NOT_CHECKED should normally be zero because "
        "every mapped company receives at least an official-source probe."
    )
    write_json(ROOT / f"current_jobs_{batch}.json", payload)
    return payload

if __name__ == "__main__":
    raise SystemExit(main())
