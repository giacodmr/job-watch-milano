"""UniCredit first-party Avature public portal certified paginated source.

Enumerate all official global result pages (15 items/page) against the visible
total before geography. For every Italian posting, read the *structured City
field* from its official JobDetail page; titles/descriptions are never used
to infer a location. Fail closed if pagination, IDs, or City evidence drifts.
"""
from __future__ import annotations

import html
import re
import time
from urllib.parse import urlparse

import collector as c

URL="https://careers.unicredit.eu/en_GB/jobsuche/SearchJobs/"
SIZE=15
MAX_PAGES=90
DETAIL_RE=re.compile(r"^/en_GB/jobsuche/JobDetail/(?:[^/]+/)?([0-9]{4,})/?$",re.I)
CARD_RE=re.compile(r'<article\b[^>]*class=["\'][^"\']*\barticle--result\b[^"\']*["\'][^>]*>.*?</article>',re.I|re.S)
TITLE_RE=re.compile(r'<h3[^>]*class=["\'][^"\']*\barticle__header__text__title\b[^"\']*["\'][^>]*>\s*<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',re.I|re.S)
LEGEND_RE=re.compile(r'<div[^>]*class=["\'][^"\']*\blist-controls__text__legend\b[^"\']*["\'][^>]*>(.*?)</div>',re.I|re.S)
CITY_FIELD_RE=re.compile(
    r'<div[^>]*class=["\'][^"\']*\barticle__content__view__field\b[^"\']*["\'][^>]*>\s*'
    r'<div[^>]*class=["\'][^"\']*\barticle__content__view__field__label\b[^"\']*["\'][^>]*>\s*City\s*</div>\s*'
    r'<div[^>]*class=["\'][^"\']*\barticle__content__view__field__value\b[^"\']*["\'][^>]*>(.*?)</div>',
    re.I|re.S
)
SPAN_RE=re.compile(r'<span[^>]*class=["\']([^"\']*job-info-icon[^"\']*)["\'][^>]*>(.*?)</span>',re.I|re.S)


def _official(url, detail=False, sid=None):
    p=urlparse(str(url))
    if p.scheme!="https" or p.hostname!="careers.unicredit.eu" or p.query or p.fragment:
        return False
    if detail:
        match=DETAIL_RE.fullmatch(p.path)
        return bool(match and match.group(1)==str(sid))
    return p.path.rstrip("/")=="/en_GB/jobsuche/SearchJobs"


def _page(offset):
    if offset<0 or offset%SIZE:
        raise c.NotCheckable("UniCredit pagination offset is not aligned")
    try:
        body,url=c.get_html(URL,params={"jobRecordsPerPage":SIZE,"jobOffset":offset})
    except Exception as e:
        raise c.NotCheckable(f"UniCredit first-party search page unavailable at offset {offset}") from e
    # The portal can append the query in its redirect; preserve strict host/path.
    p=urlparse(url)
    if p.scheme!="https" or p.hostname!="careers.unicredit.eu" or p.path.rstrip("/")!="/en_GB/jobsuche/SearchJobs":
        raise c.NotCheckable("UniCredit job pagination redirected outside its official inventory")
    legend=LEGEND_RE.search(body)
    if not legend:
        raise c.NotCheckable("UniCredit official result counter missing")
    m=re.search(r"(\d+)\s*-\s*(\d+)\s+of\s+(\d+)\s+results",c.html_to_text(legend.group(1)) or "",re.I)
    if not m:
        raise c.NotCheckable("UniCredit official total/range counter unparseable")
    start,end,total=map(int,m.groups())
    if total<=0 or total>MAX_PAGES*SIZE:
        raise c.NotCheckable(f"UniCredit total outside safe 1..{MAX_PAGES*SIZE}: {total}")
    if start!=offset+1 or end!=min(total,offset+SIZE):
        raise c.NotCheckable(f"UniCredit offset {offset}: got {start}-{end} of {total}")
    jobs=[]
    for raw in CARD_RE.findall(body):
        link=TITLE_RE.search(raw)
        if not link:
            raise c.NotCheckable("UniCredit official result lacks title/detail link")
        url=html.unescape(link.group(1))
        match=DETAIL_RE.fullmatch(urlparse(url).path)
        if not match or not _official(url,True,match.group(1)):
            raise c.NotCheckable("UniCredit job URL does not contain official numeric ID")
        title=c.html_to_text(link.group(2))
        if not title:
            raise c.NotCheckable("UniCredit official result title missing")
        fields={}
        for klass,raw_text in SPAN_RE.findall(raw):
            if "job-info-icon_world" in klass:fields["world"]=c.html_to_text(raw_text)
            if "job-info-icon_function" in klass:fields["department"]=c.html_to_text(raw_text)
            if "job-info-icon_work" in klass:fields["employment"]=c.html_to_text(raw_text)
        if not fields.get("world"):
            raise c.NotCheckable("UniCredit card has no official country metadata")
        jobs.append({"id":match.group(1),"url":url,"title":title,**fields})
    if len(jobs)!=end-start+1:
        raise c.NotCheckable(f"UniCredit official result count mismatch {len(jobs)}!={end-start+1}")
    return total,jobs


def _italy_country(world):
    return str(world or "").strip().casefold() in ("italy","italia")


def _city_details(row):
    sid=row["id"]
    if not _official(row.get("url"),True,sid):
        raise c.NotCheckable(f"UniCredit invalid detail URL for {sid}")
    try:
        body,landed=c.get_html(row["url"])
    except Exception as e:
        raise c.NotCheckable(f"UniCredit detail not available for {sid}") from e
    if not _official(landed,True,sid):
        raise c.NotCheckable(f"UniCredit detail redirected outside requisition {sid}")
    m=CITY_FIELD_RE.search(body)
    if not m:
        raise c.NotCheckable(f"UniCredit Italian requisition {sid} has no structured City field")
    city=c.html_to_text(m.group(1))
    if not city or len(city)>1000:
        raise c.NotCheckable(f"UniCredit requisition {sid} City field empty or unexpectedly long")
    # Require explicit delimiters: a *description* mentioning Milan never counts.
    segments=[s.strip().casefold() for s in re.split(r"[,;|]",city) if s.strip()]
    if not segments or len(segments)>100:
        raise c.NotCheckable(f"UniCredit requisition {sid} City list malformed")
    valid=[]
    if any(x in ("milano","milan") for x in segments):valid.append("Milan")
    if any(x in ("roma","rome") for x in segments):valid.append("Rome")
    return valid,city


def collect_unicredit(company):
    if company.get("company")!="UniCredit":
        raise c.NotCheckable("UniCredit collector called for another source")
    total,first=_page(0)
    rows=list(first)
    for offset in range(SIZE,total,SIZE):
        n,page=_page(offset)
        if n!=total:
            raise c.NotCheckable(f"UniCredit global total changed while enumerating: {total}->{n}")
        rows.extend(page)
    ids=[row["id"] for row in rows]
    if len(rows)!=total or len(set(ids))!=total:
        raise c.NotCheckable(f"UniCredit global inventory not unique/exhaustive: {len(rows)} rows / {len(set(ids))} IDs, expected {total}")

    jobs=[]
    italian=[row for row in rows if _italy_country(row.get("world"))]
    for row in italian:
        locations,raw_city=_city_details(row)
        if locations:
            jobs.append(c.compact_job("UniCredit",row["id"],title=row["title"],location=" | ".join(locations),
               department=row.get("department"),employment_type=row.get("employment"),
               canonical=row["url"]))
        time.sleep(0.08)

    # Confirm the first page's official visible total and first-page order still
    # agree after full traversal + Italian detail validation.
    fresh_total,fresh_first=_page(0)
    if total!=fresh_total or [(x["id"],x["title"],x["url"]) for x in first]!=[(x["id"],x["title"],x["url"]) for x in fresh_first]:
        raise c.NotCheckable("UniCredit first-page snapshot drift after complete enumeration")

    return {
       "coverage":"VERIFIED",
       "collector":"unicredit_avature_official_global_count_city_detail_v1",
       "inventory_count":total,
       "source_url":URL,
       "jobs":jobs,
       "reconciliation":{
           "scope":"UniCredit group official global Avature SearchJobs portal",
           "pages_exhausted":(total+SIZE-1)//SIZE,
           "global_ids_unique":len(set(ids)),
           "italian_details_checked":len(italian),
           "italy_explicit_city_matches":len(jobs),
           "stable_first_page_after_scan":True,
       },
    }
