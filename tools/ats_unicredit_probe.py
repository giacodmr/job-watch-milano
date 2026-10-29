"""Live read-only UniCredit official 15-per-page, 559-total and city evidence audit."""
import re, json, html, requests
from html.parser import HTMLParser
from urllib.parse import urlparse

URL="https://careers.unicredit.eu/en_GB/jobsuche/SearchJobs/"
SIZE=15
MAX=90
class Strip(HTMLParser):
 def __init__(self):
  super().__init__();self.parts=[]
 def handle_data(self,data):self.parts.append(data)
 def get(self):return " ".join(" ".join(self.parts).split())

def text(raw):
 p=Strip();p.feed(raw or "");return p.get()

def extract(body,expected_offset):
 legend=re.search(r'<div[^>]*class=["\'][^"\']*list-controls__text__legend[^"\']*["\'][^>]*>(.*?)</div>',body,re.I|re.S)
 if not legend:raise RuntimeError("No official result count legend")
 m=re.search(r'(\d+)\s*-\s*(\d+)\s+of\s+(\d+)\s+results',text(legend.group(1)),re.I)
 if not m:raise RuntimeError("Official result legend not parseable: "+text(legend.group(1))[:120])
 begin,end,total=map(int,m.groups())
 if begin!=expected_offset+1 or end!=min(expected_offset+SIZE,total):
  raise RuntimeError(f"Page offset mismatch {expected_offset} yielded {begin}-{end}/{total}")
 jobs=[]
 articles=re.findall(r'<article\b[^>]*class=["\'][^"\']*article--result[^"\']*["\'][^>]*>.*?</article>',body,re.I|re.S)
 for row in articles:
  href=re.search(r'<h3[^>]*class=["\'][^"\']*article__header__text__title[^"\']*["\'][^>]*>\s*<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',row,re.I|re.S)
  if not href:raise RuntimeError("Missing official job detail URL")
  path=urlparse(html.unescape(href.group(1))).path
  id_match=re.search(r'/JobDetail/(?:[^/]+/)?(\d{4,})/?$',path,re.I)
  if not id_match:raise RuntimeError("Unrecognized job path "+path)
  spans=re.findall(r'<span[^>]*class=["\']([^"\']*job-info-icon[^"\']*)["\'][^>]*>(.*?)</span>',row,re.I|re.S)
  metadata={"title":text(href.group(2)),"id":id_match.group(1),"url":html.unescape(href.group(1))}
  for cls,body in spans:
   if "job-info-icon_world" in cls:metadata["world"]=text(body)
   if "job-info-icon_function" in cls:metadata["department"]=text(body)
   if "job-info-icon_work" in cls:metadata["employment"]=text(body)
  jobs.append(metadata)
 if len(jobs)!=end-begin+1:raise RuntimeError(f"Page has {len(jobs)} rows instead of {end-begin+1}")
 return total,jobs

def main():
 ses=requests.Session();ses.headers.update({"User-Agent":"job-watch-milano/public-ats-contract"})
 first=None;all_rows=[];totals=set()
 for page in range(MAX):
  offset=page*SIZE
  if first is not None and offset>=first:break
  r=ses.get(URL,params={"jobRecordsPerPage":SIZE,"jobOffset":offset},timeout=25);r.raise_for_status()
  total,rows=extract(r.text,offset)
  if first is None:first=total
  totals.add(total)
  all_rows.extend(rows)
  if page in (0,1,10,20,30,(first-1)//SIZE):
   print("UNICREDIT_PAGE "+json.dumps({"offset":offset,"range":f"{offset+1}-{min(first,offset+SIZE)}","reported_total":total,
      "jobs":len(rows),"first":rows[:2]},ensure_ascii=False)[:2200])
  if len(totals)>1:raise RuntimeError("Portal total changed across pages")
 else:raise RuntimeError("Exceeded maximum safe pages")
 ids=[x["id"] for x in all_rows]
 if len(set(ids))!=first or len(ids)!=first:raise RuntimeError(f"Not exhaustive: {len(ids)} rows {len(set(ids))} unique expected {first}")
 countries={}
 for x in all_rows:countries[x.get("world","UNKNOWN")]=countries.get(x.get("world","UNKNOWN"),0)+1
 italian=[x for x in all_rows if (x.get("world") or "").lower() in {"italy","italia"}]
 print("UNICREDIT_GLOBAL "+json.dumps({"expected":first,"total_rows":len(all_rows),"unique_ids":len(set(ids)),
   "country_counts":countries,"italy_count":len(italian),"italian_samples":italian[:15]},ensure_ascii=False)[:10000])
 desired=sorted(italian,key=lambda r:(0 if re.search(r"strateg|product|business|operations|consult|analyst|corporate",r["title"],re.I) else 1,r["title"]))
 for row in desired[:10]:
  try:
   r=ses.get(row["url"],timeout=22);r.raise_for_status()
   chunks=re.findall(r'<span[^>]*class=["\']([^"\']*job-info-icon[^"\']*)["\'][^>]*>(.*?)</span>',r.text,re.I|re.S)
   details=[{"class":k,"text":text(v)[:90]} for k,v in chunks[:15]]
   terms=[]
   for word in ("Milan","Milano","Roma","Rome","Location","Place of work","Sede di lavoro","Work location","City","Città"):
    m=re.search(word,r.text,re.I)
    if m:terms.append({"key":word,"fragment":text(r.text[max(0,m.start()-180):m.end()+250])[:260]})
   print("UNICREDIT_ITALY_DETAIL "+json.dumps({"id":row["id"],"title":row["title"],"url":row["url"],
    "http":r.status_code,"url_after":r.url,"header_icons":details,"context":terms[:6]},ensure_ascii=False)[:4300])
  except requests.RequestException as exc:print("UNICREDIT_DETAIL_ERROR "+json.dumps({"id":row["id"],"error":str(exc)[:140]}))
if __name__=="__main__":main()
