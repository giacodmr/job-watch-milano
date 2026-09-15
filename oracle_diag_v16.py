#!/usr/bin/env python3
import json
from pathlib import Path

import collector

TARGET = "American Express"
PAGE_LIMIT = 200
SORT_BY = "POSTING_DATES_DESC"
OFFSETS = (0, 198, 199, 200, 201, 398, 399, 400, 401)


def load_company():
    for batch in ("jw1", "jw2", "jw3", "jw4"):
        data = json.loads(Path(f"ats_mapping_{batch}.json").read_text(encoding="utf-8"))
        for company in data.get("companies", []):
            if company.get("company") == TARGET:
                return company
    raise SystemExit(f"{TARGET} not found")


def fetch_page(host, site, offset):
    endpoint = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    finder = f"findReqs;siteNumber={site},limit={PAGE_LIMIT},offset={offset},sortBy={SORT_BY}"
    headers = {
        "Accept": "application/vnd.oracle.adf.resourcecollection+json, application/json",
        "Ora-Irc-Language": "en",
        "REST-Framework-Version": "1",
    }
    r = collector.get_session().get(
        endpoint,
        params={
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations",
            "finder": finder,
        },
        headers=headers,
        timeout=collector.TIMEOUT,
    )
    r.raise_for_status()
    root = collector.oracle_extract_root(r.json())
    page = root.get("requisitionList")
    if not isinstance(page, list):
        raise RuntimeError("requisitionList missing")
    ids = tuple(
        collector.oracle_source_id(raw)
        for raw in page
        if isinstance(raw, dict) and collector.oracle_source_id(raw)
    )
    print(
        "PAGE",
        {
            "offset": offset,
            "root_offset": root.get("Offset"),
            "root_limit": root.get("Limit"),
            "root_sort": root.get("SortBy"),
            "total": int(root.get("TotalJobsCount")),
            "rows": len(page),
            "unique": len(set(ids)),
            "first": ids[:3],
            "last": ids[-3:],
        },
    )
    return int(root.get("TotalJobsCount")), ids


def main():
    company = load_company()
    inventory = (company.get("ats") or {}).get("inventory_url")
    site = collector.oracle_site_from_inventory(inventory)
    hosts = collector.oracle_backend_hosts(inventory)
    print("inventory", inventory)
    print("site", site)
    print("hosts", hosts)

    selected = None
    for host in hosts:
        try:
            total, ids = fetch_page(host, site, 0)
            if ids:
                selected = host
                break
        except Exception as e:
            print("HOST_ERROR", host, type(e).__name__, str(e))
    if not selected:
        raise SystemExit("No usable Oracle backend host")
    print("selected_host", selected)

    pages = {}
    totals = {}
    for offset in OFFSETS:
        try:
            total, ids = fetch_page(selected, site, offset)
            totals[offset] = total
            pages[offset] = set(ids)
        except Exception as e:
            print("OFFSET_ERROR", offset, type(e).__name__, str(e))

    print("TOTALS", totals)
    base = pages.get(0, set())
    second_candidates = (198, 199, 200, 201)
    tail_candidates = (398, 399, 400, 401)
    expected_values = set(totals.values())
    expected = next(iter(expected_values)) if len(expected_values) == 1 else None
    print("EXPECTED_STABLE_TOTAL", expected)

    for second in second_candidates:
        for tail in tail_candidates:
            if second not in pages or tail not in pages:
                continue
            p1, p2 = pages[second], pages[tail]
            union = base | p1 | p2
            print(
                "COMBO",
                {
                    "offsets": (0, second, tail),
                    "unique": len(union),
                    "expected": expected,
                    "overlap_0_2": len(base & p1),
                    "overlap_2_3": len(p1 & p2),
                    "overlap_0_3": len(base & p2),
                    "exact": expected is not None and len(union) == expected,
                },
            )


if __name__ == "__main__":
    main()
