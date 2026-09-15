#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1", "jw2", "jw3", "jw4")


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_family(value: str | None) -> str:
    s = (value or "unknown").strip()
    low = s.casefold()
    if "oracle recruiting cloud" in low or "oracle hcm" in low or "oracle fusion" in low:
        return "Oracle Recruiting Cloud / HCM"
    if "phenom" in low:
        return "Phenom"
    if "icims" in low:
        return "iCIMS"
    if "taleo" in low:
        return "Oracle Taleo"
    if "successfactors" in low or "jobs2web" in low:
        return "SAP SuccessFactors / jobs2web"
    if "workday" in low:
        return "Workday"
    if "smartrecruiters" in low:
        return "SmartRecruiters"
    if "greenhouse" in low:
        return "Greenhouse"
    if "lever" in low:
        return "Lever"
    if "ashby" in low:
        return "Ashby"
    if "workable" in low:
        return "Workable"
    if "teamtailor" in low:
        return "Teamtailor"
    if "recruitee" in low:
        return "Recruitee"
    if "jobvite" in low:
        return "Jobvite"
    if "successfactors" in low:
        return "SAP SuccessFactors / jobs2web"
    if "custom" in low or "unresolved" in low or "proprietary" in low:
        return "Custom / unresolved"
    return re.sub(r"\s+", " ", s)


def main() -> int:
    grouped = defaultdict(list)
    level_counts = Counter()
    total = 0
    full_possible = 0

    for batch in BATCHES:
        current = read_json(ROOT / f"current_jobs_{batch}.json")
        mapping = read_json(ROOT / f"ats_mapping_{batch}.json")
        by_name = {c.get("company"): c for c in mapping.get("companies", [])}
        for row in current.get("companies", []):
            if row.get("coverage") != "NOT_CHECKED":
                continue
            total += 1
            name = row.get("company")
            mapped = by_name.get(name, {})
            verification = mapped.get("verification") or {}
            level = verification.get("level") or row.get("mapping_level") or "UNKNOWN"
            level_counts[level] += 1
            if verification.get("full_inventory_possible") is True:
                full_possible += 1
            family = normalize_family((mapped.get("ats") or {}).get("family") or row.get("ats_family"))
            grouped[family].append(
                {
                    "batch": batch.upper(),
                    "company": name,
                    "level": level,
                    "full_inventory_possible": verification.get("full_inventory_possible"),
                    "family_raw": (mapped.get("ats") or {}).get("family") or row.get("ats_family"),
                    "inventory_url": (mapped.get("ats") or {}).get("inventory_url") or row.get("source_url"),
                    "reason": row.get("reason"),
                }
            )

    print(f"NOT_CHECKED total: {total}")
    print(f"NOT_CHECKED with mapping full_inventory_possible=true: {full_possible}")
    print("Mapping levels:", dict(level_counts))
    print()
    print("Families by descending NOT_CHECKED count:")
    for family, rows in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0].casefold())):
        full = sum(1 for x in rows if x["full_inventory_possible"] is True)
        levels = Counter(x["level"] for x in rows)
        print(f"\n{family}: {len(rows)} NOT_CHECKED | FULL-possible={full} | levels={dict(levels)}")
        for x in rows:
            print(
                f"  - {x['batch']} | {x['company']} | {x['level']} | "
                f"full={x['full_inventory_possible']} | {x['family_raw']} | {x['inventory_url']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
