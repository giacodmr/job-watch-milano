"""Read-only bounded inspection of official ATS HTML surfaces (no auth/bypass)."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

SOURCES = {
    "worldline_first": "https://jobs.worldline.com/viewalljobs/",
    "worldline_second": "https://jobs.worldline.com/viewalljobs/50/",
    "worldline_search": "https://jobs.worldline.com/search/",
    "revolut": "https://www.revolut.com/careers/",
    "nexi": "https://www.nexigroup.com/it/people/lavora-in-nexi/posizioni-aperte/",
}
HINTS = ["job", "jobs", "career", "post", "position", "offer", "vacan", "ashby", "workday", "successfactor", "apiendpoint", "searchquery", "tile", "iframe", "graphql", "__next_data__", "requisition"]
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.scripts = []
        self.iframes = []
        self.tags = {}
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self.tags[tag] = self.tags.get(tag, 0) + 1
        if tag == "a" and d.get("href"):
            self.links.append({"href":d["href"],"text":d.get("aria-label"),"class":d.get("class")})
        if tag == "script":
            self.scripts.append({"src":d.get("src"),"id":d.get("id"),"type":d.get("type")})
        if tag == "iframe":
            self.iframes.append({"src":d.get("src")})


def snippets(body, tokens, max_snips=12, radius=140):
    found = []
    for term in tokens:
        pos = 0
        count = 0
        while len(found) < max_snips and count < 2:
            m = re.search(re.escape(term), body[pos:], flags=re.I)
            if not m:
                break
            idx = pos + m.start()
            excerpt = re.sub(r"\s+", " ", body[max(0,idx-radius):idx+radius])
            found.append({"needle":term,"excerpt":excerpt[:2*radius]})
            pos = idx + len(term)
            count += 1
    return found


def report(name,url,session):
    try:
        r=session.get(url,headers={"Accept":"text/html,application/xhtml+xml"},timeout=22)
    except requests.RequestException as exc:
        return {"source":name,"error":type(exc).__name__,"hint":str(exc)[:150]}
    p=Metadata()
    p.feed(r.text)
    if name == "revolut":
        m=re.search(r'<script\b[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',r.text,re.I|re.S)
        if m:
            try:
                data=json.loads(m.group(1))
                print("REVOLUT_NEXT_KEYS "+json.dumps({"top":list(data),"props":list(data.get("props",{})),"pageProps":list(data.get("props",{}).get("pageProps",{}))}))
                def walk(node,path="",depth=0):
                    if depth>9: return
                    if isinstance(node,dict):
                        for k,v in node.items():
                            pth=(path+"."+k) if path else k
                            if any(x in k.casefold() for x in ("position","job","vacanc","career","listing")):
                                sample=(list(v[0]) if isinstance(v,list) and v and isinstance(v[0],dict) else list(v)[:12] if isinstance(v,dict) else "")
                                print("REVOLUT_KEY "+json.dumps({"path":pth,"kind":type(v).__name__,"length":len(v) if isinstance(v,(list,dict,str)) else None,"sample_keys":sample},ensure_ascii=False)[:900])
                            walk(v,pth,depth+1)
                    elif isinstance(node,list) and node and isinstance(node[0],dict) and len(node)>10:
                        sample={"path":path,"n":len(node),"first_keys":list(node[0])[:25]}
                        if any(x in str(node[0]).lower()[:900] for x in ("office","remote","position","title")) or len(node)>=50:
                            print("REVOLUT_ARRAY "+json.dumps(sample,ensure_ascii=False)[:900])
                        walk(node[0],path+"[0]",depth+1)
                pp=data.get("props",{}).get("pageProps",{})
                values=pp.get("positions",[])
                print("REVOLUT_POSTINGS "+json.dumps({
                    "count":len(values),
                    "widgetData":pp.get("widgetData",{}).get("careers-teams-widget"),
                    "first3":[{"id":v.get("id"),"text":v.get("text"),"locations":v.get("locations"),"team":v.get("team"),"desc_prefix":str(v.get("description"))[:120]} for v in values[:3]],
                    "office_or_remote":sum(1 for v in values if "milan" in str(v.get("locations")).lower() or "rome" in str(v.get("locations")).lower() or "london" in str(v.get("locations")).lower()),
                    "target_examples":[{"id":v.get("id"),"text":v.get("text"),"locations":v.get("locations"),"team":v.get("team")} for v in values if "milan" in str(v.get("locations")).lower() or "rome" in str(v.get("locations")).lower() or "london" in str(v.get("locations")).lower()][:6]
                },ensure_ascii=False,default=str)[:12500])
                import unicodedata
                for v in [z for z in values if "london" in str(z.get("locations")).lower()][:2]:
                    slug=unicodedata.normalize("NFKD",str(v.get("text",""))).encode("ascii","ignore").decode("ascii").lower()
                    slug=re.sub(r"[^a-z0-9]+","-",slug).strip("-")
                    candidates=[
                        f"https://www.revolut.com/careers/position/{slug}-{v['id']}/",
                        f"https://www.revolut.com/careers/position/{v['id']}/",
                    ]
                    for cand in candidates:
                        try:
                            rr=session.get(cand,timeout=16)
                            mm=re.search(r'<script\b[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',rr.text,re.I|re.S)
                            dd=json.loads(mm.group(1)) if mm else {}
                            pp2=dd.get("props",{}).get("pageProps",{})
                            print("REVOLUT_DETAIL "+json.dumps({
                                "candidate":cand,"http":rr.status_code,"final_url":rr.url,
                                "pageProps_keys":list(pp2),"position_id":(pp2.get("position") or {}).get("id") if isinstance(pp2.get("position"),dict) else None,
                                "page_title":re.findall(r"<h1[^>]*>(.*?)</h1>",rr.text,re.S|re.I)[:1],
                            },ensure_ascii=False)[:1300])
                        except requests.RequestException as exc:
                            print("REVOLUT_DETAIL "+json.dumps({"candidate":cand,"error":type(exc).__name__}))
                walk(pp)
            except (ValueError, TypeError) as exc:
                print("REVOLUT_NEXT_ERROR "+str(exc)[:160])
    relevant_links = [x for x in p.links if any(k in x["href"].casefold() for k in ("/job/", "/jobs/", "career", "position", "open", "recruit", "workday"))]
    print(json.dumps({
        "source":name,"http_status":r.status_code,"url":r.url,"length":len(r.content),
        "links_total":len(p.links),"links_relevant_count":len(relevant_links),
        "links_relevant_sample":relevant_links[:25],
        "script_count":len(p.scripts),"script_sources":p.scripts[:18],
        "iframes":p.iframes[:12],
        "tag_counts":{x:p.tags.get(x) for x in ("a","article","table","tr","script","iframe")},
        "job_urls_text_matches":len(re.findall(r"/job/|/jobs/|/vacancies/|job-posting|jobPosting",r.text,re.I)),
        "uuid_count":len(set(UUID_RE.findall(r.text))),
        "hints":snippets(r.text,["apiEndpoint","searchQuery","jobs2web","job-tile","joblist","jobList","jobData","careerSiteCompanyId","__NEXT_DATA__","We have","requisitions"],max_snips=12),
    },ensure_ascii=False)[:9000])
    return None


def main():
    session = requests.Session()
    session.headers["User-Agent"] = "job-watch-milano/ATS-public-contract-audit"
    try:
        import collector
        data,api=collector.oracle_get_page("fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com","CX_1",0)
        root=collector.oracle_extract_root(data)
        rows=root.get("requisitionList") or []
        print("NEXI_ORACLE_SCHEMA "+json.dumps({
            "total":root.get("TotalJobsCount"),"first_keys":list(rows[0]) if rows else [],
            "examples":[{"Id":x.get("Id"),"Title":x.get("Title"),
                         "PrimaryLocation":x.get("PrimaryLocation"),
                         "secondaryLocations":x.get("secondaryLocations"),
                         "otherWorkLocations":x.get("otherWorkLocations")} for x in rows[:3]],
        },ensure_ascii=False,default=str)[:6500])
    except Exception as exc:
        print("NEXI_ORACLE_SCHEMA_ERROR "+type(exc).__name__+" "+str(exc)[:180])
    for name,url in SOURCES.items():
        result=report(name,url,session)
        if result:
            print(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__":
    main()
