"""Bounded PayPal Eightfold PCS-X location filters, sitemap and detail proof.

Source first-party Public Eightfold API /api/pcsx/search, domain=paypal.com.
Robots explicitly Allow: /api/pcsx and /careers. No rate-limit bypass.
"""
import requests,re,json,xml.etree.ElementTree as ET,time
from urllib.parse import urljoin
HOST="https://paypal.eightfold.ai"
API=HOST+"/api/pcsx/search"
PARAMS={"domain":"paypal.com","query":"","start":0,"num":10}
def summary(r):
 try:o=r.json()
 except ValueError:return {"status":r.status_code,"text":r.text[:350]}
 data=o.get("data") if isinstance(o,dict) else None
 if not isinstance(data,dict):return {"status":r.status_code,"data":str(o)[:500]}
 pos=data.get("positions") or []
 return {"status":r.status_code,"count":data.get("count"),"num":len(pos),
   "ids":[x.get("id") for x in pos],"rows":[{"id":x.get("id"),"name":x.get("name"),
      "locations":x.get("locations"),"url":x.get("positionUrl"),"postedTs":x.get("postedTs")}
      for x in pos[:10]]}
def main():
 s=requests.Session();s.headers.update({"User-Agent":"job-watch-milano/public-PayPal-career-inventory-audit","Accept":"application/json"})
 start=0
 for loc in ("Milan","Rome","Italy"):
  try:
   r=s.get(API,params={**PARAMS,"location":loc},timeout=25)
   z=summary(r)
   print("PAYPAL_CITY "+json.dumps({"location":loc,"response":z},ensure_ascii=False)[:13000])
   if loc=="Milan" and z.get("status")==200 and z.get("num"):
    start=z["ids"][0]
  except requests.RequestException as e:print("PAYPAL_CITY_ERROR "+json.dumps({"city":loc,"error":str(e)[:140]}))
  time.sleep(1.0)
 index=HOST+"/careers/sitemap_index.xml?domain=paypal.com"
 try:
  r=s.get(index,timeout=25)
  print("PAYPAL_SITEMAP_INDEX "+json.dumps({"status":r.status_code,"len":len(r.content),
    "head":r.text[:1500]},ensure_ascii=False))
  if r.status_code==200 and "<?xml" in r.text[:100]:
   tree=ET.fromstring(r.text)
   hrefs=[el.text for el in tree.iter() if el.tag.endswith("loc") and el.text]
   print("PAYPAL_SITEMAPS "+json.dumps({"n":len(hrefs),"urls":hrefs[:15]},ensure_ascii=False))
   for link in hrefs[:4]:
    if not link.startswith(HOST+"/"):continue
    rr=s.get(link,timeout=25)
    urls=re.findall(r"<loc>([^<]+)</loc>",rr.text)
    print("PAYPAL_SITEMAP_PAGE "+json.dumps({"url":link,"http":rr.status_code,"n":len(urls),
      "first":urls[:6],"contains_careers_jobs":sum("/careers/job/" in x for x in urls)}))
 except Exception as e:print("PAYPAL_SITEMAP_ERR "+json.dumps({"error":str(e)[:200]}))
 if isinstance(start,int) and start>0:
  detail=HOST+"/api/pcsx/position_details"
  try:
   r=s.get(detail,params={"domain":"paypal.com","position_id":str(start)},timeout=25)
   try:
    j=r.json()
    data=j.get("data") or {}
    row=data.get("position") if isinstance(data,dict) else {}
    print("PAYPAL_DETAILS "+json.dumps({"id":start,"status":r.status_code,"data_keys":list(data)[:35],
      "row_keys":list(row)[:40] if isinstance(row,dict) else [],
      "name":row.get("name") if isinstance(row,dict) else None,
      "location":row.get("locations") if isinstance(row,dict) else None,
      "description_len":len(str(data.get("jobDescription") or "")) if isinstance(data,dict) else 0,
      "message":j.get("message")},ensure_ascii=False))
   except ValueError:print("PAYPAL_DETAIL_HTML "+json.dumps({"status":r.status_code,"html":r.text[:220]}))
  except requests.RequestException as e:print("PAYPAL_DETAIL_ERROR "+json.dumps({"error":str(e)[:140]}))
if __name__=="__main__":main()
