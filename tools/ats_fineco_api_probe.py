"""Official Fineco first-party careers public API live schema and count probe.

Endpoint and origin are directly recovered from official Next.js bundles:
module 3473 exports T=https://public-api.finecobank.com, module 79443
issues GET at /v1/public/career/work-with-us/jobs. Only public GET.
"""
import json,requests,time
URL="https://public-api.finecobank.com/v1/public/career/work-with-us/jobs"
def dump(obj,limit=400):
 s=json.dumps(obj,ensure_ascii=False,default=str)
 return s[:limit]
def extract(o):
 print("FINECO_API_SCHEMA "+json.dumps({"type":type(o).__name__,"top_keys":list(o)[:30] if isinstance(o,dict) else [],"payload_sample":dump(o,2400)},ensure_ascii=False))
 if isinstance(o,dict):
  d=o.get("data") or {}
  jobs=d.get("jobs") if isinstance(d,dict) and isinstance(d.get("jobs"),list) else o.get("jobs")
  print("FINECO_API_DATA "+json.dumps({"data_keys":list(d)[:30] if isinstance(d,dict) else None,
    "total_field":d.get("total") if isinstance(d,dict) else None,
    "count":len(jobs) if isinstance(jobs,list) else None,
    "jobs_first":[{k:(str(v)[:160] if isinstance(v,str) else v) for k,v in item.items() if k not in {"description","jobDescription","descriptionHtml"} and not isinstance(v,(dict,list))}
      for item in jobs[:25]] if isinstance(jobs,list) else None},ensure_ascii=False)[:10000])
  if isinstance(jobs,list):
   ids=[str(j.get("id") or j.get("jobId") or j.get("uuid") or "") for j in jobs]
   print("FINECO_API_PARITY "+json.dumps({"list_len":len(jobs),"unique_nonempty_ids":len(set(x for x in ids if x)),
     "null_ids":sum(not x for x in ids),
     "job_keys":list(jobs[0]) if jobs and isinstance(jobs[0],dict) else [],
     "locations":list(dict.fromkeys(str(j.get("location")) for j in jobs if isinstance(j,dict)))[:30]},
     ensure_ascii=False))
 return o
def main():
 session=requests.Session();session.headers.update({"User-Agent":"job-watch-milano/official-ATS-public-probe","Accept":"application/json","Referer":"https://about.finecobank.com/it/careers/diventa-un-dipendente/","Origin":"https://about.finecobank.com"})
 for n in range(2):
  try:
   r=session.get(URL,timeout=28)
   print("FINECO_API_HEAD "+json.dumps({"attempt":n,"http":r.status_code,"final":r.url,"bytes":len(r.content),
     "content_type":r.headers.get("Content-Type")}))
   if r.status_code!=200:continue
   extract(r.json())
  except (requests.RequestException,ValueError) as exc:print("FINECO_API_ERROR "+json.dumps({"attempt":n,"error":str(exc)[:200]}))
  time.sleep(0.5)
if __name__=="__main__":main()
