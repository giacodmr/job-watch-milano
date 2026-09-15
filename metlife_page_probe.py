import re
import urllib.parse
import requests
from bs4 import BeautifulSoup

H = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
base = "https://www.metlifecareers.com/en_US/ml/SearchJobs"
s = requests.Session(); s.headers.update(H)
for off in (444, 450, 456):
    r = s.get(base, params={"listFilterMode": 1, "jobRecordsPerPage": 6, "jobOffset": off}, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")
    legend = soup.select_one(".list-controls__text__legend")
    print("\nOFFSET", off, "STATUS", r.status_code, "LEGEND", legend.get_text(" ", strip=True) if legend else None)
    articles = soup.select("article.article--result")
    print("ARTICLES", len(articles))
    for i, article in enumerate(articles, 1):
        txt = re.sub(r"\s+", " ", article.get_text(" ", strip=True))
        print("ARTICLE", i, "ATTRS", dict(article.attrs), "TEXT", txt)
        for a in article.find_all("a", href=True):
            href = urllib.parse.urljoin(r.url, a["href"])
            print("  LINK", repr(a.get_text(" ", strip=True)), href)
        for tag in article.find_all(True):
            attrs = {k:v for k,v in tag.attrs.items() if re.search(r"(?i)(job|folder|req|id|data)", k)}
            if attrs:
                print("  ATTR", tag.name, attrs)
