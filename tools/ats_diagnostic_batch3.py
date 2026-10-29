"""Bounded public source diagnostics for Dojo / PayPal / Worldline. No auth, no writes."""
from __future__ import annotations
import json
import re
from html.parser import HTMLParser
import html
from urllib.parse import urljoin
import requests

SOURCES={
 "dojo":"https://dojo.careers/jobs",
 "dojo_gh":"https://boards-api.greenhouse.io/v1/boards/dojo/jobs",
 "dojoitaly_gh":"https://boards-api.greenhouse.io/v1/boards/dojoitaly/jobs",
 "paypal":"https://careers.pypl.com/search-results/",
 "paypal_eightfold":"https://paypal.eightfold.ai/careers",
 "worldline":"https://jobs.worldline.com/viewalljobs/",
 "worldline_search":"https://jobs.worldline.com/search/",
}

class Attrs(HTMLParser):
 def __init__(self):
  super().__init__();self.anchors=[];self.buttons=[];self.scripts=[];self.forms=[];self.frames=[];self.data_attrs={};self.tags={};self.islands=[]
 def handle_starttag(self,tag,attrs):
  d=dict(attrs);self.tags[tag]=self.tags.get(tag,0)+1
  if tag=="astro-island":
   self.islands.append({k:d.get(k) for k in ("component-url","component-export","renderer-url","props")})
  if tag=="a":self.anchors.append({k:d.get(k) for k in ("href","class","data-job-id","data-id","aria-label")})
  if tag=="button":self.buttons.append({k:d.get(k) for k in ("type","class","id","data-action","aria-label")})
  if tag=="script":self.scripts.append({k:d.get(k) for k in ("src","id","type")})
  if tag=="form":self.forms.append({k:d.get(k) for k in ("action","method","id")})
  if tag=="iframe":self.frames.append(d.get("src"))

def sample(s,needles,max_n=10):
 out=[]
 for needle in needles:
  pat=re.compile(re.escape(needle),re.I)
  for m in list(pat.finditer(s))[:2]:
   start=max(0,m.start()-125);end=min(len(s),m.end()+190)
   out.append({"needle":needle,"around":re.sub(r"\s+"," ",s[start:end])[:310]})
 return out[:max_n]

def inspect(name,url,session):
 try:
  r=session.get(url,timeout=25,headers={"Accept":"text/html,application/json"})
 except requests.RequestException as e:
  print("DIAG "+json.dumps({"source":name,"error":type(e).__name__,"note":str(e)[:160]}));return
 print("DIAG_HEAD "+json.dumps({"source":name,"status":r.status_code,"url":r.url,"bytes":len(r.content),"type":r.headers.get("Content-Type"),"redirect_count":len(r.history)}))
 try:
  data=r.json()
  if isinstance(data,dict):
   jobs=data.get("jobs")
   print("DIAG_JSON "+json.dumps({
    "source":name,"keys":list(data)[:25],"meta":data.get("meta"),
    "jobs_length":len(jobs) if isinstance(jobs,list) else None,
    "jobs_first":[{k:x.get(k) for k in ("id","title","absolute_url","internal_job_id","location","updated_at")}
     for x in (jobs or [])[:3] if isinstance(x,dict)],
   },default=str,ensure_ascii=False)[:6500])
  else:print("DIAG_JSON "+json.dumps({"source":name,"type":type(data).__name__,"length":len(data)}))
  return
 except (ValueError,TypeError):pass
 parser=Attrs();parser.feed(r.text)
 related=[a for a in parser.anchors if a.get("href") and any(q in a["href"].lower() for q in ("/job/","/jobs/","greenhouse","eightfold","workday","lever","/positions/"))]
 src=[x for x in parser.scripts if x.get("src") and any(k in x["src"].lower() for k in ("job","career","board","candidate","position","career"))]
 if name=="dojo":
  ids=set(re.findall(r'/jobs/(\d{7,12})',r.text))
  print("DOJO_ASTRO "+json.dumps({
   "islands":len(parser.islands),
   "island_meta":[{"component":x.get("component-url"),"props_length":len(x.get("props") or ""),"props_sample":str(x.get("props"))[:380]} for x in parser.islands[:7]],
   "distinct_job_ids_in_html":len(ids),"job_ids_sample":sorted(ids)[:16],
  },ensure_ascii=False)[:6500])
  for island in parser.islands:
   try:
    data=json.loads(html.unescape(island.get("props") or ""))
    print("DOJO_ASTRO_JSON "+json.dumps({
      "component":island.get("component-url"),"keys":list(data),
      "overview":[{"key":key,"type":type(val).__name__,"length":len(val) if isinstance(val,(dict,list,str)) else 0,"head":str(val)[:550]} for key,val in data.items()]
    },ensure_ascii=False)[:4800])
   except ValueError:
    pass
 print("DIAG_HTML "+json.dumps({
  "source":name,"links":len(parser.anchors),"jobs_links":len(related),"job_url_samples":related[:18],
  "forms":parser.forms[:4],"buttons":parser.buttons[:8],"scripts":len(parser.scripts),
  "career_scripts":src[:14],"frames":parser.frames[:4],"tags":parser.tags,
  "hints":sample(r.text,["gh_jid","greenhouse","api.greenhouse","job-board","load-more","loadMore",
   "totalCount","__NEXT_DATA__","apiUrl","apiEndpoint","jobs2web","widget-loader","joblist","__NUXT__", "eightfold","search-results"],16),
 },default=str,ensure_ascii=False)[:11000])

if __name__=="__main__":
 session=requests.Session()
 session.headers["User-Agent"]="job-watch-milano/1.0 (+public ATS contract diagnostic)"
 for name,url in SOURCES.items():inspect(name,url,session)
