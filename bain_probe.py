import requests
from bs4 import BeautifulSoup
u='https://careers.bain.com/jobs/SearchJobs'
h={'User-Agent':'Mozilla/5.0','Accept':'text/html,application/xhtml+xml'}
r=requests.get(u,headers=h,timeout=30,allow_redirects=True)
s=BeautifulSoup(r.text,'html.parser')
print('STATUS',r.status_code,'FINAL',r.url,'LEN',len(r.text))
print('TITLE',s.title.get_text(' ',strip=True) if s.title else None)
print('TEXT',s.get_text(' ',strip=True)[:1000])
print('ARTICLES',len(s.select('article.article--result')))
for a in s.select('a.paginationNextLink')[:2]: print('NEXT',a.get('href'))
