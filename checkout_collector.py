"""Checkout.com official public Ashby posting feed with first-party publisher proof.

Never infer full inventory from Webflow's client-side zero-results UI. Use
the official careers-page link to the checkout.com Ashby board, require the
public posting API's listed job IDs and canonical URLs, and retry parity.
"""
from __future__ import annotations
import re
import uuid
from html.parser import HTMLParser
from urllib.parse import urlparse

import collector as c

CORPORATE = "https://www.checkout.com/jobs"
ASHBY = "https://api.ashbyhq.com/posting-api/job-board/checkout.com"
_BOARD = "https://jobs.ashbyhq.com/checkout.com"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z", re.I)


class _HrefParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag.lower()=="a":
            href=dict(attrs).get("href")
            if href:
                self.links.append(href)


def _corporate_board_confirmation():
    try:
        body, url = c.get_html(CORPORATE)
    except Exception as exc:
        raise c.NotCheckable("Checkout.com first-party corporate jobs page not reachable") from exc
    if urlparse(url).hostname not in {"checkout.com","www.checkout.com"}:
        raise c.NotCheckable("Checkout.com corporate site redirected to unknown publisher")
    p=_HrefParser()
    p.feed(body)
    direct=any(
        urlparse(x).hostname=="jobs.ashbyhq.com"
        and urlparse(x).path.startswith("/checkout.com/")
        and (urlparse(x).path=="/checkout.com/form/talent-communities"
             or urlparse(x).path.startswith("/checkout.com/"))
        for x in p.links
    )
    if not direct:
        raise c.NotCheckable("Checkout.com no longer links the expected official Ashby publishing board")
    return url


def _normalize_uuid(value):
    if not isinstance(value,str) or not _UUID.fullmatch(value):
        raise c.NotCheckable("Checkout.com public posting has invalid requisition UUID")
    try:
        return str(uuid.UUID(value))
    except ValueError as e:
        raise c.NotCheckable("Checkout.com public posting has invalid UUID") from e


def _safe_job_url(url, sid, apply=False):
    p=urlparse(str(url or ""))
    expected=f"/checkout.com/{sid}"+("/application" if apply else "")
    return p.scheme=="https" and p.hostname=="jobs.ashbyhq.com" and p.path.rstrip("/")==expected and not p.query and not p.fragment


def _locations(row):
    primary=c.clean_text(row.get("location"))
    if not primary:
        raise c.NotCheckable("Checkout.com public posting has no location")
    parts=[primary]
    extra=row.get("secondaryLocations") or []
    if not isinstance(extra,list):
        raise c.NotCheckable("Checkout.com posting has malformed secondary locations")
    for raw in extra:
        if isinstance(raw,dict):
            loc=c.clean_text(raw.get("location"))
        elif isinstance(raw,str):
            loc=c.clean_text(raw)
        else:
            loc=None
        if not loc:
            raise c.NotCheckable("Checkout.com posting has unsupported secondary location record")
        if loc not in parts:
            parts.append(loc)
    return " | ".join(parts)


def _snapshot():
    try:
        data=c.get_json(ASHBY)
    except Exception as exc:
        raise c.NotCheckable("Checkout.com official Ashby public posting API unreachable") from exc
    if not isinstance(data,dict) or not isinstance(data.get("jobs"),list) or not data.get("apiVersion"):
        raise c.NotCheckable("Checkout.com Ashby returned unrecognized job inventory metadata")
    listed={}
    for raw in data["jobs"]:
        if not isinstance(raw,dict):
            raise c.NotCheckable("Checkout.com job feed contains non-object posting")
        sid=_normalize_uuid(raw.get("id"))
        title=c.clean_text(raw.get("title"))
        loc=_locations(raw)
        if not title or not _safe_job_url(raw.get("jobUrl"),sid) or not _safe_job_url(raw.get("applyUrl"),sid,apply=True):
            raise c.NotCheckable(f"Checkout.com published posting invalid title/canonical/application URL: {sid}")
        if not isinstance(raw.get("isListed"),bool):
            raise c.NotCheckable("Checkout.com Ashby does not distinguish listed and unlisted jobs")
        if sid in listed:
            raise c.NotCheckable("Checkout.com Ashby duplicate public posting UUID")
        listed[sid]={"title":title,"location":loc,"department":c.clean_text(raw.get("department")),
                     "published_at":c.clean_text(raw.get("publishedAt")),
                     "job_url":raw["jobUrl"],"apply_url":raw["applyUrl"],"listed":raw["isListed"]}
    # Unlisted jobs are available via direct API but not publicly advertised.
    # Reconcile their IDs as part of the provider snapshot, but do not surface.
    return listed


def collect_checkout(company):
    if company.get("company")!="Checkout.com":
        raise c.NotCheckable("Checkout.com Ashby adapter called with incorrect company")
    source=_corporate_board_confirmation()
    first=_snapshot()
    if not first:
        raise c.NotCheckable("Checkout.com Ashby board has no currently public postings")
    second=_snapshot()
    if first!=second:
        raise c.NotCheckable(f"Checkout.com Ashby postings changed during enumeration: first={len(first)}, second={len(second)}")
    jobs=[]
    for sid,meta in first.items():
        if not meta["listed"]:
            continue
        if not c.location_matches(meta["location"],"Checkout.com"):
            continue
        jobs.append(c.compact_job("Checkout.com",sid,title=meta["title"],location=meta["location"],
                     department=meta["department"],published_at=meta["published_at"],
                     canonical=meta["job_url"],apply_url=meta["apply_url"]))
    return {
        "coverage":"VERIFIED",
        "collector":"checkout_first_party_ashby_public_feed_parity_v1",
        "inventory_count":sum(x["listed"] for x in first.values()),
        "source_url":source,
        "jobs":jobs,
        "reconciliation":{"publisher":"Ashby Checkout.com official public job board",
                          "feed_public_postings":len(first),"listed_postings":sum(x["listed"] for x in first.values()),
                          "geographic_jobs":len(jobs),"stable_two_snapshots":True}
    }
