#!/usr/bin/env python3
import json
import requests

API = "https://www.amazon.jobs/en/search.json"
TIMEOUT = 30


def get(session, params):
    r = session.get(API, params=params, timeout=TIMEOUT, headers={"User-Agent":"job-watch-milano/amazon-diagnostic","Accept":"application/json"})
    print("HTTP", r.status_code, len(r.content), r.url)
    if not r.ok:
        print("BODY", r.text[:1500])
    r.raise_for_status()
    return r.json()


def country_facets(data):
    raw = (data.get("facets") or {}).get("normalized_country_code_facet") or []
    out = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            try: out[str(key)] = int(value)
            except Exception: pass
    return out


def ids(data):
    return [str(x.get("id")) for x in (data.get("jobs") or []) if x.get("id")]


def main():
    s = requests.Session()
    base = get(s, [("offset","0"),("result_limit","1"),("sort","recent"),("facets[]","normalized_country_code")])
    countries = country_facets(base)
    ordered = sorted(countries.items(), key=lambda x: (-x[1], x[0]))
    print("GLOBAL_HITS", base.get("hits"))
    print("COUNTRIES", len(ordered), ordered)
    print("COUNTRY_COUNT_SUM", sum(countries.values()), "MAX", ordered[0] if ordered else None)

    for offset in (9800, 9900, 9999, 10000, 10001, 10100, 12000, 15000):
        try:
            data = get(s, [("offset",str(offset)),("result_limit","100"),("sort","recent")])
            print("OFFSET", offset, {"hits":data.get("hits"),"rows":len(data.get("jobs") or []),"ids":ids(data)[:3],"last":ids(data)[-3:]})
        except Exception as e:
            print("OFFSET_ERROR", offset, type(e).__name__, str(e))

    # Test effective page size and exact facet-count echo on the largest countries.
    for code, facet_count in ordered[:8]:
        for limit in (100, 250, 500, 1000):
            try:
                data = get(s, [("offset","0"),("result_limit",str(limit)),("sort","recent"),("normalized_country_code[]",code)])
                print("COUNTRY_LIMIT", code, {"facet_count":facet_count,"limit":limit,"hits":data.get("hits"),"rows":len(data.get("jobs") or []),"unique":len(set(ids(data)))})
            except Exception as e:
                print("COUNTRY_LIMIT_ERROR", code, limit, type(e).__name__, str(e))
                break


if __name__ == "__main__":
    main()
