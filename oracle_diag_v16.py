#!/usr/bin/env python3
import json
from pathlib import Path

import collector

TARGET = "American Express"
WIDE_LIMIT = 500


def load_company():
    for batch in ("jw1", "jw2", "jw3", "jw4"):
        data = json.loads(Path(f"ats_mapping_{batch}.json").read_text(encoding="utf-8"))
        for company in data.get("companies", []):
            if company.get("company") == TARGET:
                return company
    raise SystemExit(f"{TARGET} not found")


def fetch_page(host, site, limit, offset=0, expand=False):
    endpoint = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    finder = f"findReqs;siteNumber={site},limit={limit},offset={offset}"
    headers = {
        "Accept": "application/vnd.oracle.adf.resourcecollection+json, application/json",
        "Ora-Irc-Language": "en",
        "REST-Framework-Version": "1",
    }
    params = {"onlyData": "true", "finder": finder}
    if expand:
        params["expand"] = "requisitionList.secondaryLocations"
    r = collector.get_session().get(endpoint, params=params, headers=headers, timeout=collector.TIMEOUT)
    print(
        f"HTTP host={host} limit={limit} offset={offset} expand={expand} "
        f"status={r.status_code} bytes={len(r.content)}"
    )
    r.raise_for_status()
    root = collector.oracle_extract_root(r.json())
    page = root.get("requisitionList") or []
    ids = [collector.oracle_source_id(x) for x in page if isinstance(x, dict)]
    ids = [x for x in ids if x]
    total = int(root.get("TotalJobsCount"))
    print(
        f"  total={total} page_len={len(page)} unique_ids={len(set(ids))} "
        f"first={ids[:3]} last={ids[-3:]}"
    )
    return total, set(ids), page, r.url


def compare(label, left, right):
    lt, li, _, _ = left
    rt, ri, _, _ = right
    print(
        label,
        {
            "same_total": lt == rt,
            "same_ids": li == ri,
            "left_count": len(li),
            "right_count": len(ri),
            "total_left": lt,
            "total_right": rt,
            "left_only": len(li - ri),
            "right_only": len(ri - li),
        },
    )


def main():
    company = load_company()
    inventory = (company.get("ats") or {}).get("inventory_url")
    site = collector.oracle_site_from_inventory(inventory)
    hosts = collector.oracle_backend_hosts(inventory)
    print("inventory", inventory)
    print("site", site)
    print("hosts", hosts)

    selected = None
    baseline = None
    for host in hosts:
        try:
            baseline = fetch_page(host, site, 25, 0, expand=False)
            selected = host
            print("selected_host", selected)
            break
        except Exception as e:
            print("host_error", host, type(e).__name__, str(e))
    if not selected:
        raise SystemExit("No usable Oracle host")

    print("\n=== WIDE SNAPSHOT WITHOUT EXPAND ===")
    a = fetch_page(selected, site, WIDE_LIMIT, 0, expand=False)
    b = fetch_page(selected, site, WIDE_LIMIT, 0, expand=False)
    compare("wide_noexpand_repeat", a, b)

    total, ids, _, _ = a
    if len(ids) != total:
        print("WIDE_NOT_EXHAUSTIVE", {"retrieved": len(ids), "total": total})
        if ids:
            c = fetch_page(selected, site, WIDE_LIMIT, len(ids), expand=False)
            print("next_page_overlap", len(ids & c[1]))
        return

    print("WIDE_EXHAUSTIVE_NOEXPAND", total)
    print("\n=== WIDE SNAPSHOT WITH LOCATIONS ===")
    c = fetch_page(selected, site, WIDE_LIMIT, 0, expand=True)
    d = fetch_page(selected, site, WIDE_LIMIT, 0, expand=True)
    compare("wide_expand_repeat", c, d)
    ct, ci, cpage, _ = c
    if len(ci) == ct and c[0] == d[0] and c[1] == d[1]:
        missing_locations = 0
        for raw in cpage:
            if isinstance(raw, dict) and not collector.oracle_location(raw):
                missing_locations += 1
        print("WIDE_EXPAND_STABLE_EXHAUSTIVE", {"total": ct, "missing_locations": missing_locations})


if __name__ == "__main__":
    main()
