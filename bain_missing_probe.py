import concurrent.futures,re,urllib.parse,requests
from bs4 import BeautifulSoup
BASE='https://careers.bain.com/jobs/SearchJobs'; IDS={'102466','100635'}
H={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0 Safari/537.36','Accept':'text/html,application/xhtml+xml'}
def get(off):
 r=requests.get(BASE,params={'folderRecordsPerPage':10,'folderOffset':off},headers=H,timeout=45);s=BeautifulSoup(r.text,'html.parser');found=[]
 for art in s.select('article.article--result'):
  for a in art.find_all('a',href=True):
   u=urllib.parse.urljoin(r.url,a['href']);p=urllib.parse.urlparse(u);tail=p.path.rstrip('/').rsplit('/',1)[-1]
   if tail in IDS:
    found.append((tail,u,re.sub(r'\s+',' ',art.get_text(' ',strip=True)),str(art)))
    break
 return found
allf=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
 for rows in ex.map(get,range(0,281,10)): allf.extend(rows)
print('FOUND',[(x[0],x[1],x[2]) for x in allf])
for sid,u,txt,raw in allf:
 r=requests.get(u,headers=H,timeout=45);s=BeautifulSoup(r.text,'html.parser')
 print('\nDETAIL',sid,r.status_code,r.url,'TITLE',s.title.get_text(' ',strip=True) if s.title else None)
 for f in s.select('.article__content__view__field'):
  lab=f.select_one('.article__content__view__field__label');val=f.select_one('.article__content__view__field__value')
  if lab and val: print('FIELD',lab.get_text(' ',strip=True),'=>',val.get_text(' ',strip=True))
 for el in s.find_all(True):
  cls=' '.join(el.get('class') or [])
  tx=re.sub(r'\s+',' ',el.get_text(' ',strip=True))
  if len(tx)<300 and (re.search(r'(?i)location|city|country|office',cls) or re.search(r'(?i)\b(location|city|country|office)\b',tx)):
   if cls: print('DOM',el.name,repr(cls),repr(tx))
