#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, unquote
import requests

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1", "jw2", "jw3", "jw4")
TIMEOUT = 30
MAX_PAGES = 100
COLLECTOR_VERSION = "1.2"
TARGET_LOCATION_RE = re.compile(r"(?<!\\w)(milan|milano|rome|roma|london)(?!\\w)", re.I)
OPEN_STATUSES = {"NEW","STILL_OPEN","UPDATED"}

# Hosted-board identifiers reconstructed from current/official job URLs.
# If one of these endpoints stops working, the run becomes FAILED rather than VERIFIED.
KNOWN_GREENHOUSE_TOKENS = {
    "Adyen": "adyen",
    "N26": "n26",
    "SumUp": "sumup",
    "Trade Republic": "traderepublicbank",
    "Bolt": "bolt",
}

LOCALE_SEGMENT_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
SAFE_TENANT_RE = re.compile(r"^[A-Za-z0-9._-]+$")

session = requests.Session()
session.headers.update({"User-Agent":"job-watch-milano/1.0","Accept":"application/json, text/plain, */*"})

class CollectorError(RuntimeError): pass

def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")

def read_json(path, default=None):
    if not path.exists(): return default
    with path.open("r",encoding="utf-8") as f: return json.load(f)

def write_json(path,obj):
    with path.open("w",encoding="utf-8") as f:
        json.dump(obj,f,ensure_ascii=False,indent=2); f.write("\n")

def get_json(url, params=None):
    r=session.get(url,params=params,timeout=TIMEOUT); r.raise_for_status(); return r.json()

def post_json(url, payload, headers=None):
    h={"Content-Type":"application/json"}
    if headers: h.update(headers)
    r=session.post(url,json=payload,headers=h,timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def clean_text(v):
    if v is None: return None
    s=str(v).strip(); return s or None

def html_to_text(v):
    if not v: return None
    s=str(v)
    s=re.sub(r"<br\s*/?>","\n",s,flags=re.I); s=re.sub(r"</p\s*>","\n",s,flags=re.I)
    s=re.sub(r"<[^>]+>"," ",s); s=re.sub(r"&nbsp;"," ",s); s=re.sub(r"&amp;","&",s)
    s=re.sub(r"\s+"," ",s).strip(); return s or None

def location_matches(location):
    """Match only target cities, not substrings such as Roma inside Romagna."""
    if not location:
        return False
    return bool(TARGET_LOCATION_RE.search(str(location)))

def fingerprint(job):
    fields={k:job.get(k) for k in ("title","location","department","team","employment_type","description","url")}
    return hashlib.sha256(json.dumps(fields,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]

def infer_token(url, hosts):
    if not url: return None
    p=urlparse(url)
    if not any(h in p.netloc.casefold() for h in hosts): return None
    parts=[x for x in p.path.split("/") if x]; return parts[-1] if parts else None

def key(company,source_id): return f"{company}::{source_id}"

def collect_lever(company):
    ats=company.get("ats",{})
    tenant=clean_text(ats.get("tenant")) or infer_token(ats.get("inventory_url"),("jobs.lever.co","jobs.eu.lever.co"))
    if not tenant: raise CollectorError("Lever tenant missing")
    eu="jobs.eu.lever.co" in (ats.get("inventory_url") or "").casefold()
    base="https://api.eu.lever.co/v0/postings" if eu else "https://api.lever.co/v0/postings"
    url=f"{base}/{tenant}"; all_jobs=[]; skip=0; limit=100
    for _ in range(MAX_PAGES):
        page=get_json(url,{"mode":"json","skip":skip,"limit":limit})
        if not isinstance(page,list): raise CollectorError("Unexpected Lever response")
        all_jobs.extend(page)
        if len(page)<limit: break
        skip+=limit
    else: raise CollectorError("Lever pagination safety limit")
    jobs=[]
    for raw in all_jobs:
        c=raw.get("categories") or {}; locs=c.get("allLocations") or []
        loc=" | ".join(map(str,locs)) if locs else c.get("location")
        j={"source_id":str(raw.get("id")),"title":clean_text(raw.get("text")),"location":clean_text(loc),
           "department":clean_text(c.get("department")),"team":clean_text(c.get("team")),
           "employment_type":clean_text(c.get("commitment")),"description":clean_text(raw.get("descriptionPlain")) or html_to_text(raw.get("description")),
           "url":clean_text(raw.get("hostedUrl")),"apply_url":clean_text(raw.get("applyUrl")),"updated_at":None}
        if location_matches(j["location"]): jobs.append(j)
    return {"coverage":"VERIFIED","collector":"lever_api","inventory_count":len(all_jobs),"jobs":jobs,"source_url":url}

def collect_ashby(company):
    ats=company.get("ats",{})
    tenant=clean_text(ats.get("tenant")) or infer_token(ats.get("inventory_url"),("jobs.ashbyhq.com",))
    if not tenant: raise CollectorError("Ashby board name missing")
    url=f"https://api.ashbyhq.com/posting-api/job-board/{tenant}"
    data=get_json(url,{"includeCompensation":"true"}); all_jobs=data.get("jobs")
    if not isinstance(all_jobs,list): raise CollectorError("Unexpected Ashby response")
    jobs=[]
    for raw in all_jobs:
        locs=[clean_text(raw.get("location"))]
        for item in raw.get("secondaryLocations") or []:
            if isinstance(item,dict): locs.append(clean_text(item.get("location")))
        loc=" | ".join(x for x in locs if x)
        j={"source_id":str(raw.get("id") or raw.get("jobPostingId") or raw.get("title")),"title":clean_text(raw.get("title")),
           "location":clean_text(loc),"department":clean_text(raw.get("department")),"team":clean_text(raw.get("team")),
           "employment_type":clean_text(raw.get("employmentType")),"description":html_to_text(raw.get("descriptionHtml")) or clean_text(raw.get("descriptionPlain")),
           "compensation":raw.get("compensation"),"url":clean_text(raw.get("jobUrl")) or clean_text(raw.get("url")),
           "apply_url":clean_text(raw.get("applyUrl")),"updated_at":clean_text(raw.get("publishedAt"))}
        if location_matches(j["location"]): jobs.append(j)
    return {"coverage":"VERIFIED","collector":"ashby_public_api","inventory_count":len(all_jobs),"jobs":jobs,"source_url":url}

def greenhouse_token(company):
    ats=company.get("ats",{})
    token=clean_text(ats.get("tenant")) or infer_token(
        ats.get("inventory_url"), ("greenhouse.io",)
    )
    if token and SAFE_TENANT_RE.fullmatch(token):
        return token
    return KNOWN_GREENHOUSE_TOKENS.get(company.get("company"))

def collect_greenhouse(company):
    ats=company.get("ats",{})
    token=greenhouse_token(company)
    if not token: raise CollectorError("Greenhouse token missing")
    url=f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    data=get_json(url,{"content":"true"}); all_jobs=data.get("jobs")
    if not isinstance(all_jobs,list): raise CollectorError("Unexpected Greenhouse response")
    total=(data.get("meta") or {}).get("total")
    if total is not None and int(total)!=len(all_jobs): raise CollectorError(f"Greenhouse count mismatch {total}!={len(all_jobs)}")
    jobs=[]
    for raw in all_jobs:
        deps=raw.get("departments") or []; dept=" | ".join(clean_text(x.get("name")) for x in deps if isinstance(x,dict) and clean_text(x.get("name")))
        loc=clean_text((raw.get("location") or {}).get("name"))
        j={"source_id":str(raw.get("id")),"title":clean_text(raw.get("title")),"location":loc,"department":clean_text(dept),
           "team":None,"employment_type":None,"description":html_to_text(raw.get("content")),"url":clean_text(raw.get("absolute_url")),
           "apply_url":clean_text(raw.get("absolute_url")),"updated_at":clean_text(raw.get("updated_at"))}
        if location_matches(loc): jobs.append(j)
    return {"coverage":"VERIFIED","collector":"greenhouse_job_board_api","inventory_count":len(all_jobs),"jobs":jobs,"source_url":url}

def sr_identifier(ats):
    if clean_text(ats.get("tenant")): return clean_text(ats.get("tenant"))
    for u in (ats.get("inventory_url"),ats.get("career_site")):
        if not u: continue
        p=urlparse(u)
        if "smartrecruiters.com" not in p.netloc.casefold(): continue
        parts=[x for x in p.path.split("/") if x]
        if parts: return parts[0]
    return None

def collect_smartrecruiters(company):
    ats=company.get("ats",{}); ident=sr_identifier(ats)
    if not ident: raise CollectorError("SmartRecruiters identifier missing")
    url=f"https://api.smartrecruiters.com/v1/companies/{ident}/postings"
    offset=0; limit=100; all_jobs=[]; total=None
    for _ in range(MAX_PAGES):
        data=get_json(url,{"limit":limit,"offset":offset,"destination":"PUBLIC"}); page=data.get("content")
        if not isinstance(page,list): raise CollectorError("Unexpected SmartRecruiters response")
        if total is None: total=int(data.get("totalFound",len(page)))
        all_jobs.extend(page)
        if len(all_jobs)>=total: break
        if not page: raise CollectorError("SmartRecruiters paging stopped early")
        offset+=len(page)
    else: raise CollectorError("SmartRecruiters pagination safety limit")
    if total is not None and len(all_jobs)!=total: raise CollectorError(f"SmartRecruiters count mismatch {total}!={len(all_jobs)}")
    jobs=[]
    for raw in all_jobs:
        loc=raw.get("location") or {}; loc_text=", ".join(str(x) for x in (loc.get("city"),loc.get("region"),loc.get("country")) if x)
        if not location_matches(loc_text): continue
        pid=str(raw.get("id") or raw.get("uuid")); detail={}
        try: detail=get_json(f"{url}/{pid}")
        except Exception: pass
        dept=raw.get("department") or {}; sections=((detail.get("jobAd") or {}).get("sections") or {})
        desc=html_to_text((sections.get("jobDescription") or {}).get("text")) or html_to_text((sections.get("qualifications") or {}).get("text"))
        j={"source_id":pid,"title":clean_text(detail.get("name")) or clean_text(raw.get("name")),"location":clean_text(loc_text),
           "department":clean_text(dept.get("label")),"team":None,"employment_type":clean_text((raw.get("typeOfEmployment") or {}).get("label")),
           "description":desc,"compensation":detail.get("compensation"),"url":clean_text(detail.get("jobAdUrl")) or clean_text(raw.get("ref")),
           "apply_url":clean_text(detail.get("applyUrl")),"updated_at":clean_text(detail.get("releasedDate"))}
        jobs.append(j)
    return {"coverage":"VERIFIED","collector":"smartrecruiters_posting_api","inventory_count":len(all_jobs),"jobs":jobs,"source_url":url}


def workday_config(company):
    ats=company.get("ats",{})
    inventory=clean_text(ats.get("inventory_url"))
    if not inventory:
        raise CollectorError("Workday inventory URL missing")
    p=urlparse(inventory)
    host=p.netloc
    if "myworkdayjobs.com" not in host.casefold():
        raise CollectorError("Workday inventory is not a myworkdayjobs.com URL")

    tenant=host.split(".")[0]
    parts=[unquote(x) for x in p.path.split("/") if x]
    while parts and LOCALE_SEGMENT_RE.fullmatch(parts[0]):
        parts.pop(0)
    if not parts:
        raise CollectorError("Workday career-site name missing from URL")
    site=parts[0]
    return host, tenant, site

def collect_workday(company):
    host, tenant, site = workday_config(company)
    search_url=f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    referer=f"https://{host}/{site}"
    limit=20
    offset=0
    total=None
    all_jobs=[]

    for _ in range(MAX_PAGES):
        payload={
            "appliedFacets": {},
            "limit": limit,
            "offset": offset,
            "searchText": ""
        }
        data=post_json(
            search_url,
            payload,
            headers={
                "Accept":"application/json",
                "Referer":referer,
                "Origin":f"https://{host}",
            },
        )
        page=data.get("jobPostings")
        if not isinstance(page,list):
            raise CollectorError("Unexpected Workday CXS response")
        if total is None:
            try:
                total=int(data.get("total", len(page)))
            except Exception:
                total=len(page)

        all_jobs.extend(page)

        if len(all_jobs) >= total:
            break
        if not page:
            raise CollectorError(
                f"Workday paging stopped early: retrieved={len(all_jobs)}, total={total}"
            )
        offset += len(page)
    else:
        raise CollectorError("Workday pagination safety limit")

    if total is not None and len(all_jobs) < total:
        raise CollectorError(
            f"Workday count mismatch: total={total}, retrieved={len(all_jobs)}"
        )

    jobs=[]
    for raw in all_jobs:
        loc=clean_text(raw.get("locationsText"))
        if not location_matches(loc):
            continue

        external_path=clean_text(raw.get("externalPath"))
        if not external_path:
            continue

        detail={}
        detail_url=f"https://{host}/wday/cxs/{tenant}/{site}{external_path}"
        try:
            detail=get_json(detail_url)
        except Exception:
            detail={}

        info=detail.get("jobPostingInfo") or {}
        extra_locations=info.get("additionalLocations") or []
        loc_parts=[loc, clean_text(info.get("location"))]
        if isinstance(extra_locations,list):
            loc_parts.extend(clean_text(x) for x in extra_locations)
        full_location=" | ".join(dict.fromkeys(x for x in loc_parts if x))

        canonical=f"https://{host}/{site}{external_path}"
        source_id=clean_text(info.get("jobReqId")) or external_path

        job={
            "source_id": source_id,
            "title": clean_text(info.get("title")) or clean_text(raw.get("title")),
            "location": clean_text(full_location) or loc,
            "department": None,
            "team": None,
            "employment_type": clean_text(info.get("timeType")),
            "description": html_to_text(info.get("jobDescription")),
            "compensation": None,
            "url": canonical,
            "apply_url": canonical,
            "updated_at": clean_text(info.get("startDate")) or clean_text(raw.get("postedOn")),
        }
        jobs.append(job)
        time.sleep(0.03)

    return {
        "coverage":"VERIFIED",
        "collector":"workday_cxs",
        "inventory_count":len(all_jobs),
        "jobs":jobs,
        "source_url":search_url,
    }


def choose(company):
    ats=company.get("ats") or {}
    family=(clean_text(ats.get("family")) or "").casefold()
    inventory=clean_text(ats.get("inventory_url")) or ""
    host=urlparse(inventory).netloc.casefold()

    # Workday: only when we have a canonical public Workday board URL.
    if "workday" in family and "myworkdayjobs.com" in host:
        return collect_workday

    # Hosted boards / public APIs. Avoid false positives where the vendor name
    # appears only as an embedded/application backend behind a custom frontend.
    if "ashby" in family and ("ashbyhq.com" in host or clean_text(ats.get("tenant"))):
        return collect_ashby

    if "greenhouse" in family:
        if greenhouse_token(company):
            return collect_greenhouse

    if "lever" in family:
        tenant=clean_text(ats.get("tenant"))
        if "lever.co" in host or (tenant and SAFE_TENANT_RE.fullmatch(tenant) and "lever" == family.strip()):
            return collect_lever

    if "smartrecruiters" in family and "attrax" not in family:
        ident=clean_text(ats.get("tenant"))
        if "smartrecruiters.com" in host or (ident and SAFE_TENANT_RE.fullmatch(ident) and family.strip()=="smartrecruiters"):
            return collect_smartrecruiters

    return None

def previous_index(path):
    prev=read_json(path,{}) or {}
    # Reset the baseline whenever collector semantics change.
    # This prevents old false positives from being emitted as fake CLOSED jobs.
    if prev.get("version") != COLLECTOR_VERSION:
        return {}
    idx={}
    for c in prev.get("companies",[]):
        name=c.get("company")
        for j in c.get("jobs",[]):
            if name and j.get("source_id"): idx[key(name,str(j["source_id"]))]=j
    return idx

def collect_batch(batch):
    mp=ROOT/f"ats_mapping_{batch}.json"; out=ROOT/f"current_jobs_{batch}.json"
    mapping=read_json(mp)
    if not mapping: raise CollectorError(f"Missing {mp.name}")
    prev=previous_index(out); companies_out=[]
    summary={"companies_total":len(mapping.get("companies") or []),"collector_supported":0,"VERIFIED":0,"FAILED":0,"NOT_CHECKED":0,
             "target_jobs_open":0,"NEW":0,"STILL_OPEN":0,"UPDATED":0,"CLOSED":0,"UNKNOWN":0}
    for company in mapping.get("companies") or []:
        name=company.get("company"); fn=choose(company)
        if fn is None:
            result={"coverage":"NOT_CHECKED","collector":"unsupported_in_mvp","inventory_count":None,"jobs":[],
                    "reason":"ATS family/method not yet supported by collector v1.2","source_url":(company.get("ats") or {}).get("inventory_url")}
        else:
            summary["collector_supported"]+=1
            try:
                result=fn(company); result["reason"]=None
            except Exception as e:
                result={"coverage":"FAILED","collector":getattr(fn,"__name__","collector"),"inventory_count":None,"jobs":[],
                        "reason":f"{type(e).__name__}: {e}","source_url":(company.get("ats") or {}).get("inventory_url")}
        current=[]; ids=set()
        for j in result["jobs"]:
            k=key(name,str(j["source_id"])); old=prev.get(k); j["fingerprint"]=fingerprint(j)
            if old is None: j["status"]="NEW"
            elif old.get("fingerprint") and old.get("fingerprint")!=j["fingerprint"]: j["status"]="UPDATED"
            else: j["status"]="STILL_OPEN"
            ids.add(str(j["source_id"])); current.append(j)
        for k,old in prev.items():
            if not k.startswith(f"{name}::"): continue
            sid=str(old.get("source_id"))
            if sid in ids or old.get("status") not in OPEN_STATUSES: continue
            x=dict(old); x["status"]="CLOSED" if result["coverage"]=="VERIFIED" else "UNKNOWN"; current.append(x)
        for j in current:
            st=j.get("status")
            if st in summary: summary[st]+=1
            if st in OPEN_STATUSES: summary["target_jobs_open"]+=1
        summary[result["coverage"]]+=1
        companies_out.append({"company":name,"mapping_level":(company.get("verification") or {}).get("level"),
                              "ats_family":(company.get("ats") or {}).get("family"),"coverage":result["coverage"],
                              "collector":result["collector"],"inventory_count":result["inventory_count"],
                              "target_jobs_count":sum(1 for j in current if j.get("status") in OPEN_STATUSES),
                              "source_url":result.get("source_url"),"reason":result.get("reason"),"jobs":current})
        time.sleep(0.1)
    payload={"version":COLLECTOR_VERSION,"batch":mapping.get("batch") or batch.upper(),"batch_name":mapping.get("batch_name"),"generated_at":utc_now(),
             "collector_scope":["Lever","Ashby","Greenhouse","SmartRecruiters","Workday CXS"],
             "location_scope":["Milan","Milano","Rome","Roma","London"],
             "coverage_note":"VERIFIED means the structured public inventory was exhausted/reconciled in this run. Unsupported ATS remain NOT_CHECKED for ChatGPT fallback.",
             "summary":summary,"companies":companies_out}
    write_json(out,payload); return payload

def main():
    for batch in BATCHES:
        r=collect_batch(batch)
        print(batch.upper(), json.dumps(r["summary"], ensure_ascii=False))
        for company in r.get("companies", []):
            if company.get("coverage") == "FAILED":
                print(
                    f"  FAILED | {company.get('company')} | "
                    f"{company.get('collector')} | {company.get('reason')}"
                )
    return 0

if __name__=="__main__": raise SystemExit(main())
