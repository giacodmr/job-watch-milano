"""Inspect public UniCredit detail location markup for job city, no credentials."""
import requests,re,json
PAGES={
 "87236":"https://careers.unicredit.eu/en_GB/jobsuche/JobDetail/Group-Strategy-Benchmarking-Internship-Opportunity-2026/87236",
 "107011":"https://careers.unicredit.eu/en_GB/jobsuche/JobDetail/Client-Risk-Management-Corporate-Digital-Development/107011",
 "115555":"https://careers.unicredit.eu/en_GB/jobsuche/JobDetail/Curricular-Internship-Ultra-High-Net-Worth-Strategic-Development-Milano/115555",
 "106810":"https://careers.unicredit.eu/en_GB/jobsuche/JobDetail/Gestore-Corporate-Junior/106810",
 "114535":"https://careers.unicredit.eu/en_GB/jobsuche/JobDetail/Senior-Technical-Analyst-Payments-Cash-Management-Solutions/114535",
}
def inspect(name,url):
 s=requests.Session()
 s.headers["User-Agent"]="job-watch-milano/ATS-official-detail-audit"
 r=s.get(url,timeout=22);r.raise_for_status()
 for word in ("MILANO","ROMA","luogo di lavoro","Place of Work","sede di lavoro","Location"):
  for m in list(re.finditer(re.escape(word),r.text,re.I))[:2]:
   excerpt=r.text[max(0,m.start()-700):min(len(r.text),m.end()+450)]
   print("CITY_MARKUP "+json.dumps({"id":name,"word":word,"offset":m.start(),"raw":re.sub(r"\s+"," ",excerpt)[:1100]},ensure_ascii=False))
 print("DETAIL_META "+json.dumps({"id":name,"http":r.status_code,"final":r.url,"size":len(r.content),"city_text_matches":len(re.findall(r"MILANO|ROMA",r.text,re.I))},ensure_ascii=False))
if __name__=="__main__":
 for k,u in PAGES.items():inspect(k,u)
