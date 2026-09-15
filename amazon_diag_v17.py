#!/usr/bin/env python3
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin
import requests

SEARCH="https://www.amazon.jobs/en/search"; API="https://www.amazon.jobs/en/search.json"; TIMEOUT=30
class P(HTMLParser):
    def __init__(self): super().__init__(); self.scripts=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag.lower()=="script" and a.get("src"): self.scripts.append(a["src"])
def get(s,url,params=None,accept="*/*"):
    r=s.get(url,params=params,timeout=TIMEOUT,headers={"User-Agent":"job-watch-milano/amazon-diagnostic","Accept":accept}); print("HTTP",r.status_code,len(r.content),r.url,r.headers.get("content-type")); r.raise_for_status(); return r
def contexts(label,text,needles,radius=650,limit=80):
    low=text.lower(); seen=set(); n=0
    for needle in needles:
        start=0
        while True:
            i=low.find(needle.lower(),start)
            if i<0: break
            sn=re.sub(r"\s+"," ",text[max(0,i-radius):min(len(text),i+len(needle)+radius)])
            if sn not in seen:
                seen.add(sn); print(label,needle,sn); n+=1
                if n>=limit:return
            start=i+len(needle)
def summary(tag,data):
    print(tag,"HITS",data.get("hits"),"JOBS",len(data.get("jobs") or []),"ERROR",data.get("error"))
    print(tag,"REQUEST",json.dumps(data.get("job_posting_search_request"),ensure_ascii=False,sort_keys=True)[:6000])
    facets=data.get("facets")
    print(tag,"FACETS_TYPE",type(facets).__name__)
    print(tag,"FACETS",json.dumps(facets,ensure_ascii=False)[:12000])
    jobs=data.get("jobs") or []
    print(tag,"JOB_SAMPLE",[(x.get("id"),x.get("city"),x.get("state"),x.get("country_code"),x.get("location"),x.get("normalized_location")) for x in jobs[:5]])
def main():
    s=requests.Session(); page=get(s,SEARCH,accept="text/html,application/xhtml+xml"); p=P(); p.feed(page.text)
    scripts=[urljoin(page.url,x) for x in p.scripts]; print("SCRIPTS",scripts)
    for src in scripts:
        if "/bundles/search/" not in src: continue
        js=get(s,src).text
        contexts("JS",js,["search.json","result_limit","offset","base_query","loc_query","country","city","state","radius","latitude","longitude","facets","normalized_location","job_category","business_category"],radius=900,limit=120)
    base=get(s,API,{"offset":0,"result_limit":10},"application/json").json(); summary("BASE",base)
    probes=[
      ("COUNTRY_ITA",[("country[]","ITA")]),("COUNTRY_GBR",[("country[]","GBR")]),
      ("CITY_MILAN",[("city[]","Milan")]),("CITY_ROME",[("city[]","Rome")]),("CITY_LONDON",[("city[]","London")]),
      ("CITY_MILANO",[("city[]","Milano")]),("LOC_MILAN",[("location[]","Milan")]),
      ("NORM_MILAN",[("normalized_location[]","Milan, Italy")]),
      ("LATLON_MILAN",[("latitude","45.4642"),("longitude","9.1900"),("radius","24km")]),
    ]
    for tag,pairs in probes:
        params=[("offset","0"),("result_limit","10")]+pairs
        try: d=get(s,API,params,"application/json").json(); summary(tag,d)
        except Exception as e: print(tag,"ERROR",type(e).__name__,str(e))
if __name__=="__main__":main()
