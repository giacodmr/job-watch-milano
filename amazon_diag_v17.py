#!/usr/bin/env python3
import json
import math
import requests

API = "https://www.amazon.jobs/en/search.json"
TIMEOUT = 30


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


def flat(data, name):
    raw = (data.get("facets") or {}).get(name + "_facet") or []
    out = {}
    for item in raw:
        if isinstance(item, dict):
            for k, v in item.items():
                try:
                    out[str(k)] = int(v)
                except (TypeError, ValueError):
                    pass
    return out


def scalar_tree(value, prefix="", depth=0):
    if depth > 4:
        return []
    rows = []
    if isinstance(value, dict):
        for k, v in value.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            if k in {"jobs", "facets"}:
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                rows.append((p, v))
            else:
                rows.extend(scalar_tree(v, p, depth + 1))
    elif isinstance(value, list) and len(value) <= 10:
        for i, v in enumerate(value):
            rows.extend(scalar_tree(v, f"{prefix}[{i}]", depth + 1))
    return rows


def job_locations(job):
    out = []
    for raw in job.get("locations") or []:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                continue
        if isinstance(raw, dict):
            out.append(raw)
    return out


def main():
    s = requests.Session()

    # Global response structure + every scalar that could contain a non-capped total.
    global_params = [
        ("offset", "0"),
        ("result_limit", "1"),
        ("sort", "recent"),
        ("facets[]", "normalized_country_code"),
        ("facets[]", "location"),
    ]
    g = get(s, global_params)
    print("GLOBAL_TOP_KEYS", sorted(g.keys()))
    print("GLOBAL_HITS", g.get("hits"), "JOBS", len(g.get("jobs") or []))
    for path, value in scalar_tree(g):
        low = path.casefold()
        if any(token in low for token in ("total", "count", "hit", "size", "start", "limit", "number")):
            print("GLOBAL_SCALAR", path, repr(value))

    countries = flat(g, "normalized_country_code")
    print("COUNTRIES", len(countries), "SUM", sum(countries.values()), "MAX", sorted(countries.items(), key=lambda x: -x[1])[:10])

    # USA exact country count from the global facet; inspect all raw location facet values.
    usa_params = [
        ("offset", "0"),
        ("result_limit", "100"),
        ("sort", "recent"),
        ("normalized_country_code[]", "USA"),
        ("facets[]", "location"),
        ("facets[]", "normalized_state_name"),
    ]
    u = get(s, usa_params)
    locations = flat(u, "location")
    states = flat(u, "normalized_state_name")
    print("USA_COUNTRY_FACET_COUNT", countries.get("USA"), "USA_HITS", u.get("hits"))
    print("USA_LOCATION_FACET", {"values": len(locations), "sum_counts": sum(locations.values()), "max": sorted(locations.items(), key=lambda x:-x[1])[:10]})
    print("USA_STATE_FACET", {"values": len(states), "sum_counts": sum(states.values()), "max": sorted(states.items(), key=lambda x:-x[1])[:10]})

    # Check whether every job in the visible capped USA window has at least one raw location value.
    # We do not need to scan all 10k again: sample boundary pages + known last visible page.
    for offset in (0, 4900, 9900):
        d = get(s, [("offset", str(offset)), ("result_limit", "100"), ("sort", "recent"), ("normalized_country_code[]", "USA")])
        missing = []
        for job in d.get("jobs") or []:
            locs = job_locations(job)
            if not any((x.get("location") or "").strip() for x in locs if (x.get("normalizedCountryCode") or x.get("countryIso3a")) == "USA"):
                missing.append(str(job.get("id")))
        print("USA_RAW_LOCATION_SAMPLE", offset, {"rows": len(d.get("jobs") or []), "missing": len(missing), "sample": missing[:5]})

    # Test OR semantics for multiple raw location values and verify the result is bounded by the
    # sum of the facet counts. Use a small deterministic subset first.
    ordered = sorted(locations.items(), key=lambda x: (-x[1], x[0]))
    probe_values = [name for name, _count in ordered[:3]]
    probe_sum = sum(locations[x] for x in probe_values)
    params = [("offset", "0"), ("result_limit", "100"), ("sort", "recent"), ("normalized_country_code[]", "USA")]
    for value in probe_values:
        params.append(("location[]", value))
    p = get(s, params)
    print("LOCATION_OR_PROBE", {"values": probe_values, "facet_count_sum": probe_sum, "hits": p.get("hits"), "rows": len(p.get("jobs") or [])})

    # Greedy bin-pack all returned raw location facet values so each group's *sum of counts*
    # remains well below the 10k cap. If OR semantics holds, each group's unique hits must be <= sum.
    bins = []
    target = 7000
    for name, count in ordered:
        placed = False
        for b in bins:
            if b["sum"] + count <= target:
                b["values"].append(name)
                b["sum"] += count
                placed = True
                break
        if not placed:
            bins.append({"values": [name], "sum": count})
    print("LOCATION_BINS", {"count": len(bins), "sums": [b["sum"] for b in bins], "value_counts": [len(b["values"]) for b in bins]})

    # Probe each packed group's first page. A complete enumeration will be done only if these
    # grouped filters are accepted and remain safely below the cap.
    for i, b in enumerate(bins, 1):
        params = [("offset", "0"), ("result_limit", "100"), ("sort", "recent"), ("normalized_country_code[]", "USA")]
        for value in b["values"]:
            params.append(("location[]", value))
        d = get(s, params)
        print("LOCATION_BIN_PROBE", i, {"values": len(b["values"]), "sum_counts": b["sum"], "hits": d.get("hits"), "rows": len(d.get("jobs") or [])})


if __name__ == "__main__":
    main()
