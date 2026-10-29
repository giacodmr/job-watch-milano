"""Safe PARTIAL Worldline collector: first-party public SuccessFactors job results.

Worldline /viewalljobs/ officially says 65 jobs, whereas its own legacy
search endpoint returns totalJobs=221 with repeated IDs and nonstable order.
Never call this exhaustive. Retain only validated job details at explicit
Italy-Milan / Italy-Rome locations, with exact original publisher IDs.
"""
from __future__ import annotations

import html
import re
from urllib.parse import quote, urlparse

import collector as c

HOME = "https://jobs.worldline.com"
SOURCE = HOME + "/viewalljobs/"
SEARCH = HOME + "/search/?unified=legacy"
ENDPOINT = HOME + "/services/recruiting/v1/jobs"
MAX_PAGES = 36
CANON_RE = re.compile(r"^/job/[^/]+/([0-9]{4,})-en_US/?$",re.I)
COUNTER_RE = re.compile(r"Results\s*1\s*[–-]\s*50\s*of\s*(\d+)",re.I)
TARGET_LOCATION_RE = re.compile(r"^Italy[\s]*-[\s]*(Milan|Milano|Rome|Roma)\s*$",re.I)


def _homepage_total():
    try:
        body, landed = c.get_html(SOURCE)
    except Exception as exc:
        raise c.NotCheckable("Worldline official corporate viewalljobs inventory unreachable") from exc
    p=urlparse(landed)
    if p.scheme!="https" or p.hostname!="jobs.worldline.com" or p.path.rstrip("/")!="/viewalljobs":
        raise c.NotCheckable("Worldline viewalljobs redirected outside official source")
    m=COUNTER_RE.search(c.html_to_text(body) or "")
    if not m:
        raise c.NotCheckable("Worldline official corporate listing total cannot be parsed")
    return int(m.group(1))


def _api_page(page):
    payload={"keywords":"","locale":"en_US","location":"","pageNumber":page,"sortBy":"recent"}
    try:
        d=c.post_json(ENDPOINT,payload,headers={"Origin":HOME,"Referer":SEARCH})
    except Exception as exc:
        raise c.NotCheckable(f"Worldline first-party recruiting API failed on page {page}") from exc
    if not isinstance(d,dict) or not isinstance(d.get("totalJobs"),int) or not isinstance(d.get("jobSearchResult"),list):
        raise c.NotCheckable(f"Worldline first-party recruiting response schema invalid on page {page}")
    if d["totalJobs"]<1 or d["totalJobs"]>3500:
        raise c.NotCheckable("Worldline publisher count outside bounded range")
    return d["totalJobs"],d["jobSearchResult"]


def _target_cities(raw):
    if not isinstance(raw,list):
        raise c.NotCheckable("Worldline posting location array malformed")
    cities=set()
    for v in raw:
        s=c.clean_text(v)
        if not s:
            raise c.NotCheckable("Worldline posting location entry blank")
        m=TARGET_LOCATION_RE.fullmatch(s)
        if m:
            cities.add("Milan" if m.group(1).casefold().startswith("mil") else "Rome")
    return " | ".join(sorted(cities))


def _official_url(raw):
    sid=str(raw.get("id") or "")
    if not re.fullmatch(r"[0-9]{4,}",sid):
        raise c.NotCheckable("Worldline requisition ID not numeric")
    slug=html.unescape(c.clean_text(raw.get("unifiedUrlTitle")) or "")
    if not slug or len(slug)>220 or "/" in slug or "?" in slug:
        raise c.NotCheckable(f"Worldline requisition {sid} has invalid official slug")
    slug=quote(slug,safe="-%")
    url=f"{HOME}/job/{slug}/{sid}-en_US"
    match=CANON_RE.fullmatch(urlparse(url).path)
    if not match or match.group(1)!=sid:
        raise c.NotCheckable("Worldline official job detail path invalid")
    return url


def _validate_detail(raw,url):
    sid=str(raw["id"])
    title=c.clean_text(raw.get("unifiedStandardTitle"))
    if not title:
        raise c.NotCheckable(f"Worldline requisition {sid} has no official title")
    try:
        body,landed=c.get_html(url)
    except Exception as exc:
        raise c.NotCheckable(f"Worldline official job detail inaccessible for {sid}") from exc
    p=urlparse(landed)
    match=CANON_RE.fullmatch(p.path)
    if p.scheme!="https" or p.hostname!="jobs.worldline.com" or not match or match.group(1)!=sid:
        raise c.NotCheckable(f"Worldline detail redirected outside official requisition {sid}")
    page_title=re.search(r"<title[^>]*>(.*?)</title>",body,re.I|re.S)
    if not page_title:
        raise c.NotCheckable(f"Worldline detail has no title for {sid}")
    label=c.html_to_text(page_title.group(1)) or ""
    if title.casefold() not in label.casefold() or sid not in body:
        raise c.NotCheckable(f"Worldline official job detail title/ID mismatch for {sid}")


def collect_worldline(company):
    if company.get("company")!="Worldline":
        raise c.NotCheckable("Worldline adapter called with incorrect company")
    corporate_total=_homepage_total()
    seen={}
    first_total=None
    fetched=0
    pages=0
    for page in range(MAX_PAGES):
        count,rows=_api_page(page)
        if first_total is None:first_total=count
        elif count!=first_total:
            raise c.NotCheckable(f"Worldline recruiting count drift: {first_total}->{count}")
        pages+=1
        if not rows:break
        for item in rows:
            raw=item.get("response") if isinstance(item,dict) else None
            if not isinstance(raw,dict):
                raise c.NotCheckable("Worldline recruiting item missing response object")
            fetched+=1
            sid=str(raw.get("id") or "")
            if not re.fullmatch(r"[0-9]{4,}",sid):
                raise c.NotCheckable("Worldline response has no stable numeric ID")
            if sid in seen:
                previous=seen[sid]
                if previous.get("unifiedStandardTitle")!=raw.get("unifiedStandardTitle"):
                    raise c.NotCheckable(f"Worldline ID {sid} has conflicting title")
                continue
            seen[sid]=raw
        if fetched>=first_total:break
    else:
        raise c.NotCheckable("Worldline recruiting page limit exceeded")
    if fetched<first_total:
        raise c.NotCheckable("Worldline API returned fewer records than declared count")

    jobs=[]
    for sid,raw in seen.items():
        if "Worldline" not in (raw.get("sfstd_marketingBrand_obj") or []):
            continue
        loc=_target_cities(raw.get("jobLocationShort"))
        if not loc or not c.location_matches(loc,"Worldline"):
            continue
        url=_official_url(raw)
        _validate_detail(raw,url)
        jobs.append(c.compact_job("Worldline",sid,title=raw.get("unifiedStandardTitle"),
            location=loc,department=" / ".join(raw.get("custJobFamily") or []),
            employment_type=" / ".join(raw.get("jobContract") or []),
            canonical=url,apply_url=url))
    return {
        "coverage":"PARTIAL",   # mismatched global/card count, repeat IDs & unstable order
        "collector":"worldline_sf_official_recruiting_partial_validated_details_v1",
        "inventory_count":corporate_total,
        "jobs":jobs,
        "source_url":SOURCE,
        "reason":f"Worldline corporate list shows {corporate_total} postings, but public recruiting API declares {first_total} records and returned {len(seen)} distinct IDs in {fetched} rows; publisher scope/order cannot be reconciled. Retained {len(jobs)} Milan/Rome official detail-verified requisitions only.",
        "reconciliation":{
            "corporate_visible_count":corporate_total,
            "api_total_reported":first_total,
            "api_rows_read":fetched,
            "api_distinct_ids":len(seen),
            "pages_read":pages,
            "target_official_details_verified":len(jobs),
            "certified_complete":False
        }
    }
