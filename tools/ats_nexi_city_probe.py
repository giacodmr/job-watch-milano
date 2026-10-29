"""Read-only Nexi Oracle Candidate Experience cross-check for country-only Italy.

Global board has 85 complete IDs. The four Italian country-only job cards
need official per-ID details before any geographic certification. Probe the
public, documented CE detail REST resource without authentication/bypass.
"""
import html,json,re,requests
from urllib.parse import urlparse
import collector as c
HOST="fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com"
SITE="CX_1"
BASE="https://"+HOST
DETAIL=BASE+"/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
SHELL=BASE+"/hcmUI/CandidateExperience/en/sites/"+SITE+"/job/"

def filtered(raw):
    keys=[k for k in raw if re.search(r'locat|cit(y|ies)|region|country|town|address|requisition|title|description|organization|workplace|worksite|latitude|longitude',k,re.I)]
    out={}
    for k in keys:
        value=raw.get(k)
        if re.search(r'description|responsib|qualification',k,re.I):
            if isinstance(value,str):
                out[k]={"length":len(value),"mentions_city":list(dict.fromkeys(re.findall(r"\b(?:Milano|Milan|Roma|Rome|Napoli|Turin|Torino|Trento|Italy|Italia)\b",c.html_to_text(value) or "",re.I)))[:15]}
            continue
        text=json.dumps(value,ensure_ascii=False,default=str)
        out[k]=value if len(text)<1400 else str(value)[:400]+"…"
    return out

def main():
    rows=[];seen=set();offset=0;total=None
    for page in range(10):
        response,_=c.oracle_get_page(HOST,SITE,offset)
        root=c.oracle_extract_root(response)
        recs=root.get("requisitionList")
        if not isinstance(recs,list):raise RuntimeError("Oracle missing requisitionList")
        total=int(root.get("TotalJobsCount"))
        for row in recs:
            sid=c.oracle_source_id(row)
            if sid in seen:raise RuntimeError("Oracle duplicate requisition "+str(sid))
            seen.add(sid);rows.append(row)
        if len(rows)>=total:break
        if not recs:raise RuntimeError("Oracle stopped early")
        offset+=len(recs)
    if total!=len(rows) or total!=len(seen):raise RuntimeError("Oracle global ID count mismatch")
    italy=[r for r in rows if
        (str(r.get("PrimaryLocationCountry") or "").lower() in {"it","italy","italia"} or
         str(r.get("PrimaryLocation") or "").lower() in {"italy","italia"}) and
         not c.location_matches(c.oracle_location(r),"Nexi")]
    print("NEXI_GLOBAL "+json.dumps({"total":total,"unique":len(seen),"italy_country_only":len(italy),
      "rows":[{"id":c.oracle_source_id(r),"title":r.get("Title"),
               "primary":r.get("PrimaryLocation"),"country":r.get("PrimaryLocationCountry"),
               "location":c.oracle_location(r),
               "other_keys":[k for k in r if re.search("locat|cit|region|town|country|workplace",k,re.I)]}
               for r in italy]},ensure_ascii=False)[:10500])
    sess=requests.Session();sess.headers.update({
      "User-Agent":"job-watch-milano/public-official-Oracle-CX-location-probe",
      "Accept":"application/vnd.oracle.adf.resourcecollection+json, application/json",
      "Ora-Irc-Language":"en", "REST-Framework-Version":"1"})
    for raw in italy:
        sid=str(c.oracle_source_id(raw))
        details_url=SHELL+sid
        try:
            rr=sess.get(details_url,timeout=22)
            print("NEXI_SHELL "+json.dumps({"id":sid,"status":rr.status_code,"final_url":rr.url,
              "bytes":len(rr.content),"host":urlparse(rr.url).hostname,
              "hints":list(dict.fromkeys(re.findall(r"(?i)(?:milano|milan|roma|rome|italy|italia|(?:data-apibaseurl))",rr.text)))[:12]},ensure_ascii=False))
        except requests.RequestException as e:
            print("NEXI_SHELL_ERR "+json.dumps({"id":sid,"error":type(e).__name__,"message":str(e)[:120]}))
        for finder in [f'ById;Id="{sid}",siteNumber={SITE}',f'ById;Id={sid},siteNumber={SITE}']:
            try:
                r=sess.get(DETAIL,params={"finder":finder,"onlyData":"true","expand":"secondaryLocations,otherWorkLocations"},timeout=28)
                try: data=r.json()
                except ValueError:data={}
                items=data.get("items") if isinstance(data,dict) else None
                print("NEXI_DETAIL "+json.dumps({"id":sid,"finder":finder,"status":r.status_code,"url":r.url,
                 "count":len(items) if isinstance(items,list) else None,"response_keys":list(data)[:20] if isinstance(data,dict) else [],
                 "error":str(data.get("title") or data.get("detail") or "")[:400] if isinstance(data,dict) and not items else "",
                 "first":filtered(items[0]) if isinstance(items,list) and items else None},ensure_ascii=False,default=str)[:13000])
                if isinstance(items,list) and items:break
            except requests.RequestException as e:
                print("NEXI_DETAIL_ERR "+json.dumps({"id":sid,"finder":finder,"error":str(e)[:180]}))
if __name__=="__main__":main()
