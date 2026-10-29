"""Read-only first-party Worldline SuccessFactors legacy public job endpoint parity.

This endpoint is discovered in j2w.searchManager JS from jobs.worldline.com.
The 65 legacy /viewalljobs/ count and returned endpoint total may differ;
report that discrepancy openly and do not label VERIFIED without proof.
"""
import requests,json,re,html
from urllib.parse import quote
ROOT="https://jobs.worldline.com"
ENDPOINT=ROOT+"/services/recruiting/v1/jobs"
PAYLOAD={"keywords":"","locale":"en_US","location":"","pageNumber":0,"sortBy":"recent"}
def get_json(s,page):
 d={**PAYLOAD,"pageNumber":page}
 r=s.post(ENDPOINT,json=d,timeout=30);r.raise_for_status();o=r.json()
 if not isinstance(o,dict) or not isinstance(o.get("jobSearchResult"),list):raise RuntimeError("Unrecognized Worldline recruiting response")
 n=o.get("totalJobs")
 if not isinstance(n,int) or not 0<n<=3000:raise RuntimeError("Invalid Worldline totalJobs")
 return n,o["jobSearchResult"]
def official_link(row):
 s=row.get("response") or {}
 slug=html.unescape(str(s.get("unifiedUrlTitle") or "untitled")).replace(" ","-")
 sid=str(s.get("id") or "")
 return ROOT+"/job/"+quote(slug,safe="-")+"/"+quote(sid,safe="")+"-en_US"
def main():
 s=requests.Session()
 s.headers.update({"User-Agent":"Mozilla/5.0 (compatible; JobWatch-public-Ats-audit)","Origin":ROOT,"Referer":ROOT+"/search/?unified=legacy"})
 s.get(ROOT+"/search/?unified=legacy",timeout=20)
 first=None;result=[];totals=set();last_ids=[]
 for i in range(300):
  n,rows=get_json(s,i)
  totals.add(n)
  if first is None:first=n
  if len(totals)!=1:raise RuntimeError("Worldline API total drift")
  if not rows:break
  result.extend(rows)
  if i in (0,1,2,10,20):print("WORLDLINE_PAGE "+json.dumps({"index":i,"count":len(rows),"totalJobs":n,"first":[r.get("response") for r in rows[:1]]},ensure_ascii=False)[:1700])
 else:raise RuntimeError("Exceeded max pages")
 ids=[str((row.get("response") or {}).get("id") or "") for row in result]
 print("WORLDLINE_SCAN "+json.dumps({"pages":i,"total":first,"records":len(ids),"unique":len(set(ids)),
    "missing_ids":sum(not x for x in ids),"first_ids":ids[:12],"last_ids":ids[-12:]},ensure_ascii=False))
 candidates=[]
 for row in result:
  info=row.get("response") or {}
  loc=info.get("jobLocationShort") or []
  if any(re.search(r"(?:Italy|Italia)[-\s,]*(?:Milan|Milano|Rome|Roma)|(?:Milan|Milano|Rome|Roma)",str(q),re.I) for q in loc):
   candidates.append({"id":info.get("id"),"title":info.get("unifiedStandardTitle"),
     "locations":loc,"seniority":info.get("filter6"),"family":info.get("custJobFamily"),"url":official_link(row)})
 print("WORLDLINE_CANDIDATES "+json.dumps({"n":len(candidates),"items":candidates},ensure_ascii=False)[:18000])
 selected=(candidates[:10]+[{"id":(row.get("response") or {}).get("id"),
       "title":(row.get("response") or {}).get("unifiedStandardTitle"),"url":official_link(row)}
       for row in result[:2]])
 for v in selected:
  try:
   rr=s.get(v["url"],timeout=20)
   title=re.search(r"<title[^>]*>(.*?)</title>",rr.text,re.I|re.S)
   jobid=str(v["id"])
   print("WORLDLINE_DETAIL "+json.dumps({"id":jobid,"title":v["title"],"url":v["url"],
     "status":rr.status_code,"final_url":rr.url,"page_title":html.unescape(re.sub("<.*?>","",title.group(1))).strip()[:140] if title else "",
     "id_in_html":jobid in rr.text,"size":len(rr.content)},ensure_ascii=False))
  except requests.RequestException as e:print("WORLDLINE_DETAIL_ERR "+json.dumps({"id":v["id"],"error":str(e)[:130]}))
 if result:
  n,last=get_json(s,0)
  now=[str((x.get("response") or {}).get("id")) for x in last]
  print("WORLDLINE_RECHECK "+json.dumps({"same_total":n==first,"first_page_same_ids":now==ids[:len(last)],"page_size":len(last)}))
if __name__=="__main__":main()
