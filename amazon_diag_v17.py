#!/usr/bin/env python3
import json
import requests

API="https://www.amazon.jobs/en/search.json"; TIMEOUT=30
FACETS=["normalized_state_name","normalized_city_name","normalized_location","location"]
def get(s,params):
 r=s.get(API,params=params,timeout=TIMEOUT,headers={"User-Agent":"job-watch-milano/amazon-diagnostic","Accept":"application/json"}); print("HTTP",r.status_code,len(r.content),r.url); r.raise_for_status(); return r.json()
def flat(data,name):
 raw=(data.get("facets") or {}).get(name+"_facet") or []; out={}
 for item in raw:
  if isinstance(item,dict):
   for k,v in item.items():
    try: out[str(k)]=int(v)
    except: pass
 return out
def locs(job):
 out=[]
 for raw in job.get("locations") or []:
  if isinstance(raw,str):
   try: raw=json.loads(raw)
   except: continue
  if isinstance(raw,dict): out.append(raw)
 return out
def main():
 s=requests.Session(); params=[("offset","0"),("result_limit","100"),("sort","recent"),("normalized_country_code[]","USA")]
 for f in FACETS: params.append(("facets[]",f))
 d=get(s,params); print("USA_HITS",d.get("hits"),"ROWS",len(d.get("jobs") or []))
 for f in FACETS:
  vals=flat(d,f); ordered=sorted(vals.items(),key=lambda x:(-x[1],x[0])); print("FACET",f,"COUNT",len(vals),"SUM",sum(vals.values()),"MAX",ordered[:20]);
 # Validate the visible capped 10k in pages and count missing geography in that full visible window.
 seen={}; missing_state=[]; missing_city=[]; missing_country=[]; expected=10000
 for offset in range(0,expected,100):
  data=get(s,[("offset",str(offset)),("result_limit","100"),("sort","recent"),("normalized_country_code[]","USA")])
  rows=data.get("jobs") or []
  if int(data.get("hits") or 0)!=expected: raise SystemExit(f"USA cap changed at {offset}: {data.get('hits')}")
  for job in rows:
   jid=str(job.get("id"));
   if not jid or jid in seen: raise SystemExit(f"duplicate/missing id at {offset}: {jid}")
   seen[jid]=job
   js=locs(job)
   us=[x for x in js if (x.get("normalizedCountryCode") or x.get("countryIso3a"))=="USA"]
   if not us: missing_country.append(jid)
   if us and not any(x.get("normalizedStateName") for x in us): missing_state.append(jid)
   if us and not any(x.get("normalizedCityName") for x in us): missing_city.append(jid)
 print("USA_VISIBLE_10K",{"unique":len(seen),"missing_country":len(missing_country),"missing_state":len(missing_state),"missing_city":len(missing_city),"missing_state_sample":missing_state[:10],"missing_city_sample":missing_city[:10]})
 # Probe the largest state partitions to establish exact counts/pageability.
 states=flat(d,"normalized_state_name")
 for state,count in sorted(states.items(),key=lambda x:-x[1])[:15]:
  x=get(s,[("offset","0"),("result_limit","100"),("sort","recent"),("normalized_country_code[]","USA"),("normalized_state_name[]",state)])
  print("STATE",state,{"facet_count":count,"hits":x.get("hits"),"rows":len(x.get("jobs") or [])})
if __name__=="__main__":main()
