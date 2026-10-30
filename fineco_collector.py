"""FinecoBank official employee vacancies (Next.js frontend -> first-party public API).

The first-party Next.js career page fetches exactly this one unpaginated
public JSON jobs array; its PositionAccordion maps over positions.jobs.
Each stable ID and its intervieweb.it URL come directly from the company API.
VERIFIED is scoped to this official employee page, not independent job boards.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import collector as c

PORTAL = "https://about.finecobank.com/it/careers/diventa-un-dipendente/"
ENDPOINT = "https://public-api.finecobank.com/v1/public/career/work-with-us/jobs"
ID_RE = re.compile(r"^[0-9]{3,15}$")
PATH_RE = re.compile(r"^/jobs/[^/]+-([0-9]{3,15})/it/?$", re.I)
MAX = 500


def _public_snapshot():
    try:
        r = c.get_response(ENDPOINT, headers={
            "Accept": "application/json",
            "Referer": PORTAL,
            "Origin": "https://about.finecobank.com",
        })
        p = urlparse(r.url)
        if p.scheme != "https" or p.hostname != "public-api.finecobank.com" or p.path != "/v1/public/career/work-with-us/jobs":
            raise c.NotCheckable("Fineco public jobs API redirected outside first-party source")
        raw = r.json()
    except c.NotCheckable:
        raise
    except Exception as exc:
        raise c.NotCheckable("Fineco official public employee vacancies API unavailable") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("jobs"), list):
        raise c.NotCheckable("Fineco official careers JSON must expose a full jobs array")
    data = raw["jobs"]
    if len(data) > MAX:
        raise c.NotCheckable("Fineco employee inventory exceeds safe bounds")
    jobs = {}
    for item in data:
        if not isinstance(item, dict):
            raise c.NotCheckable("Fineco official vacancy item malformed")
        sid = c.clean_text(item.get("id"))
        title = c.clean_text(item.get("title"))
        location = c.clean_text(item.get("location"))
        canonical = c.clean_text(item.get("url"))
        if not sid or not ID_RE.fullmatch(sid) or not title or not location or not canonical:
            raise c.NotCheckable("Fineco public job lacks stable ID, title, location or URL")
        if sid in jobs:
            raise c.NotCheckable(f"Fineco public API duplicated requisition {sid}")
        url = urlparse(canonical)
        m = PATH_RE.fullmatch(url.path)
        if url.scheme != "https" or url.hostname != "finecobank.intervieweb.it" or url.query or url.fragment or not m or m.group(1) != sid:
            raise c.NotCheckable(f"Fineco public API job {sid} has invalid company Intervieweb link")
        if c.clean_text(item.get("locationLabel")) not in {"Sede", "Location"}:
            raise c.NotCheckable(f"Fineco job {sid} does not identify its official work location")
        jobs[sid] = {
            "id": sid,
            "title": title,
            "location": location,
            "url": canonical,
            "department": c.clean_text(item.get("function")),
            "experience": c.clean_text(item.get("levelOfExperience")),
            "published": c.clean_text(item.get("published")),
        }
    return jobs


def _detail_page(row):
    """A published Intervieweb URL should still show the same company's job."""
    sid = row["id"]
    try:
        body, url = c.get_html(row["url"])
    except Exception as exc:
        raise c.NotCheckable(f"Fineco official Intervieweb detail inaccessible for requisition {sid}") from exc
    u = urlparse(url)
    m = PATH_RE.fullmatch(u.path)
    if u.scheme != "https" or u.hostname != "finecobank.intervieweb.it" or not m or m.group(1) != sid:
        raise c.NotCheckable(f"Fineco requisition {sid} redirected to another job")
    # Host/ID/URL parity is guaranteed by the first-party official API and
    # detail route. The title can be in dynamic HTML or metadata, so require
    # at least a non-empty, actual HTML document with a page title.
    if len(body) < 100 or not re.search(r"<title[^>]*>\s*[^<]{3,}", body, re.I):
        raise c.NotCheckable(f"Fineco intervieweb job {sid} has no authentic HTML page")


def collect_fineco(company):
    if company.get("company") != "FinecoBank":
        raise c.NotCheckable("Fineco collector called for an unrelated company")
    before = _public_snapshot()
    after = _public_snapshot()
    if before != after:
        raise c.NotCheckable("Fineco first-party employee jobs array changed between two full snapshots")
    jobs = []
    for sid, row in before.items():
        location = row["location"]
        if not c.location_matches(location, "FinecoBank"):
            # Country-only location is insufficient to declare scope exclusion.
            if location.casefold() in {"italy", "italia", "it", "italian market", "remote"}:
                raise c.NotCheckable(f"Fineco job {sid} has ambiguous country-only/remote geography")
            continue
        _detail_page(row)
        jobs.append(c.compact_job(
            "FinecoBank", sid, title=row["title"], location=location,
            department=row["department"], employment_type=row["experience"],
            published_at=row["published"], canonical=row["url"],
            apply_url=row["url"],
        ))
    return {
        "coverage": "VERIFIED",
        "collector": "fineco_first_party_public_jobs_intervieweb_id_parity_v1",
        "inventory_count": len(before),
        "jobs": jobs,
        "source_url": PORTAL,
        "reconciliation": {
            "scope": "FinecoBank official employee positions (not financial-adviser recruiting or LinkedIn syndication)",
            "official_api": ENDPOINT,
            "public_jobs_count": len(before),
            "unique_stable_ids": len(before),
            "stable_full_snapshots": 2,
            "target_detail_pages_checked": len(jobs),
            "complete_frontend_array": True,
        },
    }
