import concurrent.futures
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup

BASE='https://careers.bain.com/jobs/SearchJobs'
H={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0 Safari/537.36','Accept':'text/html,application/xhtml+xml','Accept-Language':'en-US,en;q=0.9'}
RANGE=re.compile(r'([\d,]+)\s*[-–—]\s*([\d,]+)\s+of\s+([\d,]+)(\+?)',re.I)

def sid_from_url(u):
 p=urllib.parse.urlparse(u); path=p.path.rstrip('/'); tail=path.rsplit('/',1)[-1]
 if ('/FolderDetail/' in path or '/JobDetail/' in path) and tail.isdigit(): return tail
 if path.lower().endswith(('/folderdetail','/jobdetail')):
  q=urllib.parse.parse_qs(p.query)
  for k in ('folderId','folderID','jobId','jobID'):
   vals=q.get(k) or []
   if len(vals)==1 and vals[0].isdigit(): return vals[0]
 return None

def parse(r,dom=False):
 s=BeautifulSoup(r.text,'html.parser'); text=s.get_text(' ',strip=True); m=RANGE.search(text)
 rg=(int(m.group(1).replace(',','')),int(m.group(2).replace(',','')),int(m.group(3).replace(',','')),bool(m.group(4))) if m else None
 arts=s.select('article.article--result'); rows=[]
 for art in arts:
  found={}; title=None; url=None
  for a in art.find_all('a',href=True):
   u=urllib.parse.urljoin(r.url,a['href']); sid=sid_from_url(u)
   if sid:
    found[sid]=u
    tx=a.get_text(' ',strip=True)
    if tx and tx.lower() not in ('learn more','apply','view') and title is None: title=tx;url=u
  if len(found)!=1: raise RuntimeError(f'card stable IDs={found}')
  sid=next(iter(found)); url=url or found[sid]
  locel=art.select_one('.list-item-location')
  loc=locel.get_text(' ',strip=True) if locel else None
  rows.append((sid,url,title,loc))
 if dom and arts:
  print('FIRST_ARTICLE',re.sub(r'\s+',' ',arts[0].get_text(' ',strip=True)))
  for el in arts[0].find_all(True):
   cls=' '.join(el.get('class') or []); tx=re.sub(r'\s+',' ',el.get_text(' ',strip=True))
   if cls: print('DOM',el.name,repr(cls),repr(tx[:250]))
  for a in arts[0].find_all('a',href=True): print('LINK',repr(a.get_text(' ',strip=True)),urllib.parse.urljoin(r.url,a['href']),sid_from_url(urllib.parse.urljoin(r.url,a['href'])))
 return rg,rows,len(arts)

def get(off):
 r=requests.get(BASE,params={'folderRecordsPerPage':10,'folderOffset':off},headers=H,timeout=45)
 if r.status_code!=200: raise RuntimeError((off,r.status_code,r.url))
 return off,*parse(r)

first=requests.get(BASE,headers=H,timeout=45); print('FIRST',first.status_code,first.url)
fr,firstrows,arts=parse(first,True); print('FIRST_RANGE',fr,'ROWS',len(firstrows),'ARTICLES',arts)
if not fr or fr[0]!=1 or fr[3]: raise SystemExit(2)
total=fr[2]; size=fr[1]-fr[0]+1; offs=list(range(0,total,size)); print('PLAN',total,size,len(offs))
res={0:(fr,firstrows,arts)}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 futs={pool.submit(get,o):o for o in offs[1:]}
 for f in concurrent.futures.as_completed(futs):
  o,rg,rows,a=f.result();res[o]=(rg,rows,a)
seen=set();errs=[]
for o in offs:
 rg,rows,a=res[o]; est=o+1; een=min(o+size,total); exp=(est,een,total,False); n=een-est+1
 print('PAGE',o,'RANGE',rg,'ARTICLES',a,'ROWS',len(rows))
 if rg!=exp: errs.append(f'range {o}: {rg}!={exp}')
 if a!=n or len(rows)!=n: errs.append(f'count {o}: articles={a} rows={len(rows)} expected={n}')
 for sid,u,t,l in rows:
  if sid in seen: errs.append(f'overlap {sid} at {o}')
  seen.add(sid)
  if not l: errs.append(f'missing location {sid}')
reread=requests.get(BASE,headers=H,timeout=45); rr,rrows,ra=parse(reread)
if rr!=fr: errs.append(f'total changed {fr}->{rr}')
if [x[0] for x in rrows]!=[x[0] for x in firstrows]: errs.append('first page changed')
if len(seen)!=total: errs.append(f'unique {len(seen)} != total {total}')
print('SUMMARY','TOTAL',total,'UNIQUE',len(seen),'REREAD',rr,'FIRST_STABLE',[x[0] for x in rrows]==[x[0] for x in firstrows],'ERRORS',errs)
if errs: raise SystemExit(2)
