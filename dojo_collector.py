"""Read-only Dojo corporate careers collector via official Greenhouse + Astro board.

Scope: the advertised corporate dojo.careers/jobs board, not the separately
operated dojoitaly self-employed field-sales marketplace. Fail closed if the
first-party initial job batch does not agree with its Greenhouse publisher.
"""
from __future__ import annotations

import html
import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import collector as c

BOARD = "https://dojo.careers/jobs"
GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/dojo/jobs"
DETAIL_PATH = re.compile(r"^/jobs/(\d{7,12})/?$")


class JobsIslandParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.jobs_components = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() != "astro-island":
            return
        values = dict(attrs)
        if re.search(r"/_astro/Jobs\.[^/]+\.js$", values.get("component-url") or ""):
            self.jobs_components.append(values.get("props"))


class H1Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_heading = False
        self.headings = []
        self.current = []
    def handle_starttag(self, tag, attrs):
        if tag.lower()=="h1":
            self.in_heading = True
            self.current = []
    def handle_data(self, data):
        if self.in_heading:
            self.current.append(data)
    def handle_endtag(self, tag):
        if tag.lower()=="h1" and self.in_heading:
            self.headings.append(c.clean_text(" ".join(self.current)))
            self.in_heading = False


def _astro_unwrap(value):
    """Decode Astro's documented serialized [type, payload] wrappers."""
    if isinstance(value, list) and len(value)==2 and value[0]==0:
        return _astro_unwrap(value[1])
    if isinstance(value, list) and len(value)==2 and value[0]==1 and isinstance(value[1],list):
        return [_astro_unwrap(item) for item in value[1]]
    if isinstance(value, dict):
        return {k:_astro_unwrap(v) for k,v in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise c.NotCheckable("Dojo first-party Astro job payload has unsupported structure")


def _id_in_url(url, sid):
    parsed=urlparse(str(url or ""))
    match=DETAIL_PATH.fullmatch(parsed.path)
    if parsed.scheme!="https" or parsed.hostname not in {"dojo.careers","www.dojo.careers"} or not match:
        return False
    if match.group(1)!=str(sid):
        return False
    jid=parse_qs(parsed.query).get("gh_jid")
    return not jid or jid==[str(sid)]


def _corporate_snapshot():
    try:
        body,final_url=c.get_html(BOARD)
    except Exception as exc:
        raise c.NotCheckable("Dojo first-party corporate jobs page unavailable") from exc
    if urlparse(final_url).hostname not in {"dojo.careers","www.dojo.careers"}:
        raise c.NotCheckable("Dojo corporate jobs page redirected off its first-party domain")
    parser=JobsIslandParser()
    parser.feed(body)
    if len(parser.jobs_components)!=1:
        raise c.NotCheckable("Dojo corporate board exposes no unambiguous Astro jobs component")
    try:
        props=json.loads(html.unescape(parser.jobs_components[0]))
        decoded={k:_astro_unwrap(v) for k,v in props.items()}
    except (ValueError,TypeError) as exc:
        raise c.NotCheckable("Dojo Astro jobs payload cannot be decoded") from exc
    initial=decoded.get("jobs")
    size=decoded.get("initialBatchSize")
    offset=decoded.get("initialPageOffset")
    more=decoded.get("hasMoreJobs")
    if not isinstance(initial,list) or not initial or not isinstance(size,int) or not isinstance(offset,int) or offset!=0:
        raise c.NotCheckable("Dojo Astro initial batch pagination contract invalid")
    if len(initial)!=min(size,len(initial)) or size < 1 or size > 100 or not isinstance(more,bool):
        raise c.NotCheckable("Dojo Astro initial batch size invalid")
    if not more and len(initial)!=size:
        # A final short batch may be valid, but its size must not suggest pagination
        pass
    parsed=[]
    for item in initial:
        if not isinstance(item,dict):
            raise c.NotCheckable("Dojo Astro board contains malformed posting")
        sid=c.clean_text(item.get("id"))
        title=c.clean_text(item.get("title"))
        url=item.get("absolute_url")
        if not sid or not title or not _id_in_url(url,sid):
            raise c.NotCheckable("Dojo first-party job lacks stable validated URL/title/ID")
        parsed.append({"id":sid,"title":title,"url":url,"location":c.clean_text(item.get("location"))})
    if len({x["id"] for x in parsed})!=len(parsed):
        raise c.NotCheckable("Dojo initial first-party postings contain duplicate IDs")
    return parsed,size,more


def _greenhouse_snapshot():
    try:
        data=c.get_json(GREENHOUSE)
    except Exception as exc:
        raise c.NotCheckable("Dojo official Greenhouse publisher unavailable") from exc
    if not isinstance(data,dict) or not isinstance(data.get("jobs"),list):
        raise c.NotCheckable("Dojo Greenhouse publisher lacks a job array")
    jobs=data["jobs"]
    try:
        total=int((data.get("meta") or {}).get("total"))
    except (TypeError,ValueError) as exc:
        raise c.NotCheckable("Dojo Greenhouse publisher has no numeric total") from exc
    if total!=len(jobs):
        raise c.NotCheckable(f"Dojo Greenhouse publisher total mismatch: {total}!={len(jobs)}")
    seen=set()
    for item in jobs:
        if not isinstance(item,dict):
            raise c.NotCheckable("Dojo Greenhouse publisher contains malformed requisition")
        sid=c.clean_text(item.get("id"))
        title=c.clean_text(item.get("title"))
        loc=c.clean_text((item.get("location") or {}).get("name")) if isinstance(item.get("location"),dict) else None
        if not sid or not title or not loc or sid in seen or not _id_in_url(item.get("absolute_url"),sid):
            raise c.NotCheckable("Dojo Greenhouse publisher has duplicate/invalid requisition, metadata or URL")
        seen.add(sid)
    return jobs,total


def _check_first_batch(first,limit,has_more,all_jobs,total):
    if len(first)!=min(limit,total) or has_more!=(total>len(first)):
        raise c.NotCheckable("Dojo Astro first-page pagination is inconsistent with complete Greenhouse publisher")
    for f,raw in zip(first,all_jobs[:len(first)]):
        if f["id"]!=str(raw["id"]) or f["title"]!=c.clean_text(raw["title"]) or f["url"]!=raw["absolute_url"]:
            raise c.NotCheckable("Dojo corporate first-party and official Greenhouse ordering/IDs/titles/URLs differ")


def _verify_official_detail(row):
    url=row["absolute_url"]
    sid=str(row["id"])
    try:
        body,final_url=c.get_html(url)
    except Exception as exc:
        raise c.NotCheckable(f"Dojo first-party requisition unavailable: {sid}") from exc
    if not _id_in_url(final_url,sid):
        raise c.NotCheckable(f"Dojo requisition redirected outside official identity: {sid}")
    h=H1Parser()
    h.feed(body)
    if h.headings.count(c.clean_text(row["title"]))!=1:
        raise c.NotCheckable(f"Dojo first-party detail title mismatch for {sid}")
    return url


def collect_dojo(company):
    if company.get("company")!="Dojo":
        raise c.NotCheckable("Dojo collector called for wrong owner")
    first,batch,more=_corporate_snapshot()
    all_jobs,total=_greenhouse_snapshot()
    _check_first_batch(first,batch,more,all_jobs,total)
    found=[]
    for item in all_jobs:
        loc=c.clean_text((item.get("location") or {}).get("name"))
        if not c.location_matches(loc,"Dojo"):
            continue
        url=_verify_official_detail(item)
        department=" | ".join(str(x.get("name")) for x in (item.get("departments") or []) if isinstance(x,dict) and x.get("name")) or None
        found.append(c.compact_job("Dojo",str(item["id"]),title=item["title"],location=loc,
           department=department,updated_at=item.get("updated_at"),canonical=url,apply_url=url))
        time.sleep(0.1)
    later,later_total=_greenhouse_snapshot()
    later_first,later_batch,later_more=_corporate_snapshot()
    _check_first_batch(later_first,later_batch,later_more,later,later_total)
    if total!=later_total or [int(x["id"]) for x in all_jobs]!=[int(x["id"]) for x in later]:
        raise c.NotCheckable("Dojo Greenhouse publisher changed during official job detail verification")
    return {
       "coverage":"VERIFIED",
       "collector":"dojo_corporate_first_party_astro_greenhouse_id_parity_v1",
       "inventory_count":total,
       "source_url":BOARD,
       "jobs":found,
       "reconciliation":{
           "scope":"dojo.careers corporate jobs board, not dojoitaly independent self-employed field-sales board",
           "first_party_initial_batch":len(first),
           "greenhouse_count":total,
           "official_target_details_verified":len(found),
           "stable_two_snapshots":True,
       },
    }
