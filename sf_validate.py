#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import collector

ROOT = Path(__file__).resolve().parent
TARGETS = {
    "Intesa Sanpaolo", "Worldline", "Swiss Re", "Capgemini Invent", "Mundys",
    "E.ON Italia", "Italgas", "Bolton Group", "Boehringer Ingelheim",
}


def targets():
    out = []
    for batch in ("jw1", "jw2", "jw3", "jw4"):
        data = json.loads((ROOT / f"ats_mapping_{batch}.json").read_text(encoding="utf-8"))
        for company in data.get("companies", []):
            if company.get("company") in TARGETS:
                out.append(company)
    return out


def main():
    verified = 0
    for company in targets():
        name = company.get("company")
        try:
            result = collector.collect_successfactors(company)
            verified += int(result.get("coverage") == "VERIFIED")
            print(json.dumps({
                "company": name,
                "coverage": result.get("coverage"),
                "inventory_count": result.get("inventory_count"),
                "target_jobs": len(result.get("jobs") or []),
                "source_url": result.get("source_url"),
            }, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"company": name, "coverage": "NOT_CHECKED", "reason": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
    print(json.dumps({"targeted_verified": verified, "targeted_total": len(TARGETS)}))


if __name__ == "__main__":
    main()
