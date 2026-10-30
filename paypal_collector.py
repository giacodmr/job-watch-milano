"""PayPal Eightfold PCS-X target-scope certified official vacancies.

The employer-hosted Eightfold public search declares a count for each location
filter. Two identical complete Italy, Milan, Rome result sets are reconciled
with every Italy job permalink in the employer's first-party sitemap and
individual exact-ID/name detail. VERIFIED covers only Milan/Rome, the two
configured PayPal allowed_locations, NOT all global requisitions.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import collector as c

ORIGIN = "https://paypal.eightfold.ai"
ENDPOINT = ORIGIN + "/api/pcsx/search"
DETAIL = ORIGIN + "/api/pcsx/position_details"
SITEMAP = ORIGIN + "/careers/sitemap.xml?domain=paypal.com"
SOURCE = ORIGIN + "/careers?domain=paypal.com"
COUNTRY = "italy"
IDS = re.compile(r"^[0-9]{7,18}$")
JOB_PATH = re.compile(r"^/careers/job/([0-9]{7,18})(?:-[a-z0-9-]+)?/?$",re.I)
MAX_TARGET = 500


def _search(city):
    params = {"domain": "paypal.com", "query": "", "location": city, "start": 0, "num": 10}
    try:
        o = c.get_json(ENDPOINT, params=params)
    except Exception as exc:
        raise c.NotCheckable(f"PayPal official public PCS-X {city} search unavailable") from exc
    if not isinstance(o,dict) or o.get("status") not in ("ok", "OK", "success", 200, None):
        raise c.NotCheckable(f"PayPal PCS-X {city} response status unexpected")
    data=o.get("data")
    if not isinstance(data,dict) or not isinstance(data.get("positions"),list) or not isinstance(data.get("count"),int):
        raise c.NotCheckable(f"PayPal PCS-X {city} lacks published total or positions array")
    n=data["count"];rows=data["positions"]
    if n<0 or n>MAX_TARGET or len(rows)!=n:
        raise c.NotCheckable(f"PayPal PCS-X {city} is paginated or exceeds bounded location scope: count {n}, rows {len(rows)}")
    out={}
    for row in rows:
        if not isinstance(row,dict):
            raise c.NotCheckable("PayPal official PCS-X item is malformed")
        sid=str(row.get("id") or "")
        title=c.clean_text(row.get("name"))
        path=c.clean_text(row.get("positionUrl")) or ""
        locations=row.get("locations")
        if not IDS.fullmatch(sid) or not title or not isinstance(locations,list) or not locations:
            raise c.NotCheckable(f"PayPal PCS-X {city} entry lacks ID/title/locations")
        if not JOB_PATH.fullmatch(path) or JOB_PATH.fullmatch(path).group(1)!=sid:
            raise c.NotCheckable(f"PayPal PCS-X {city} entry URL not its ID")
        if sid in out:
            raise c.NotCheckable(f"PayPal PCS-X {city} duplicated requisition {sid}")
        vals=[c.clean_text(x) for x in locations]
        if any(not x for x in vals):
            raise c.NotCheckable("PayPal PCS-X location array malformed")
        out[sid]={
            "id":sid,"title":title,"locations":vals,
            "url":ORIGIN+path,"department":c.clean_text(row.get("department")),
            "displayJobId":c.clean_text(row.get("displayJobId")),
            "postedTs":row.get("postedTs"),
            "workLocationOption":c.clean_text(row.get("workLocationOption")),
        }
    return out


def _sitemap_italy_ids():
    try:
        body,landed=c.get_html(SITEMAP)
    except Exception as exc:
        raise c.NotCheckable("PayPal official jobs sitemap unavailable") from exc
    p=urlparse(landed)
    if p.scheme!="https" or p.hostname!="paypal.eightfold.ai" or p.path!="/careers/sitemap.xml":
        raise c.NotCheckable("PayPal job sitemap redirected outside first-party board")
    try:
        root=ET.fromstring(body)
    except ET.ParseError as exc:
        raise c.NotCheckable("PayPal first-party XML sitemap malformed") from exc
    if not root.tag.endswith("urlset"):
        raise c.NotCheckable("PayPal job sitemap does not expose a URL set")
    ids=set()
    total=0
    for x in root.iter():
        if not x.tag.endswith("loc") or not x.text:continue
        url=urlparse(x.text)
        if url.scheme!="https" or url.hostname!="paypal.eightfold.ai":continue
        m=JOB_PATH.fullmatch(url.path)
        if not m:continue
        total+=1
        # Sitemaps may lag and contain globally stale jobs. Require exact
        # Italy slug parity so target scope cannot silently miss Milan/Rome.
        if re.search(r"(?:^|[-_/])(?:italy|milan|milano|rome|roma)(?:[-_/]|$)",url.path,re.I):
            ids.add(m.group(1))
    if total<=0:
        raise c.NotCheckable("PayPal sitemap has no official job links")
    return ids,total


def _detail(row):
    sid=row["id"]
    try:
        data=c.get_json(DETAIL, params={"domain":"paypal.com","position_id":sid})
    except Exception as exc:
        raise c.NotCheckable(f"PayPal official PCS-X detail unavailable for {sid}") from exc
    d=data.get("data") if isinstance(data,dict) else None
    if not isinstance(d,dict):
        raise c.NotCheckable(f"PayPal official PCS-X detail missing for {sid}")
    if str(d.get("id"))!=sid or c.clean_text(d.get("name"))!=row["title"]:
        raise c.NotCheckable(f"PayPal {sid} official detail ID or title mismatch")
    if d.get("locations")!=row["locations"] or d.get("positionUrl")!="/careers/job/"+sid:
        raise c.NotCheckable(f"PayPal {sid} detail does not match public location/ID")
    if d.get("publicUrl")!=row["url"]:
        raise c.NotCheckable(f"PayPal {sid} public application URL mismatch")
    if not c.clean_text(d.get("jobDescription")):
        raise c.NotCheckable(f"PayPal {sid} detail has no public job description")


def collect_paypal(company):
    if company.get("company")!="PayPal":
        raise c.NotCheckable("PayPal adapter invoked for another company")
    # Existing user/company policy explicitly permits Milan and Rome only.
    italian=_search("Italy")
    milan=_search("Milan")
    rome=_search("Rome")
    italian2=_search("Italy")
    milan2=_search("Milan")
    rome2=_search("Rome")
    if italian!=italian2 or milan!=milan2 or rome!=rome2:
        raise c.NotCheckable("PayPal PCS-X Italy/city target inventory changed within double snapshots")
    if set(italian)!=set(milan)|set(rome):
        raise c.NotCheckable("PayPal Italy jobs not exhaustively covered by Milan and Rome filters")
    for sid,row in italian.items():
        if not any("italy" in x.casefold() for x in row["locations"]):
            raise c.NotCheckable(f"PayPal Italian location filter returned a foreign requisition {sid}")
        if not c.location_matches(" | ".join(row["locations"]),"PayPal"):
            raise c.NotCheckable(f"PayPal Italian requisition {sid} not proven Milan/Rome")
    geo_sitemap,global_sitemap_count=_sitemap_italy_ids()
    if geo_sitemap!=set(italian):
        raise c.NotCheckable(f"PayPal sitemap/active Italy IDs drift: sitemap {len(geo_sitemap)}, PCS-X {len(italian)}")
    jobs=[]
    for sid,row in italian.items():
        _detail(row)
        jobs.append(c.compact_job(
            "PayPal",sid,title=row["title"],location=" | ".join(row["locations"]),
            department=row["department"],employment_type=row["workLocationOption"],
            published_at=c.epoch_millis_to_iso(row["postedTs"]),
            canonical=row["url"],apply_url=row["url"],
        ))
    return {
        "coverage":"VERIFIED",
        "collector":"paypal_eightfold_pcsx_geographic_italy_sitemap_detail_parity_v1",
        "inventory_count":len(italian),
        "jobs":jobs,
        "source_url":SOURCE,
        "reconciliation":{
            "verified_scope":"PayPal Milan/Rome only; no claim of complete worldwide Eightfold inventory",
            "italy_active_count":len(italian),
            "milan_count":len(milan),
            "rome_count":len(rome),
            "two_stable_location_snapshots":True,
            "italy_sitemap_id_parity":True,
            "global_sitemap_jobs_unreconciled":global_sitemap_count,
            "first_party_detail_id_title_location_parity":len(jobs),
        },
    }
