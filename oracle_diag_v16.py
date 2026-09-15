#!/usr/bin/env python3
import json
from pathlib import Path

import collector

TARGET = "American Express"
LIMITS = (25, 50, 100, 250, 500, 1000)


def load_company():
    for batch in ("jw1", "jw2", "jw3", "jw4"):
        data = json.loads(Path(f"ats_mapping_{batch}.json").read_text(encoding="utf-8"))
        for company in data.get("companies", []):
            if company.get("company") == TARGET:
                return company
    raise SystemExit(f"{TARGET} not found")


def fetch_page(host, site, limit, offset=0):
    endpoint = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    finder = f"findReqs;siteNumber={site},limit={limit},offset={offset}"
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
    print(f"HTTP host={host} limit={limit} offset={offset} status={r.status_code} bytes={len(r.content)}")
    r.raise_for_status()
    data = r.json()
    root = collector.oracle_extract_root(data)
    page = root.get("requisitionList") or []
    ids = [collector.oracle_source_id(x) for x in page if isinstance(x, dict)]
    ids = [x for x in ids if x]
    total = root.get("TotalJobsCount")
    print(
        f"  total={total} page_len={len(page)} unique_ids={len(set(ids))} "
        f"first={ids[:3]} last={ids[-3:]} root_keys={sorted(root.keys())}"
    )
    return int(total), set(ids), root, r.url


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
            total, ids, root, url = fetch_page(host, site, 25, 0)
            selected = host
            print("selected_host", host)
            break
        except Exception as e:
            print("host_error", host, type(e).__name__, str(e))
    if not selected:
        raise SystemExit("No usable Oracle host")

    for limit in LIMITS:
        print(f"\n=== LIMIT {limit} ===")
        try:
            a_total, a_ids, a_root, _ = fetch_page(selected, site, limit, 0)
            b_total, b_ids, b_root, _ = fetch_page(selected, site, limit, 0)
            print(
                "  repeat",
                {
                    "same_total": a_total == b_total,
                    "same_ids": a_ids == b_ids,
                    "a_count": len(a_ids),
                    "b_count": len(b_ids),
                    "total_a": a_total,
                    "total_b": b_total,
                },
            )
            if a_total > len(a_ids):
                next_offset = len(a_ids)
                if next_offset:
                    c_total, c_ids, c_root, _ = fetch_page(selected, site, limit, next_offset)
                    print(
                        "  page2",
                        {
                            "offset": next_offset,
                            "total": c_total,
                            "count": len(c_ids),
                            "overlap": len(a_ids & c_ids),
                        },
                    )
        except Exception as e:
            print("  ERROR", type(e).__name__, str(e))


if __name__ == "__main__":
    main()
