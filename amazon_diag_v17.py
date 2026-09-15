#!/usr/bin/env python3
import gzip
import io
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse
import requests

BASE="https://www.amazon.jobs"
S=requests.Session(); S.headers.update({"User-Agent":"job-watch-milano/amazon-diagnostic","Accept":"*/*"})


def fetch(url):
    r=S.get(url,timeout=45)
    print("FETCH",r.status_code,len(r.content),r.headers.get("content-type"),r.url)
    return r

robots=fetch(BASE+"/robots.txt")
print("ROBOTS_PREVIEW",robots.text[:5000].replace("\n"," | "))
urls=[]
for line in robots.text.splitlines():
    if line.lower().startswith("sitemap:"):
        urls.append(line.split(":",1)[1].strip())
for candidate in (BASE+"/sitemap.xml",BASE+"/sitemap_index.xml",BASE+"/sitemap-index.xml",BASE+"/sitemaps/sitemap.xml"):
    if candidate not in urls: urls.append(candidate)

seen=set(); queue=list(urls); job_urls=set(); xml_docs=0
while queue and len(seen)<100:
    url=queue.pop(0)
    if url in seen: continue
    seen.add(url)
    try:
        r=fetch(url)
    except Exception as exc:
        print("ERR",url,repr(exc)); continue
    if r.status_code!=200: continue
    content=r.content
    if url.endswith(".gz") or "gzip" in (r.headers.get("content-type") or "").lower():
        try: content=gzip.decompress(content)
        except Exception: pass
    text=content.decode("utf-8","replace")
    if "<urlset" not in text and "<sitemapindex" not in text:
        print("NOT_XML_SITEMAP",url,text[:200].replace("\n"," ")); continue
    xml_docs+=1
    locs=re.findall(r"<loc>\s*([^<]+?)\s*</loc>",text,re.I)
    print("SITEMAP",url,"LOCS",len(locs),"INDEX",("<sitemapindex" in text))
    for loc in locs:
        loc=loc.replace("&amp;","&")
        if "/jobs/" in urlparse(loc).path:
            job_urls.add(loc)
        elif any(x in loc.lower() for x in ("sitemap",".xml",".gz")):
            if loc not in seen: queue.append(loc)

ids=set()
for u in job_urls:
    m=re.search(r"/jobs/(\d+)(?:/|$)",urlparse(u).path)
    if m: ids.add(m.group(1))
print("SUMMARY",{"seed_urls":urls,"xml_docs":xml_docs,"job_urls":len(job_urls),"numeric_job_ids":len(ids),"sample":sorted(job_urls)[:10]})
