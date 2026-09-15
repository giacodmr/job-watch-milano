#!/usr/bin/env python3
import html as htmlmod, json, re
from urllib.parse import urljoin, urlparse, parse_qs
import requests
BOARD="https://kearney.recsolu.com/job_boards/1"; BID="EPd41qlA4_03IncZMnWyRQ"; SEARCH=f"https://kearney.recsolu.com/job_boards/{BID}/search"; TAB="job-watch-yello-v16-diagnostic"; TIMEOUT=30
TARGETS={"Milan":19960,"Rome":19946,"London":19071}
def req(s,url,params=None):
 r=s.get(url,params=params,timeout=TIMEOUT,headers={"User-Agent":"job-watch-milano/yello-diagnostic","Accept":"application/json, text/html, */*","X-Requested-With":"XMLHttpRequest"}); print("HTTP",r.status_code,len(r.content),r.url); r.raise_for_status(); return r
def strip(v): return " ".join(htmlmod.unescape(re.sub(r"<[^>]+>"," ",v or "")).split())
def cards(fragment):
 f=htmlmod.unescape(fragment or ""); out=[]
 for b in re.findall(r'<li[^>]*class=["\'][^"\']*search-results__item[^"\']*["\'][^>]*>(.*?)</li>',f,re.I|re.S):
  m=re.search(r'<a[^>]*class=["\'][^"\']*search-results__req_title[^"\']*["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',b,re.I|re.S)
  if not m: continue
  u=urljoin(SEARCH,htmlmod.unescape(m.group(1))); spans=[strip(x) for x in re.findall(r'<span[^>]*>(.*?)</span>',b,re.I|re.S)]
  out.append({"id":urlparse(u).path.rstrip('/').split('/')[-1],"url":u,"title":strip(m.group(2)),"employment":spans[0] if len(spans)>0 else "","region":spans[1] if len(spans)>1 else "","location":spans[2] if len(spans)>2 else ""})
 return out
def enum(s,ids):
 fs=','.join(str(x) for x in ids); allc=[]; first_meta=None
 for page in range(1,21):
  d=req(s,SEARCH,{"query":"","filters":fs,"page_number":page,"job_board_tab_identifier":TAB}).json()
  if first_meta is None: first_meta={k:d.get(k) for k in ("display_count_text","filters","query","text_filters","count_on_page")}
  pc=cards(d.get('html')); print("FILTER_PAGE",fs,page,"rows",len(pc),"more",d.get('more_requisitions'),"display",d.get('display_count_text')); allc.extend(pc)
  if not d.get('more_requisitions'): break
 return first_meta,allc
def main():
 s=requests.Session()
 for label,ids in [(k,[v]) for k,v in TARGETS.items()]+[("combined",list(TARGETS.values()))]:
  meta,c=enum(s,ids); uniq={x['id'] for x in c}; print("RESULT",label,"META",meta,"rows",len(c),"unique",len(uniq),"jobs",[(x['title'],x['location']) for x in c])
  if len(c)!=len(uniq): raise SystemExit("duplicate filtered IDs")
 print("DONE")
if __name__=="__main__": main()
