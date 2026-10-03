#!/usr/bin/env python3
import json, re, html, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote
import requests
from daily_worklist import build_worklist

ROOT=Path(__file__).resolve().parent
BATCHES=("jw1","jw2","jw3","jw4")
UA="Mozilla/5.0 (compatible; JobWatchSemanticEnricher/1.0)"
s=requests.Session(); s.headers.update({"User-Agent":UA,"Accept-Language":"en-US,en;q=0.8"})

class FetchError(Exception): pass
def load(name, default=None):
    p=ROOT/name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
def dump(name, obj):
    from pipeline_state import stable_dump
    stable_dump(name,obj,ROOT)


def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
def clean_html(x):
    if not x: return ""
    x=str(x)
    x=re.sub(r"(?is)<(script|style|svg).*?>.*?</\1>"," ",x)
    x=re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>|</h[1-6]>","\n",x)
    x=re.sub(r"<[^>]+>"," ",x)
    x=html.unescape(x).replace("\xa0"," ")
    lines=[re.sub(r"\s+"," ",z).strip(" \t-•") for z in x.splitlines()]
    return "\n".join(z for z in lines if z)
def get_json(url):
    r=s.get(url,timeout=25)
    if r.status_code>=400: raise FetchError(f"HTTP {r.status_code}")
    return r.json()
def get_text(url):
    r=s.get(url,timeout=25,allow_redirects=True)
    if r.status_code>=400: raise FetchError(f"HTTP {r.status_code}")
    return clean_html(r.text)

def workday(url):
    p=urlparse(url); host=p.netloc
    seg=[unquote(x) for x in p.path.split("/") if x]
    while seg and re.fullmatch(r"[a-z]{2}(?:[-_][A-Z]{2})?",seg[0]): seg.pop(0)
    if not seg: raise FetchError("no Workday site slug")
    site=seg[0]; rest="/"+"/".join(seg[1:])
    if not rest.startswith("/job/"): raise FetchError(f"unexpected Workday path {rest}")
    tenant=host.split(".",1)[0]
    api=f"https://{host}/wday/cxs/{tenant}/{site}{rest}"
    d=get_json(api); info=d.get("jobPostingInfo") or d; parts=[]
    for k in ("jobDescription","description","additionalInformation","jobRequisitionInfo"):
        v=info.get(k) if isinstance(info,dict) else None
        if isinstance(v,str) and v.strip(): parts.append(clean_html(v))
    if not parts:
        def walk(x):
            if isinstance(x,str) and len(x)>80: parts.append(clean_html(x))
            elif isinstance(x,dict):
                for v in x.values(): walk(v)
            elif isinstance(x,list):
                for v in x: walk(v)
        walk(info)
    text="\n".join(dict.fromkeys(z for z in parts if z))
    if len(text)<120: raise FetchError("Workday detail text too short")
    return text,api,"workday_cxs_detail"

def smartrecruiters(url,source_id,mapping):
    feed=(mapping.get("ats") or {}).get("public_api_or_feed") or ""
    tenant=None
    m=re.search(r"/companies/([^/]+)/postings",feed)
    if m: tenant=m.group(1)
    if not tenant:
        seg=[x for x in urlparse(url).path.split("/") if x]
        if seg: tenant=seg[0]
    if not tenant: raise FetchError("no SmartRecruiters tenant")
    api=f"https://api.smartrecruiters.com/v1/companies/{tenant}/postings/{source_id}"
    d=get_json(api); parts=[]
    def walk(x):
        if isinstance(x,str) and len(x)>30: parts.append(clean_html(x))
        elif isinstance(x,dict):
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk((d.get("jobAd") or {}).get("sections") or {})
    if not parts: walk(d)
    text="\n".join(dict.fromkeys(z for z in parts if z))
    if len(text)<120: raise FetchError("SmartRecruiters detail text too short")
    return text,api,"smartrecruiters_detail"

def lever(url,source_id,mapping):
    ats=mapping.get("ats") or {}; tenant=ats.get("tenant")
    if not tenant: raise FetchError("no Lever tenant")
    base="https://api.eu.lever.co/v0/postings" if "jobs.eu.lever.co" in (ats.get("inventory_url") or "").lower() else "https://api.lever.co/v0/postings"
    api=f"{base}/{tenant}/{source_id}?mode=json"
    d=get_json(api); parts=[]
    for k in ("descriptionPlain","description"):
        if d.get(k): parts.append(clean_html(d[k]))
    for item in d.get("lists") or []:
        if item.get("text"): parts.append(clean_html(item["text"]))
        if item.get("content"): parts.append(clean_html(item["content"]))
    text="\n".join(dict.fromkeys(z for z in parts if z))
    if len(text)<120: raise FetchError("Lever detail text too short")
    return text,api,"lever_detail"

_ashby={}
def ashby(url,source_id,mapping):
    tenant=(mapping.get("ats") or {}).get("tenant")
    if not tenant: raise FetchError("no Ashby tenant")
    if tenant not in _ashby:
        api=f"https://api.ashbyhq.com/posting-api/job-board/{tenant}"
        _ashby[tenant]=(api,get_json(api))
    api,d=_ashby[tenant]; jobs=d.get("jobs") or []
    hit=next((x for x in jobs if str(x.get("id"))==str(source_id)),None)
    if hit is None:
        canon=url.rstrip("/")
        hit=next((x for x in jobs if str(x.get("jobUrl") or x.get("applyUrl") or "").rstrip("/")==canon),None)
    if hit is None: raise FetchError("Ashby job not found")
    parts=[]
    for k in ("descriptionPlain","descriptionHtml","description","requirements"):
        if hit.get(k): parts.append(clean_html(hit[k]))
    text="\n".join(dict.fromkeys(z for z in parts if z))
    if len(text)<120: raise FetchError("Ashby detail text too short")
    return text,api,"ashby_board_detail"

def fallback(url, title):
    response=s.get(url,timeout=25,allow_redirects=True)
    response.raise_for_status()
    raw=response.text
    # Prefer structured official JobPosting text to navigation/legal boilerplate.
    for block in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',raw,re.I|re.S):
        try:
            data=json.loads(block)
        except ValueError:
            continue
        rows=data if isinstance(data,list) else [data]
        for row in rows:
            candidates=(row.get("@graph") or [row]) if isinstance(row,dict) else []
            for item in candidates:
                if isinstance(item,dict) and "JobPosting" in str(item.get("@type")):
                    text=clean_html(item.get("description"))
                    if len(text)>=120:
                        return text,response.url,"official_jobposting_jsonld"
    text=clean_html(raw)
    if len(text)<180 or not title or str(title).casefold() not in text.casefold():
        raise FetchError("official page does not expose a matching job description")
    if re.search(r'captcha|access denied|job (?:is )?no longer available|position (?:has been|is) closed',text,re.I):
        raise FetchError("official job page blocked or unavailable")
    return text,response.url,"official_html"

def fetch_jd(rec,mapping):
    url=rec.get("canonical_url") or rec.get("apply_url") or ""
    if not url: raise FetchError("missing URL")
    fam=((mapping.get("ats") or {}).get("family") or "").lower()
    host=urlparse(url).netloc.lower()
    if "myworkdayjobs.com" in host or "workday" in fam: return workday(url)
    if "smartrecruiters" in fam or "smartrecruiters.com" in host: return smartrecruiters(url,rec.get("source_id"),mapping)
    if "lever" in fam or "lever.co" in host: return lever(url,rec.get("source_id"),mapping)
    if "ashby" in fam or "ashbyhq.com" in host: return ashby(url,rec.get("source_id"),mapping)
    return fallback(url, rec.get("title"))

def main(batches=BATCHES):
    worklist = build_worklist()
    amazon = load("amazon_target_check.json", {}) or {}
    amazon_by_url = {str(r.get("apply_url", "")).rstrip("/"): r for r in amazon.get("target_jobs", [])}
    for b in batches:
        mapping=load(f"ats_mapping_{b}.json",{}) or {}
        byco={x.get("company"):x for x in mapping.get("companies",[]) if x.get("company")}
        cache=load(f"semantic_jd_cache_{b}.json",{}) or {"version":"1.0","batch":b,"records":{}}
        cache.setdefault("records",{})
        todo=[r for r in worklist["records"] if r["batch"] == b.upper() and r["needs_semantic_review"]]
        ok=fail=reuse=0
        for i,r in enumerate(todo,1):
            k=r.get("job_key"); fp=r.get("fingerprint"); old=cache["records"].get(k)
            if old and old.get("fingerprint")==fp and old.get("status")=="OK" and len(old.get("text") or "")>=120:
                reuse+=1; continue
            if old and old.get("fingerprint")==fp and old.get("status")=="FAILED":
                try:
                    age=(datetime.now(timezone.utc)-datetime.fromisoformat(old["fetched_at"].replace("Z","+00:00"))).total_seconds()
                except (KeyError, ValueError):
                    age=86400
                if age < 21600:  # failed endpoints get a six-hour cooldown
                    from pipeline_state import record_error
                    record_error('LOCAL_RECORD_ERROR','enrichment','JD_UNAVAILABLE',old.get('error') or 'JD fetch cooldown',root=ROOT,batch=b.upper(),company=r.get('company'),job_key=k)
                    fail+=1; continue
            try:
                raw=amazon_by_url.get(str(r.get("canonical_url") or r.get("apply_url") or "").rstrip("/")) if r.get("company")=="Amazon" else None
                if raw and raw.get("fingerprint")==fp and raw.get("description"):
                    txt="\n".join(clean_html(raw.get(f)) for f in ("description","basic_qualifications","preferred_qualifications") if raw.get(f))
                    source=raw["apply_url"]; method="amazon_collected_official_jd"
                else:
                    txt,source,method=fetch_jd(r,byco.get(r.get("company"),{}))
                cache["records"][k]={"fingerprint":fp,"status":"OK","fetched_at":now(),"company":r.get("company"),"title":r.get("title"),"location":r.get("location"),"source_url":source,"method":method,"text":txt[:40000]}
                ok+=1
            except Exception as e:
                from pipeline_state import record_error
                record_error('LOCAL_RECORD_ERROR','enrichment','JD_UNAVAILABLE',e,root=ROOT,batch=b.upper(),company=r.get('company'),job_key=k)
                cache["records"][k]={"fingerprint":fp,"status":"FAILED","fetched_at":now(),"company":r.get("company"),"title":r.get("title"),"location":r.get("location"),"source_url":r.get("canonical_url") or r.get("apply_url"),"method":"failed","error":str(e)[:500],"text":""}
                fail+=1
            if i%25==0: print(f"{b}: {i}/{len(todo)} ok={ok} fail={fail} reuse={reuse}",flush=True)
            time.sleep(0.05)
        cache["generated_at"]=now(); cache["actionable_count"]=len(todo)
        cache["ok_count"]=sum(1 for v in cache["records"].values() if v.get("status")=="OK")
        cache["failed_count"]=sum(1 for v in cache["records"].values() if v.get("status")=="FAILED")
        dump(f"semantic_jd_cache_{b}.json",cache)
        print(f"{b}: actionable={len(todo)} fetched={ok} reused={reuse} failed={fail}")

if __name__=="__main__": main()
