#!/usr/bin/env python3
import html as htmlmod
import re
from html.parser import HTMLParser
from urllib.parse import urljoin
import requests

BOARD="https://kearney.recsolu.com/job_boards/1"; TIMEOUT=30
class P(HTMLParser):
    def __init__(self): super().__init__(); self.scripts=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag.lower()=="script" and a.get("src"): self.scripts.append(a['src'])

def get(s,url):
    r=s.get(url,timeout=TIMEOUT,headers={"User-Agent":"job-watch-milano/yello-diagnostic"}); print("HTTP",r.status_code,len(r.content),r.url); r.raise_for_status(); return r

def ctx(text,needle,radius=2200):
    i=text.find(needle)
    if i<0: return None
    return re.sub(r"\s+"," ",text[max(0,i-radius):min(len(text),i+len(needle)+radius)])

def main():
    s=requests.Session(); r=get(s,BOARD); p=P(); p.feed(r.text)
    m=re.search(r'<defined-field-answers-filter-container[^>]*data-filter-search-url=["\'][^"\']*/filter_fields/search/603["\'][^>]*field-label=["\']Office Location["\'][^>]*v-bind:filters=["\']([^"\']+)["\']',r.text,re.I|re.S)
    raw=htmlmod.unescape(m.group(1)) if m else ""
    print("OFFICE_LOCATION_BINDING",raw[:10000])
    for city in ("Milan","Rome","London"):
        mm=re.search(r'\{[^{}]*["\']id["\']\s*:\s*(\d+)[^{}]*["\']label["\']\s*:\s*["\']'+re.escape(city)+r'["\'][^{}]*\}',raw,re.I)
        print("CITY_ID",city,mm.group(1) if mm else None)
    scripts=[urljoin(r.url,x) for x in p.scripts]
    for src in scripts:
        if "job_boards" not in src: continue
        js=get(s,src).text
        for needle in ("retrieveFilterIdsFromSessionOrActiveFilters","buildActiveTextFiltersPayload","activeFilters","definedFilters","filters:"):
            c=ctx(js,needle)
            if c: print("JS_CONTEXT",needle,c)
if __name__=="__main__": main()
