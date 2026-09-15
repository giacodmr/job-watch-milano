#!/usr/bin/env python3
import json
import requests

API = "https://www.amazon.jobs/en/search.json"
TIMEOUT = 30
FACETS = [
    "category",
    "schedule_type_id",
    "employee_class",
    "job_function_id",
    "business_category",
    "is_manager",
    "is_intern",
    "normalized_country_code",
]


def get(session, params, label):
    r = session.get(API, params=params, timeout=TIMEOUT, headers={"User-Agent":"job-watch-milano/amazon-diagnostic","Accept":"application/json"})
    print("HTTP", label, r.status_code, len(r.content), r.url)
    r.raise_for_status()
    d = r.json()
    print("RESULT", label, "hits", d.get("hits"), "jobs", len(d.get("jobs") or []))
    return d


def flat(data, name):
    out = {}
    for item in ((data.get("facets") or {}).get(name + "_facet") or []):
        if isinstance(item, dict):
            for k, v in item.items():
                try: out[str(k)] = int(v)
                except Exception: pass
    return out


def main():
    s = requests.Session()
    params=[("offset","0"),("result_limit","1"),("sort","recent")]
    for f in FACETS: params.append(("facets[]",f))
    d=get(s,params,"GLOBAL_FACETS")

    facet_data={}
    for f in FACETS:
        vals=flat(d,f)
        facet_data[f]=vals
        ordered=sorted(vals.items(),key=lambda x:(-x[1],x[0]))
        print("FACET",f,{"values":len(vals),"sum":sum(vals.values()),"max":ordered[:15]})

    # Test likely exhaustive partition facets: each value must be individually queryable.
    tests=[]
    for f in ("category","schedule_type_id","employee_class","job_function_id"):
        vals=facet_data[f]
        if vals:
            name,count=sorted(vals.items(),key=lambda x:-x[1])[0]
            tests.append((f,name,count))
    for f,name,count in tests:
        p=[("offset","0"),("result_limit","10"),("sort","recent"),(f+"[]",name)]
        x=get(s,p,"FILTER_"+f)
        print("FILTER_CHECK",f,{"value":name,"facet_count":count,"hits":x.get("hits"),"sample_ids":[str(j.get("id")) for j in (x.get("jobs") or [])[:3]],"request":x.get("job_posting_search_request")})

    # Also inspect category facet specifically within USA: if counts sum to exact USA country
    # count and every category is below 10k, it can solve the USA cap independently.
    up=[("offset","0"),("result_limit","1"),("sort","recent"),("normalized_country_code[]","USA"),("facets[]","category"),("facets[]","schedule_type_id"),("facets[]","employee_class"),("facets[]","job_function_id")]
    u=get(s,up,"USA_FACETS")
    for f in ("category","schedule_type_id","employee_class","job_function_id"):
        vals=flat(u,f); ordered=sorted(vals.items(),key=lambda x:(-x[1],x[0])); print("USA_FACET",f,{"values":len(vals),"sum":sum(vals.values()),"max":ordered[:15]})


if __name__ == "__main__":
    main()
