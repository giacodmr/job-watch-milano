#!/usr/bin/env python3
import json
import requests

API = "https://www.amazon.jobs/en/search.json"
TIMEOUT = 30
PAGE_SIZE = 100
TARGETS = {
    "Milan": "ITA",
    "Rome": "ITA",
    "London": "GBR",
}


def get(session, params):
    r = session.get(
        API,
        params=params,
        timeout=TIMEOUT,
        headers={"User-Agent": "job-watch-milano/amazon-diagnostic", "Accept": "application/json"},
    )
    print("HTTP", r.status_code, len(r.content), r.url)
    r.raise_for_status()
    return r.json()


def request_body(data):
    raw = data.get("job_posting_search_request")
    if isinstance(raw, str):
        try:
            return json.loads(raw).get("jobPostingSearchRequest") or {}
        except Exception:
            return {}
    if isinstance(raw, dict):
        return raw.get("jobPostingSearchRequest") or raw
    return {}


def expected_filters(data, cities, countries):
    req = request_body(data)
    facets = req.get("filterFacets") or []
    parsed = {}
    for facet in facets:
        if not isinstance(facet, dict):
            continue
        name = facet.get("name")
        vals = []
        for item in facet.get("values") or []:
            if isinstance(item, dict) and item.get("name") is not None:
                vals.append(str(item.get("name")))
        parsed[name] = set(vals)
    want = {
        "normalizedCityName": set(cities),
        "normalizedCountryCode": set(countries),
    }
    if parsed.get("normalizedCityName") != want["normalizedCityName"]:
        raise RuntimeError(f"city filter echo mismatch: {parsed}")
    if parsed.get("normalizedCountryCode") != want["normalizedCountryCode"]:
        raise RuntimeError(f"country filter echo mismatch: {parsed}")


def locations(job):
    out = []
    for raw in job.get("locations") or []:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                continue
        if isinstance(raw, dict):
            out.append(raw)
    if not out:
        out.append({
            "normalizedCityName": job.get("city"),
            "normalizedCountryCode": job.get("country_code"),
            "normalizedLocation": job.get("normalized_location"),
            "location": job.get("location"),
        })
    return out


def target_pairs(job):
    pairs = set()
    for loc in locations(job):
        city = loc.get("normalizedCityName") or loc.get("city")
        country = loc.get("normalizedCountryCode") or loc.get("countryIso3a")
        if city in TARGETS and country == TARGETS[city]:
            pairs.add((city, country))
    return pairs


def enumerate_scope(session, label, cities, countries):
    seen = {}
    expected_hits = None
    offset = 0
    page = 0
    while True:
        page += 1
        params = [("offset", str(offset)), ("result_limit", str(PAGE_SIZE)), ("sort", "recent")]
        for city in cities:
            params.append(("normalized_city_name[]", city))
        for country in countries:
            params.append(("normalized_country_code[]", country))
        data = get(session, params)
        expected_filters(data, cities, countries)
        hits = int(data.get("hits"))
        jobs = data.get("jobs") or []
        if expected_hits is None:
            expected_hits = hits
        elif hits != expected_hits:
            raise RuntimeError(f"{label}: hits changed {expected_hits}->{hits}")
        ids = [str(j.get("id")) for j in jobs if j.get("id")]
        if len(ids) != len(jobs) or len(ids) != len(set(ids)):
            raise RuntimeError(f"{label}: invalid/duplicate IDs inside page {page}")
        overlap = set(ids) & set(seen)
        if overlap:
            raise RuntimeError(f"{label}: overlap across pages {sorted(overlap)[:5]}")
        for j in jobs:
            seen[str(j["id"])] = j
        print("PAGE", label, {"page": page, "offset": offset, "rows": len(jobs), "hits": hits, "collected": len(seen)})
        if len(seen) == expected_hits:
            break
        if len(seen) > expected_hits:
            raise RuntimeError(f"{label}: overflow {len(seen)}>{expected_hits}")
        if not jobs:
            raise RuntimeError(f"{label}: no pagination progress at {len(seen)}/{expected_hits}")
        offset += len(jobs)
        if page > 100:
            raise RuntimeError(f"{label}: too many pages")
    print("RECONCILE", label, {"hits": expected_hits, "unique": len(seen), "pages": page})
    return expected_hits, seen


def main():
    s = requests.Session()
    singles = {}
    for city, country in TARGETS.items():
        hits, rows = enumerate_scope(s, city.upper(), [city], [country])
        invalid = [jid for jid, job in rows.items() if (city, country) not in target_pairs(job)]
        print("SINGLE", city, {"hits": hits, "invalid_target_evidence": len(invalid)})
        if invalid:
            raise SystemExit(f"{city}: filtered jobs lack exact target location evidence: {invalid[:5]}")
        singles[city] = rows

    union = {}
    for rows in singles.values():
        union.update(rows)
    memberships = {jid: sorted(city for city, rows in singles.items() if jid in rows) for jid in union}
    overlaps = {jid: cities for jid, cities in memberships.items() if len(cities) > 1}
    print("SINGLE_UNION", {"unique": len(union), "overlaps": len(overlaps), "overlap_sample": list(overlaps.items())[:20]})

    combined_hits, combined = enumerate_scope(s, "COMBINED", list(TARGETS), sorted(set(TARGETS.values())))
    invalid_combined = [jid for jid, job in combined.items() if not target_pairs(job)]
    print("COMBINED_TARGET_EVIDENCE", {"invalid": len(invalid_combined)})
    if invalid_combined:
        raise SystemExit(f"combined filter returned non-target jobs: {invalid_combined[:10]}")
    print(
        "UNION_COMPARE",
        {
            "single_union": len(union),
            "combined_hits": combined_hits,
            "combined_unique": len(combined),
            "same_ids": set(union) == set(combined),
            "only_single": len(set(union) - set(combined)),
            "only_combined": len(set(combined) - set(union)),
        },
    )
    if set(union) != set(combined):
        raise SystemExit("combined Amazon target inventory differs from union of exact city scopes")

    # Second complete combined snapshot: require identical total and IDs.
    hits2, combined2 = enumerate_scope(s, "COMBINED_REPEAT", list(TARGETS), sorted(set(TARGETS.values())))
    print("STABILITY", {"hits1": combined_hits, "hits2": hits2, "same_ids": set(combined) == set(combined2)})
    if combined_hits != hits2 or set(combined) != set(combined2):
        raise SystemExit("Amazon target inventory is not stable across consecutive exhaustive snapshots")
    print("AMAZON_TARGET_EXHAUSTIVE_OK", combined_hits)


if __name__ == "__main__":
    main()
