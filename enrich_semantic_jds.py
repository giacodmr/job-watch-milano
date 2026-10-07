#!/usr/bin/env python3
import json, re, html, hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote
import requests

ROOT=Path(__file__).resolve().parent
BATCHES=("jw1","jw2","jw3","jw4")
UA="Mozilla/5.0 (compatible; JobWatchSemanticEnricher/1.0)"
s=requests.Session(); s.headers.update({"User-Agent":UA,"Accept-Language":"en-US,en;q=0.8"})

class FetchError(Exception): pass

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

def oracle(url, source_id, title):
    """Oracle CE serves an empty app shell; fetch the public external JD by ID."""
    path = urlparse(url).path
    match = re.search(r'/sites/([A-Za-z0-9_]+)/job/([^/]+)', path)
    if not match or unquote(match.group(2)) != str(source_id):
        raise FetchError('Oracle URL/requisition ID mismatch')
    response = s.get(url, timeout=25, allow_redirects=True)
    response.raise_for_status()
    backend = re.search(r'data-apibaseurl=["\']([^"\']+)', response.text, re.I)
    base = urlparse(html.unescape(backend.group(1))) if backend else urlparse(url)
    if base.scheme != 'https' or not (base.hostname or '').endswith('.oraclecloud.com'):
        raise FetchError('Oracle public backend not identified on official page')
    api = f'https://{base.netloc}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails'
    detail = s.get(api, params={'onlyData':'true', 'expand':'all',
        'finder':f'ById;Id="{source_id}",siteNumber={match.group(1)}'},
        headers={'Ora-Irc-Language':'en', 'REST-Framework-Version':'1'}, timeout=25)
    detail.raise_for_status()
    rows = detail.json().get('items', [])
    item = next((r for r in rows if str(r.get('Id')) == str(source_id)), None)
    if not item or str(item.get('Title') or '').strip().casefold() != str(title or '').strip().casefold():
        raise FetchError('Oracle detail does not match requested requisition/title')
    fields = ('ExternalDescriptionStr', 'ExternalResponsibilitiesStr', 'ExternalQualificationsStr',
              'CorporateDescriptionStr', 'OrganizationDescriptionStr')
    parts = [clean_html(item.get(k)) for k in fields if item.get(k)]
    text = '\n'.join(dict.fromkeys(parts))
    if len(clean_html(item.get('ExternalDescriptionStr'))) < 120:
        raise FetchError('Oracle external job description missing or too short')
    return text, detail.url, 'oracle_ce_external_detail'

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
    if re.search(r'/sites/[A-Za-z0-9_]+/job/', urlparse(url).path):
        return oracle(url, rec.get('source_id'), rec.get('title'))
    return fallback(url, rec.get("title"))

def fetch_candidates(batch, limit=20, root=None, fetch=False, exclude_keys=()):
    """Small ephemeral worker packet. No cache or daily-state writes."""
    from sync_analysis_state import project_batch
    from location_policy import allowed
    from pipeline_state import load as read
    root = root or ROOT
    excluded = set(exclude_keys)
    todo = [r for r in project_batch(batch, root)['queue'] if r['job_key'] not in excluded][:limit]
    mapping = read(f'ats_mapping_{batch}.json', {}, root)
    byco = {x['company']:x for x in mapping.get('companies',[])}
    result = []
    for rec in todo:
        if not allowed(rec['company'], rec.get('location'), root): continue
        rec = dict(rec)
        if fetch:
            try:
                text, source, method = fetch_jd(rec, byco.get(rec['company'], {}))
                rec['jd'] = {'text':text, 'source_url':source, 'method':method, 'fetched_at':now(),
                             'text_sha256': hashlib.sha256(text.encode()).hexdigest()}
            except Exception as exc:
                rec['jd_error'] = str(exc)[:500]
        result.append(rec)
    return result

if __name__ == '__main__':
    raise SystemExit('Use semantic_worker.py select <batch> --fetch for just-in-time JD packets')
