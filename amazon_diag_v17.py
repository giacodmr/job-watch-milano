#!/usr/bin/env python3
import json
import requests

API = "https://www.amazon.jobs/en/search.json"
TIMEOUT = 30
FACETS = [
    "normalized_country_code",
    "normalized_state_name",
    "normalized_city_name",
    "normalized_location",
    "location",
]


def get(session, params):
    r = session.get(
        API,
        params=params,
        timeout=TIMEOUT,
        headers={
            "User-Agent": "job-watch-milano/amazon-diagnostic",
            "Accept": "application/json",
        },
    )
    print("HTTP", r.status_code, len(r.content), r.url)
    r.raise_for_status()
    return r.json()


def base_params(limit=10, offset=0):
    params = [("offset", str(offset)), ("result_limit", str(limit)), ("sort", "recent")]
    for facet in FACETS:
        params.append(("facets[]", facet))
    return params


def request_json(data):
    raw = data.get("job_posting_search_request")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


def dump_facet(name, values):
    if not isinstance(values, list):
        print("FACET", name, "TYPE", type(values).__name__, repr(values)[:1000])
        return
    interesting = []
    for item in values:
        if not isinstance(item, dict):
            continue
        blob = json.dumps(item, ensure_ascii=False).casefold()
        if any(x in blob for x in ("milan", "milano", "rome", "roma", "london", "ital", "united kingdom", "gbr", "ita")):
            interesting.append(item)
    print("FACET", name, "COUNT", len(values), "INTERESTING", json.dumps(interesting, ensure_ascii=False)[:18000])


def summary(tag, data):
    jobs = data.get("jobs") or []
    print("\n===", tag, "===")
    print("HITS", data.get("hits"), "JOBS", len(jobs), "ERROR", data.get("error"))
    print("REQUEST", json.dumps(request_json(data), ensure_ascii=False, sort_keys=True)[:12000])
    facets = data.get("facets") or {}
    print("FACET_KEYS", sorted(facets.keys()) if isinstance(facets, dict) else type(facets).__name__)
    if isinstance(facets, dict):
        for name, values in facets.items():
            dump_facet(name, values)
    print(
        "JOBS_SAMPLE",
        [
            {
                "id": j.get("id"),
                "id_icims": j.get("id_icims"),
                "city": j.get("city"),
                "state": j.get("state"),
                "country_code": j.get("country_code"),
                "location": j.get("location"),
                "normalized_location": j.get("normalized_location"),
                "locations": j.get("locations"),
            }
            for j in jobs[:5]
        ],
    )


def probe(session, tag, extras):
    params = base_params()
    params.extend(extras)
    data = get(session, params)
    summary(tag, data)
    return data


def main():
    s = requests.Session()
    base = probe(s, "BASE_WITH_FACETS", [])

    probes = [
        ("COUNTRY_ITA_DIRECT", [("normalized_country_code[]", "ITA")]),
        ("COUNTRY_GBR_DIRECT", [("normalized_country_code[]", "GBR")]),
        ("CITY_MILAN_DIRECT", [("normalized_city_name[]", "Milan")]),
        ("CITY_MILANO_DIRECT", [("normalized_city_name[]", "Milano")]),
        ("CITY_ROME_DIRECT", [("normalized_city_name[]", "Rome")]),
        ("CITY_ROMA_DIRECT", [("normalized_city_name[]", "Roma")]),
        ("CITY_LONDON_DIRECT", [("normalized_city_name[]", "London")]),
        (
            "CITY_COMBINED_DIRECT",
            [
                ("normalized_city_name[]", "Milan"),
                ("normalized_city_name[]", "Rome"),
                ("normalized_city_name[]", "London"),
            ],
        ),
    ]
    for tag, extras in probes:
        try:
            probe(s, tag, extras)
        except Exception as e:
            print(tag, "ERROR", type(e).__name__, str(e))


if __name__ == "__main__":
    main()
