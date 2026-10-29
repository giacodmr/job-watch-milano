"""Public, read-only Worldline SuccessFactors HTML/JS contract discovery."""
import requests,re,json,html
from html.parser import HTMLParser
from urllib.parse import urljoin,urlparse
URLS=[
 "https://jobs.worldline.com/viewalljobs/",
 "https://jobs.worldline.com/viewalljobs/50/",
 "https://jobs.worldline.com/search/",
 "https://jobs.worldline.com/search/?q=&sortColumn=referencedate&sortDirection=desc",
]
KEYWORDS=("jobId","joblist","jobList","requisition","jobTitle","jobs-list","widget-loader","apiURL","apiUrl","api2.successfactors","jobResults","searchResults","searchJobs","jobData","jobCard","job-row","jobPosting","searchajax","searchjobs")
class Parts(HTMLParser):
 def __init__(self):
  super().__init__();self.scripts=[];self.links=[];self.iframes=[];self.divs=[];self.inputs=[]
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if tag=="script":self.scripts.append(d)
  if tag=="a" and d.get("href"):self.links.append(d)
  if tag=="iframe":self.iframes.append(d)
  if tag=="div" and any(z in str(d).lower() for z in ("job","list","result","search")):self.divs.append(d)
  if tag=="input" and any(z in str(d).lower() for z in ("job","search","result")):self.inputs.append(d)
def terms(s,needles=KEYWORDS,lim=22):
 results=[]
 for needle in needles:
  m=re.search(re.escape(needle),s,re.I)
  if m:results.append({"keyword":needle,"snippet":re.sub(r"\s+"," ",s[max(0,m.start()-180):m.end()+320])[:550]})
 return results[:lim]
def main():
 sess=requests.Session();sess.headers["User-Agent"]="job-watch-milano/ATS-public-contract-audit"
 assets=set()
 for u in URLS:
  try:r=sess.get(u,timeout=25)
  except requests.RequestException as e:print("WORLDLINE_PAGE_ERR "+json.dumps({"url":u,"reason":str(e)[:160]}));continue
  p=Parts();p.feed(r.text)
  jobs=[l for l in p.links if re.search(r"/job/|jobId|jobs2web|/career",l["href"],re.I)]
  print("WORLDLINE_PAGE "+json.dumps({"url":u,"status":r.status_code,"final_url":r.url,"size":len(r.content),
     "a_total":len(p.links),"job_link_count":len(jobs),"job_links":jobs[:12],
     "scripts":p.scripts[:35],"ifrs":p.iframes[:4],"job_div":p.divs[:18],"inputs":p.inputs[:8],
     "samples":terms(r.text)},ensure_ascii=False)[:18500])
  for v in p.scripts:
   src=v.get("src")
   if src and not any(z in src for z in ("google","gtm","facebook","cookie","consent","linkedin","adobe","akamai")):assets.add(urljoin(r.url,src))
 for u in list(assets)[:20]:
  try:r=sess.get(u,timeout=22)
  except requests.RequestException as e:
   print("WORLDLINE_JS_ERR "+json.dumps({"url":u,"reason":str(e)[:130]}));continue
  print("WORLDLINE_JS "+json.dumps({"url":u,"status":r.status_code,"size":len(r.content),
   "snippets":terms(r.text,("vmod","widget","career","joblist","searchJobs","jobRequisition","jobId","jobUrl","apiURL","api2.successfactors","searchajax","jobs2web","/job/","recruiting","jobSearch","rest/v1","/api/"))},ensure_ascii=False)[:11500])

def api_test():
 sess=requests.Session()
 sess.headers.update({"User-Agent":"Mozilla/5.0 (compatible; public-ATS-validation)", "Referer":"https://jobs.worldline.com/search/?unified=legacy","Origin":"https://jobs.worldline.com"})
 sess.get("https://jobs.worldline.com/search/?unified=legacy",timeout=25)
 endpoint="https://jobs.worldline.com/services/recruiting/v1/jobs"
 data=[
  {"keywords":"","locale":"en_US","location":"","pageNumber":0,"sortBy":"recent"},
  {"keywords":"","locale":"en_US","location":"","pageNumber":1,"sortBy":"recent"},
  {"keywords":"","locale":"en_US","location":"","pageNumber":2,"sortBy":"recent"},
 ]
 for payload in data:
  try:
   r=sess.post(endpoint,json=payload,timeout=25)
   try:
    o=r.json()
    preview={k:v for k,v in o.items() if k!="jobSearchResult"} if isinstance(o,dict) else o
    jobs=o.get("jobSearchResult") if isinstance(o,dict) else []
    if isinstance(jobs,list):
     preview["job_count"]=len(jobs)
     preview["first_job"]=jobs[:3]
   except ValueError:
    preview=r.text[:900]
   print("WORLDLINE_API "+json.dumps({"request":payload,"status":r.status_code,"url":r.url,"size":len(r.content),
    "result":preview},ensure_ascii=False,default=str)[:11500])
  except requests.RequestException as e:print("WORLDLINE_API_ERR "+json.dumps({"request":payload,"error":str(e)[:200]}))
if __name__=="__main__":
 main()
 api_test()

