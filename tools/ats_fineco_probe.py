"""Read-only Fineco official careers inventory and JS API discovery (no auth)."""
import json,re,requests,html
from html.parser import HTMLParser
from urllib.parse import urljoin,urlparse
URLS=["https://about.finecobank.com/it/careers/diventa-un-dipendente/","https://about.finecobank.com/en/careers/diventa-un-dipendente/"]
TOKENS=["job","vacan","position","career","recruit","requisition","api/","graphql","annunc","posizioni","workday","personio","greenhouse","lever","smartrecruiters","fineco","next_data","json","offerte"]
class Scanner(HTMLParser):
 def __init__(self):
  super().__init__();self.links=[];self.scripts=[];self.ifs=[];self.data=[];self.nodes=[]
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if tag=="a" and d.get("href"):self.links.append(d)
  if tag=="script":self.scripts.append(d)
  if tag=="iframe":self.ifs.append(d)
  if any(re.search(r"job|vacanc|careers|recruit|offer|position",k+"="+str(v),re.I) for k,v in d.items()):
   if tag!="a":self.nodes.append({"tag":tag,"attrs":{k:v for k,v in d.items() if len(str(v))<200}})
def snippets(body,tokens=TOKENS,limit=20):
 res=[]
 for token in tokens:
  hits=list(re.finditer(re.escape(token),body,re.I))
  for m in hits[:2]:
   v=re.sub(r"\s+"," ",body[max(0,m.start()-140):m.end()+250])
   res.append({"word":token,"value":v[:390]})
 return res[:limit]
def get_page(s,url):
 try:r=s.get(url,timeout=28)
 except requests.RequestException as e:
  print("FINECO_ERR "+json.dumps({"url":url,"error":str(e)[:180]}));return [],None
 p=Scanner();p.feed(r.text)
 nextdata=re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',r.text,re.I|re.S)
 nd={}
 if nextdata:
  try:nd=json.loads(nextdata.group(1))
  except ValueError:pass
 js=[urljoin(r.url,z["src"]) for z in p.scripts if z.get("src")]
 print("FINECO_PAGE "+json.dumps({"url":url,"final":r.url,"status":r.status_code,"length":len(r.content),
   "scripts":js[:90],"links":p.links[:65],"links_n":len(p.links),
   "nextProps":list((nd.get("props") or {}).get("pageProps",{}))[:35],
   "nextRoute":nd.get("page"),"nextBuild":nd.get("buildId"),
   "frames":p.ifs[:5],"nodes":p.nodes[:14],"hints":snippets(r.text,limit=36)},ensure_ascii=False)[:17500])
 return js,r
def get_js(s,src):
 try:r=s.get(src,timeout=25)
 except requests.RequestException as e:print("FINECO_JS_ERR "+json.dumps({"url":src,"err":str(e)[:130]}));return
 if r.status_code!=200:return
 matches=snippets(r.text,["jobOffer","jobOpen","vacanc","career","recruit","jobPosition","posizioniAperte","opportunit","/api/","graphql","/wp-json/","application","annunc","Lavora con noi","jobList","searchPositions","jobIds","getJobs","jobs?","career/","position/"],limit=27)
 urls=set(re.findall(r'https?://[a-z0-9.\-_/?:&=%]+',r.text,re.I))
 candidates=[v for v in urls if any(t in v.lower() for t in ["api","job","career","recruit","position","fineco"])]
 config_matches=[]
 for m in list(re.finditer(r"(?<![A-Za-z0-9])3473\s*[,=:]",r.text))[:6]:
  config_matches.append(re.sub(r"\\s+"," ",r.text[max(0,m.start()-220):m.end()+1250])[:1450])
 if config_matches:print("FINECO_CONFIG "+json.dumps({"src":src,"matches":config_matches},ensure_ascii=False)[:9500])
 print("FINECO_JS "+json.dumps({"src":src,"status":r.status_code,"len":len(r.content),
     "snips":matches,"urls":sorted(candidates)[:25]},ensure_ascii=False)[:10000])
def main():
 s=requests.Session();s.headers["User-Agent"]="job-watch-milano/read-only-official-ATS-audit"
 all_js=set()
 for url in URLS:
  js,_=get_page(s,url)
  all_js.update(js)
 likely=[x for x in all_js if ("/_next/static/" in x or "/assets/" in x or "/js/" in x) and not any(y in x for y in ("goog","gtm","cook","consent","analytics","recaptcha"))]
 print("FINECO_JS_COUNT "+json.dumps({"total":len(all_js),"inspect":len(likely)}))
 for src in likely[:60]:get_js(s,src)
 for path in ("/robots.txt","/sitemap.xml"):
  try:r=s.get("https://about.finecobank.com"+path,timeout=20)
  except requests.RequestException:continue
  print("FINECO_INDEX "+json.dumps({"path":path,"status":r.status_code,"len":len(r.content),
    "career_links":re.findall(r"https?://[^<\s]+(?:career|lavora|lavoro)[^<\s]*",r.text,re.I)[:20],
    "snips":snippets(r.text,["job","career","sitemap"],6)},ensure_ascii=False)[:3500])
if __name__=="__main__":main()
