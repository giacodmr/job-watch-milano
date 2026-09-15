#!/usr/bin/env python3
import json
import re
import requests

API = "https://www.amazon.jobs/en/search.json"
TIMEOUT = 30


def get(session, params, label):
    r = session.get(API, params=params, timeout=TIMEOUT, headers={"User-Agent":"job-watch-milano/amazon-diagnostic","Accept":"application/json"})
    print("HTTP", label, r.status_code, len(r.content), r.url)
    r.raise_for_status()
    d = r.json()
    print("RESULT", label, "hits", d.get("hits"), "jobs", len(d.get("jobs") or []))
    print("REQUEST", label, json.dumps(d.get("job_posting_search_request"), sort_keys=True)[:5000])
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
    g = get(s, [("offset","0"),("result_limit","1"),("sort","recent"),("facets[]","normalized_country_code"),("facets[]","normalized_location"),("facets[]","location")], "GLOBAL")
    print("TOP_KEYS", sorted(g.keys()))
    content = g.get("content")
    print("CONTENT_TYPE", type(content).__name__, "LEN", len(content) if hasattr(content,"__len__") else None)
    if isinstance(content, str):
        print("CONTENT_PREVIEW", re.sub(r"\s+", " ", content)[:3000])
        for pat in (r"[\"'](?:total|totalCount|count|hits)[\"']\s*[:=]\s*[\"']?([\d,]+)", r"([\d,]+)\s+(?:open\s+)?jobs?"):
            print("CONTENT_TOTAL_MATCHES", pat, re.findall(pat, content, re.I)[:20])
    countries = flat(g, "normalized_country_code")
    print("COUNTRY_COUNT_USA", countries.get("USA"), "COUNTRIES", len(countries), "COUNTRY_SUM", sum(countries.values()))

    u = get(s, [("offset","0"),("result_limit","1"),("sort","recent"),("normalized_country_code[]","USA"),("facets[]","normalized_location"),("facets[]","location")], "USA")
    norm = flat(u, "normalized_location")
    raw = flat(u, "location")
    print("USA_NORMALIZED_LOCATION_VALUES", len(norm), "TOP", sorted(norm.items(), key=lambda x:-x[1])[:5])
    print("USA_RAW_LOCATION_VALUES", len(raw), "TOP", sorted(raw.items(), key=lambda x:-x[1])[:5])

    tests = [
        ("RAW_BRACKETS", [("normalized_country_code[]","USA"),("location[]","US, WA, Seattle")]),
        ("RAW_NO_BRACKETS", [("normalized_country_code[]","USA"),("location","US, WA, Seattle")]),
        ("NORM_BRACKETS", [("normalized_country_code[]","USA"),("normalized_location[]","Seattle, Washington, USA")]),
        ("NORM_NO_BRACKETS", [("normalized_country_code[]","USA"),("normalized_location","Seattle, Washington, USA")]),
        ("STATE_CONTROL", [("normalized_country_code[]","USA"),("normalized_state_name[]","Washington")]),
    ]
    for label, extra in tests:
        params=[("offset","0"),("result_limit","10"),("sort","recent")]+extra
        d=get(s,params,label)
        sample=[(j.get("id"),j.get("location"),j.get("normalized_location")) for j in (d.get("jobs") or [])[:3]]
        print("SAMPLE",label,sample)


if __name__ == "__main__":
    main()
