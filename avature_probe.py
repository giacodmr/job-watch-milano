import json, re, sys, urllib.parse
import requests
from bs4 import BeautifulSoup

URLS = {
    'siemens_branded': 'https://jobs.siemens-energy.com/en_US/jobs/Jobs/?folderRecordsPerPage=20&listFilterMode=1',
    'siemens_avature': 'https://siemensenergy.avature.net/en_US/careers/SearchJobs/',
    'deloitte': 'https://deloittecm.avature.net/en_US/careers/SearchJobs/',
    'ibm': 'https://ibmglobal.avature.net/en_US/careers/OpenJobs',
    'metlife': 'https://www.metlifecareers.com/en_US/ml/SearchJobs',
    'bain': 'https://www.bain.com/careers/find-a-role/',
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Cache-Control': 'no-cache',
}

COUNT_PATTERNS = [
    r'\b(\d[\d,.]*)\s*(?:results?|jobs?|positions?)\b',
    r'\b\d+\s*[-–]\s*\d+\s+of\s+(\d[\d,.+]*)\b',
    r'\bof\s+(\d[\d,.+]*)\s+(?:results?|jobs?|positions?)\b',
]

for label, url in URLS.items():
    print('\n' + '='*100)
    print(label, url)
    s = requests.Session(); s.headers.update(HEADERS)
    try:
        r = s.get(url, timeout=30, allow_redirects=True)
    except Exception as e:
        print('REQUEST_ERROR', type(e).__name__, repr(e)); continue
    print('STATUS', r.status_code, 'FINAL', r.url, 'LEN', len(r.text), 'CT', r.headers.get('content-type'))
    print('SERVER', r.headers.get('server'), 'VIA', r.headers.get('via'))
    print('COOKIES', sorted(s.cookies.get_dict().keys()))
    text = r.text
    print('AVATURE_MARKERS', sorted(set(re.findall(r'(?i)avature[^\s<>"\']{0,80}', text)))[:20])
    for p in COUNT_PATTERNS:
        vals = re.findall(p, BeautifulSoup(text, 'html.parser').get_text(' ', strip=True), flags=re.I)
        if vals: print('COUNT_PATTERN', p, vals[:20])
    if r.status_code != 200:
        print('BODY_HEAD', re.sub(r'\s+', ' ', text[:1000])); continue
    soup = BeautifulSoup(text, 'html.parser')
    print('TITLE', soup.title.get_text(' ', strip=True) if soup.title else None)
    forms=[]
    for f in soup.find_all('form'):
        forms.append({'method':(f.get('method') or 'GET').upper(),'action':urllib.parse.urljoin(r.url,f.get('action') or ''),'id':f.get('id'),'class':f.get('class')})
    print('FORMS', json.dumps(forms[:20], ensure_ascii=False))
    hidden=[]
    for x in soup.find_all('input', {'type':'hidden'}):
        hidden.append((x.get('name'), x.get('value')))
    print('HIDDEN', json.dumps(hidden[:80], ensure_ascii=False))
    selects=[]
    for sel in soup.find_all('select'):
        opts=[(o.get('value'),o.get_text(' ',strip=True)) for o in sel.find_all('option')[:12]]
        selects.append({'name':sel.get('name'),'id':sel.get('id'),'options':opts})
    print('SELECTS', json.dumps(selects[:30], ensure_ascii=False))
    links=[]
    for a in soup.find_all('a', href=True):
        href=urllib.parse.urljoin(r.url,a['href'])
        tx=a.get_text(' ',strip=True)
        if re.search(r'(?i)(job|requisition|position|career)', href) or re.search(r'(?i)(apply|job)', tx):
            links.append((href,tx))
    print('JOBLIKE_LINKS', json.dumps(links[:100], ensure_ascii=False))
    scripts=[urllib.parse.urljoin(r.url,x.get('src')) for x in soup.find_all('script', src=True)]
    print('SCRIPTS', json.dumps(scripts[:80], ensure_ascii=False))
    # key strings/params in raw HTML
    keys=sorted(set(re.findall(r'(?i)(folderOffset|folderRecordsPerPage|listFilterMode|jobRecordsPerPage|SearchJobs|OpenJobs|facet[^\s<>"\']*|csrf[^\s<>"\']*|xsrf[^\s<>"\']*)', text)))
    print('KEYS', keys[:100])
