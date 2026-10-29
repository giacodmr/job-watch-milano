"""Read-only bounded evidence gathering on candidate first-party public ATS endpoints."""
import requests, re, json, html
from urllib.parse import urljoin, urlparse
from html.parser import HTMLParser

PAGES={
 "checkout":"https://www.checkout.com/jobs",
 "checkout_careers":"https://www.checkout.com/careers",
 "unicredit":"https://careers.unicredit.eu/en_GB/jobsuche/SearchJobs/",
 "fineco":"https://about.finecobank.com/it/careers/diventa-un-dipendente/",
 "fineco_careers":"https://about.finecobank.com/it/careers/",
 "checkout_ashby":"https://api.ashbyhq.com/posting-api/job-board/checkout.com",
 "unicredit_bigpage":"https://careers.unicredit.eu/en_GB/jobsuche/SearchJobs/?jobRecordsPerPage=1000",
 "unicredit_page2":"https://careers.unicredit.eu/en_GB/jobsuche/SearchJobs/?jobRecordsPerPage=15&jobOffset=15",
 "nexi_italy":"https://fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/requisitions?location=Italy&locationId=300000000462006&locationLevel=country&mode=location",
}
HINTS=("__NEXT_DATA__","__NUXT__","__PRELOADED_STATE__","__APOLLO_STATE__","jobPosting","job-board","jobs","jobCount","pagination","job-list","apiEndpoint","workday","greenhouse","eightfold","job-boards","SuccessFactors","requisition","apply","talentlink","jobRecordsPerPage")
class P(HTMLParser):
 def __init__(self):
  super().__init__();self.links=[];self.scripts=[];self.forms=[];self.frames=[];self.counts={};self.title=[];self.h1=[];self.capture=None
 def handle_starttag(self,t,a):
  d=dict(a);self.counts[t]=self.counts.get(t,0)+1
  if t=="a":self.links.append({k:d.get(k) for k in ("href","class","data-id","data-testid","title")})
  if t=="script":self.scripts.append({k:d.get(k) for k in ("src","id","type")})
  if t=="form":self.forms.append({k:d.get(k) for k in ("action","method","id")})
  if t=="iframe":self.frames.append(d.get("src"))
  if t in ("title","h1"):self.capture=t
 def handle_data(self,s):
  if self.capture=="h1":self.h1.append(s)
  if self.capture=="title":self.title.append(s)
 def handle_endtag(self,t):
  if t==self.capture:self.capture=None

def excerpts(body, terms, max_n=12):
 out=[]
 for term in terms:
  count=0
  for m in re.finditer(re.escape(term),body,re.I):
   out.append({"term":term,"sample":re.sub(r"\s+"," ",body[max(0,m.start()-110):m.end()+185])[:350]})
   count+=1
   if count>=2 or len(out)>=max_n:break
  if len(out)>=max_n:break
 return out

def main():
 ses=requests.Session()
 ses.headers.update({"User-Agent":"job-watch-milano/ATS-public-inventory-audit", "Accept":"text/html,application/xhtml+xml,application/json"})
 for name,url in PAGES.items():
  try:r=ses.get(url,timeout=22)
  except requests.RequestException as e:
   print("DIAG_ERR "+json.dumps({"name":name,"error":type(e).__name__,"message":str(e)[:160]}));continue
  if "ashby" in name:
   try:
    data=r.json();lst=data.get("jobs") or []
    print("ASHBY "+json.dumps({"name":name,"keys":list(data),"total":len(lst),
      "first":[{k:i.get(k) for k in ("id","title","location","department","jobUrl","applyUrl","isListed")}
       for i in lst[:3]],"target":[{k:i.get(k) for k in ("id","title","location","department","jobUrl","isListed")} 
       for i in lst if "milan" in str(i.get("location")).lower() or "rome" in str(i.get("location")).lower() or "london" in str(i.get("location")).lower()][:15]},ensure_ascii=False,default=str)[:14000])
   except (ValueError,TypeError) as exc:print("ASHBY_ERR "+str(exc)[:100])
   continue
  p=P();p.feed(r.text)
  related=[a for a in p.links if a.get("href") and any(term in a["href"].lower() for term in ("job","careers","position","vacan","requisition","openings","workday","recruit"))]
  ext=[x for x in p.scripts if x.get("src") and any(t in str(x["src"]).lower() for t in ("job","recruit","search","career","workday","ats","api"))]
  print("DIAG "+json.dumps({
   "name":name,"status":r.status_code,"final_url":r.url,"bytes":len(r.content),"redirects":len(r.history),
   "title":" ".join(p.title)[:140],"h1":" ".join(p.h1)[:160],
   "counts":p.counts,"links":len(p.links),"job_links":related[:18],"job_link_count":len(related),
   "scripts":len(p.scripts),"notable_scripts":ext[:20],
   "forms":p.forms[:6],"frames":p.frames[:4],
   "regex_counts":{term:len(re.findall(re.escape(term),r.text,re.I)) for term in ("__NEXT_DATA__","/job/","/jobs/","jobs/","position/","job-posting","jobPosting","JobPosting","jobId","requisitionId","jobTitle","jobRecordsPerPage")},
   "samples":excerpts(r.text,HINTS,16),
  },ensure_ascii=False)[:15500])
  if name.startswith("unicredit"):
   # Show real same-host job detail URL, pagination links, and any advertised count.
   jobs=[x for x in p.links if x.get("href") and re.search(r"jobId=|/jobsuche/Jobs|/jobsuche/Job|/jobsuche/ViewJob",x["href"],re.I)]
   pages=[x for x in p.links if x.get("href") and "jobOffset=" in x["href"]]
   print("UNICREDIT_CONTRACT "+json.dumps({
    "name":name,"detail_links":len(jobs),"detail_samples":jobs[:18],
    "pagination_count":len(pages),"pagination_samples":pages[:12],
    "jobId_unique":sorted(set(re.findall(r"jobId=(\d{4,})",r.text,re.I)))[:18],
    "count_fragments":excerpts(r.text,("Total Jobs","Total Results","Showing","Total","Results","totalJobs","totalRecords","Search results","jobOffset","jobRecordsPerPage"),18),
   },ensure_ascii=False)[:14000])
  if name.startswith("fineco"):
    m=re.search(r'<script[^>]*__NEXT_DATA__[^>]*>(.*?)</script>',r.text,re.I|re.S)
   if m:
    try:
     data=json.loads(m.group(1));pp=data.get("props",{}).get("pageProps",{})
     print("FINECO_NEXT "+json.dumps({"name":name,"pp_keys":list(pp),"keys":{k:{"type":type(v).__name__,"len":len(v) if isinstance(v,(dict,list,str)) else None,"sample":str(v)[:500]} for k,v in pp.items() if k!="_nextI18Next"}},ensure_ascii=False)[:13000])
    except ValueError as e:print("FINECO_PARSE_ERR "+str(e))
  if name=="checkout":
   m=re.search(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',r.text,re.I|re.S)
   if m:
    try:
     obj=json.loads(m.group(1));props=obj.get("props",{}).get("pageProps",{})
     print("CHECKOUT_NEXT "+json.dumps({"pageProps_keys":list(props),"buildId":obj.get("buildId"),"samples":str(props)[:1500]},ensure_ascii=False))
    except ValueError:pass
if __name__=="__main__":main()
