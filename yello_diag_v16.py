#!/usr/bin/env python3
import html as htmlmod
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, parse_qs
import requests

BOARD="https://kearney.recsolu.com/job_boards/1"; TIMEOUT=30; TAB="job-watch-yello-v16-diagnostic"
class BP(HTMLParser):
    def __init__(self): super().__init__(); self.anchors=[]; self.text=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=="a": self.anchors.append(dict(attrs))
    def handle_data(self,data):
        s=" ".join(data.split());
        if s: self.text.append(s)

def req(s,url,params=None,xhr=True):
    h={"User-Agent":"job-watch-milano/yello-diagnostic","Accept":"application/json, text/html, */*"}
    if xhr: h["X-Requested-With"]="XMLHttpRequest"
    r=s.get(url,params=params,timeout=TIMEOUT,headers=h); print("HTTP",r.status_code,len(r.content),r.url,r.headers.get("content-type")); r.raise_for_status(); return r

def strip(v): return " ".join(htmlmod.unescape(re.sub(r"<[^>]+>"," ",v or "")).split())
def cards(fragment,base):
    fragment=htmlmod.unescape(fragment or ""); out=[]
    for b in re.findall(r'<li[^>]*class=["\'][^"\']*search-results__item[^"\']*["\'][^>]*>(.*?)</li>',fragment,re.I|re.S):
        m=re.search(r'<a[^>]*class=["\'][^"\']*search-results__req_title[^"\']*["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',b,re.I|re.S)
        if not m: continue
        u=urljoin(base,htmlmod.unescape(m.group(1))); spans=[strip(x) for x in re.findall(r'<span[^>]*>(.*?)</span>',b,re.I|re.S)]
        out.append({"id":urlparse(u).path.rstrip('/').split('/')[-1],"url":u,"title":strip(m.group(2)),"region":spans[1] if len(spans)>1 else "","location":spans[2] if len(spans)>2 else ""})
    return out

def main():
    s=requests.Session(); r=req(s,BOARD,xhr=False); p=BP(); p.feed(r.text); text=" ".join(p.text)
    total=int(re.search(r"\b([\d,]+)\s+Results\b",text,re.I).group(1).replace(',',''))
    bids=[]
    for a in p.anchors:
        u=urljoin(r.url,a.get('href') or '')
        if '/jobs/' in urlparse(u).path:
            bid=(parse_qs(urlparse(u).query).get('job_board_id') or [None])[0]
            if bid: bids.append(bid)
    bid=sorted(set(bids))[0]; search=f"https://kearney.recsolu.com/job_boards/{bid}/search"; allc=[]
    for page in range(1,51):
        d=req(s,search,{"query":"","filters":"[]","page_number":page,"job_board_tab_identifier":TAB}).json(); pc=cards(d.get('html'),search); allc+=pc
        if not d.get('more_requisitions'): break
    print("RECONCILE",len(allc),len({x['id'] for x in allc}),total)
    missing=[x for x in allc if not x['location']]; print("MISSING",len(missing))
    for x in missing:
        rr=req(s,x['url'],xhr=False); page=strip(rr.text); low=page.casefold(); hits=[]
        for needle in ("office location","location","oslo","norway","manila","philippines","denmark","copenhagen","milan","rome","london"):
            pos=low.find(needle)
            if pos>=0: hits.append(page[max(0,pos-180):pos+420])
        print("DETAIL",x['id'],x['title'],"REGION",x['region'],"HITS",hits[:12])
    r2=req(s,BOARD,xhr=False); p2=BP(); p2.feed(r2.text); m=re.search(r"\b([\d,]+)\s+Results\b"," ".join(p2.text),re.I); print("TOTAL_RECHECK",m.group(1) if m else None)
if __name__=="__main__": main()
