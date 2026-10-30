"""PayPal Eightfold: Italian published inventory vs official sitemap ID parity.

Eightfold site robots explicitly allow /api/pcsx and /careers.
Check complete Italy 4/4 and Milan/Rome rows, job ID/URL/detail proof,
and official sitemap entries that might reveal geo omissions.
"""
import requests,re,json,xml.etree.ElementTree as ET,time
from urllib.parse import urlparse
ORIGIN="https://paypal.eightfold.ai"
ENDPOINT=ORIGIN+"/api/pcsx/search"
SITEMAP=ORIGIN+"/careers/sitemap.xml?domain=paypal.com"
def get(s,city):
 r=s.get(ENDPOINT,params={"domain":"paypal.com","query":"","location":city,"start":0,"num":10},timeout=28)
 r.raise_for_status();o=r.json();d=o.get("data")
 if not isinstance(d,dict) or not isinstance(d.get("positions"),list) or not isinstance(d.get("count"),int):raise RuntimeError("Invalid PCS-X payload")
 return d
def main():
 s=requests.Session();s.headers.update({"User-Agent":"job-watch-milano/official-PayPal-Eightfold-geo-parity","Accept":"application/json,text/xml;q=0.8"})
 snapshots={}
 for run in range(2):
  for city in ["Italy","Milan","Rome"]:
   d=get(s,city)
   rows=d["positions"];ids=[str(r.get("id")) for r in rows]
   if len(rows)!=d["count"] or len(set(ids))!=len(ids):raise RuntimeError("Expected complete geo result set not exposed")
   snapshots[(run,city)]=set(ids)
   print("PAYPAL_GEO "+json.dumps({"run":run,"city":city,"total":d["count"],"ids":ids,
     "roles":[{"id":r.get("id"),"name":r.get("name"),"locations":r.get("locations"),"url":r.get("positionUrl")} for r in rows]},ensure_ascii=False)[:12000])
   if run==0 and city=="Italy":italy_rows=rows
   time.sleep(0.5)
 if snapshots[(0,"Italy")]!=snapshots[(1,"Italy")]:raise RuntimeError("Italy first-party scope drift")
 if snapshots[(0,"Milan")]!=snapshots[(1,"Milan")] or snapshots[(0,"Rome")]!=snapshots[(1,"Rome")]:raise RuntimeError("City first-party scope drift")
 if snapshots[(0,"Italy")]!=snapshots[(0,"Milan")] | snapshots[(0,"Rome")]:raise RuntimeError("Italy postings not covered by Milan/Rome filters")
 r=s.get(SITEMAP,timeout=30);r.raise_for_status()
 root=ET.fromstring(r.text)
 urls=[e.text for e in root.iter() if e.tag.endswith("loc") and e.text and "/careers/job/" in e.text]
 italy=[]
 for u in urls:
  p=urlparse(u); m=re.search(r"/careers/job/(\d+)",p.path)
  if not m:continue
  if re.search(r"(?:^|[-_/])(?:italy|milan|milano|rome|roma)(?:[-_/]|$)",p.path,re.I):
   italy.append({"id":m.group(1),"url":u})
 print("PAYPAL_SITEMAP_GEO "+json.dumps({"total_urls":len(urls),"geo_slugs":italy,
  "geo_sitemap_ids_not_in_active_italy":sorted({r["id"] for r in italy}-snapshots[(0,"Italy")]),
  "active_italy_ids_not_in_sitemap":sorted(snapshots[(0,"Italy")]-{r["id"] for r in italy})},ensure_ascii=False)[:14000])
 for row in italy_rows:
  sid=str(row["id"]);u=ORIGIN+"/api/pcsx/position_details"
  rr=s.get(u,params={"domain":"paypal.com","position_id":sid},timeout=28)
  if rr.status_code!=200:raise RuntimeError(f"PayPal official detail unavailable for {sid}: {rr.status_code}")
  obj=rr.json();d=obj.get("data")
  if not isinstance(d,dict):raise RuntimeError("No detail data")
  print("PAYPAL_GEO_DETAIL "+json.dumps({"id":sid,"detail_id":d.get("id"),
    "name":d.get("name"),"locations":d.get("locations"),
    "positionUrl":d.get("positionUrl"),"publicUrl":d.get("publicUrl"),
    "description_len":len(str(d.get("jobDescription") or "")),
    "status":rr.status_code},ensure_ascii=False)[:3500])
  time.sleep(0.5)
if __name__=="__main__":main()
