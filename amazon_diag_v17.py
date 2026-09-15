#!/usr/bin/env python3
import requests

API="https://www.amazon.jobs/en/search.json"
S=requests.Session(); S.headers.update({"User-Agent":"job-watch-milano/amazon-diagnostic","Accept":"application/json"})
CATEGORY="Operations, IT, & Support Engineering"

for limit in (100,101,125,150,175,200,225,249,250):
    r=S.get(API,params=[("offset","0"),("result_limit",str(limit)),("sort","recent"),("category[]",CATEGORY)],timeout=45)
    ctype=(r.headers.get("content-type") or "").casefold()
    try:
        d=r.json() if "json" in ctype else {}
    except Exception:
        d={}
    print("LIMIT",limit,{"http":r.status_code,"ctype":ctype,"bytes":len(r.content),"hits":d.get("hits"),"rows":len(d.get("jobs") or []),"error":d.get("error")})
