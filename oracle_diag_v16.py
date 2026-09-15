#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path

import collector

TARGET = "American Express"
PAGE_LIMIT = 200
SORT_BY = "POSTING_DATES_DESC"
SNAPSHOTS = 8


def load_company():
    for batch in ("jw1", "jw2", "jw3", "jw4"):
        data = json.loads(Path(f"ats_mapping_{batch}.json").read_text(encoding="utf-8"))
        for company in data.get("companies", []):
            if company.get("company") == TARGET:
                return company
    raise SystemExit(f"{TARGET} not found")


def fetch_page(host, site, offset):
    endpoint = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    finder = (
        f"findReqs;siteNumber={site},limit={PAGE_LIMIT},offset={offset},"
        f"sortBy={SORT_BY}"
    )
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
    ids = []
    for raw in page:
        if not isinstance(raw, dict):
            continue
        sid = collector.oracle_source_id(raw)
        if not sid:
            raise RuntimeError("stable public ID missing")
        ids.append(sid)
    total = int(root.get("TotalJobsCount"))
    print(
        "PAGE",
        {
            "offset": offset,
            "root_offset": root.get("Offset"),
            "root_limit": root.get("Limit"),
            "root_sort": root.get("SortBy"),
            "total": total,
            "rows": len(page),
            "unique": len(set(ids)),
            "first": ids[:2],
            "last": ids[-2:],
        },
    )
    return total, page, ids


def enumerate_snapshot(host, site):
    expected = None
    rows = []
    seen = set()
    offset = 0
    for page_index in range(10):
        total, page, ids = fetch_page(host, site, offset)
        if expected is None:
            expected = total
        elif total != expected:
            raise RuntimeError(f"TOTAL_CHANGED:{expected}->{total}")
        overlap = seen.intersection(ids)
        if overlap:
            raise RuntimeError(f"PAGE_OVERLAP:{len(overlap)}")
        for raw, sid in zip(page, ids):
            if sid not in seen:
                seen.add(sid)
                rows.append(raw)
        if len(rows) == expected:
            break
        if len(rows) > expected:
            raise RuntimeError(f"OVERFLOW:{len(rows)}>{expected}")
        if not page:
            raise RuntimeError(f"STOPPED_EARLY:{len(rows)}/{expected}")
        offset += len(page)
    else:
        raise RuntimeError("PAGE_LIMIT_EXCEEDED")
    if len(rows) != expected:
        raise RuntimeError(f"COUNT_MISMATCH:{len(rows)}/{expected}")
    ordered_ids = tuple(sorted(seen))
    digest = hashlib.sha256("\n".join(ordered_ids).encode()).hexdigest()[:16]
    missing_location = sum(1 for raw in rows if not collector.oracle_location(raw))
    return {
        "total": expected,
        "ids": ordered_ids,
        "hash": digest,
        "missing_location": missing_location,
    }


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
            total, page, ids = fetch_page(host, site, 0)
            if page and ids:
                selected = host
                break
        except Exception as e:
            print("HOST_ERROR", host, type(e).__name__, str(e))
    if not selected:
        raise SystemExit("No usable Oracle backend host")
    print("selected_host", selected)

    previous = None
    stable_pairs = 0
    for index in range(1, SNAPSHOTS + 1):
        try:
            snap = enumerate_snapshot(selected, site)
            same_as_previous = bool(
                previous
                and previous["total"] == snap["total"]
                and previous["ids"] == snap["ids"]
            )
            print(
                "SNAPSHOT",
                {
                    "n": index,
                    "total": snap["total"],
                    "hash": snap["hash"],
                    "missing_location": snap["missing_location"],
                    "same_as_previous": same_as_previous,
                },
            )
            if same_as_previous:
                stable_pairs += 1
                print("STABLE_PAIR_FOUND", {"n": index, "total": snap["total"], "hash": snap["hash"]})
                break
            previous = snap
        except Exception as e:
            print("SNAPSHOT_ERROR", {"n": index, "error": f"{type(e).__name__}: {e}"})
            previous = None

    print("RESULT", {"stable_pairs": stable_pairs})


if __name__ == "__main__":
    main()
