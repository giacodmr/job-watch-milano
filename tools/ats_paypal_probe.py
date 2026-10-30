"""Read-only anonymous PayPal Eightfold PCS-X careers source probe.

No account, no application, no paid API. Do not bypass rate-limiting,
access refusals or site policy. Official career link and tenant public feed.
"""
import json,requests,re
TENANT="https://paypal.eightfold.ai"
PAGE=TENANT+"/careers"
DOMAIN="paypal.com"
API=TENANT+"/api/pcsx/search"
LEGACY=TENANT+"/api/apply/v2/jobs"
def summarize(obj):
 if not isinstance(obj,dict):return {"type":type(obj).__name__}
 d=obj.get("data")
 o=d if isinstance(d,dict) else obj
 rows=o.get("positions") or o.get("jobs") or []
 return {"top_keys":list(obj)[:25],"data_keys":list(o)[:30],"count":o.get("count"),"total":o.get("total"),
   "rows":len(rows) if isinstance(rows,list) else None,
   "sample":[{k:(str(v)[:180] if isinstance(v,str) else v) for k,v in row.items()
       if k in ("id","name","positionId","title","locations","location","department",
         "displayJobId","display_job_id","postedTs","positionUrl","workLocationOption")}
        for row in rows[:6] if isinstance(row,dict)]}
def main():
 s=requests.Session();s.headers.update({"User-Agent":"job-watch-milano/public-Eightfold-ATS-audit","Accept":"application/json,text/html;q=0.8"})
 for url in (TENANT+"/robots.txt", PAGE, "https://careers.pypl.com/search-results/"):
  try:r=s.get(url,timeout=22);print("PAYPAL_PAGE "+json.dumps({"url":url,"status":r.status_code,"final":r.url,"length":len(r.content),
      "robots":r.text[:2200] if "robots.txt" in url else None,
      "domain_count":len(re.findall("paypal.com",r.text,re.I)),
      "pcsx_mentions":len(re.findall("pcsx",r.text,re.I))},ensure_ascii=False))
  except requests.RequestException as e:print("PAYPAL_PAGE_ERROR "+json.dumps({"url":url,"error":str(e)[:170]}))
 for endpoint in (API,LEGACY):
  params={"domain":DOMAIN,"query":"","location":"","start":0,"num":10} if endpoint==API else {"domain":DOMAIN,"start":0,"num":10}
  try:
   r=s.get(endpoint,params=params,timeout=28)
   try:j=r.json()
   except ValueError:j=None
   print("PAYPAL_API "+json.dumps({"url":r.url,"status":r.status_code,"bytes":len(r.content),
       "content_type":r.headers.get("Content-Type"),"payload":summarize(j) if j is not None else r.text[:240],
       "message":j.get("message") if isinstance(j,dict) else None},ensure_ascii=False,default=str)[:12000])
   if endpoint==API and r.status_code==200:
    break
   if endpoint==API and r.status_code==403 and isinstance(j,dict) and "not enabled" not in str(j.get("message","")).casefold():
    print("PAYPAL_ACCESS_REFUSED: no legacy fallback attempted");break
  except requests.RequestException as e:print("PAYPAL_API_ERROR "+json.dumps({"endpoint":endpoint,"error":str(e)[:190]}))
if __name__=="__main__":main()
