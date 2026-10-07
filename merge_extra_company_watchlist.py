#!/usr/bin/env python3
"""One-time migration: fold extra_company_watchlist.json into company_candidates.json."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CANDIDATES = ROOT / "company_candidates.json"
EXTRA = ROOT / "extra_company_watchlist.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


candidates = load(CANDIDATES)
extra = load(EXTRA)

candidates["version"] = "1.1"
candidates["updated_at"] = "2026-10-07"
candidates["purpose"] = (
    "Single non-active employer registry for research evidence, candidate staging, "
    "promotion readiness and technical-access gaps before active JW1-JW4 monitoring."
)
authority = candidates.setdefault("authority", {})
authority["scope"] = "non-active employer research, candidate staging and promotion evidence"
authority["research_watchlist"] = (
    "Merged into company_candidates.json; status and source evidence distinguish radar-only, "
    "promotion-ready and ATS-mapping candidates."
)

source_policies = candidates.setdefault("source_policies", {})
source_policies["extra_company_watchlist_20261004"] = {
    "purpose": extra.get("purpose"),
    "policy": extra.get("policy", {}),
}

records = candidates.setdefault("records", {})
status_rank = {
    "STAGED_DISCOVERY": 1,
    "WATCH_EXTRA": 2,
    "PROMOTION_CANDIDATE": 3,
    "NEEDS_ATS_MAPPING": 4,
}
merged_names = []
for row in extra.get("companies", []):
    name = row.get("company")
    if not name:
        continue
    rec = records.setdefault(name, {
        "company": name,
        "status": row.get("status") or "WATCH_EXTRA",
        "recommended_batch": row.get("recommended_batch"),
        "priority": row.get("priority"),
        "first_seen": None,
        "last_seen": "2026-10-04",
        "career_url": row.get("career_url"),
        "expected_fit": None,
        "compensation_signal": row.get("compensation_signal"),
        "sources": {},
    })
    current_status = rec.get("status")
    new_status = row.get("status")
    if status_rank.get(new_status, 0) > status_rank.get(current_status, 0):
        rec["status"] = new_status
    if not rec.get("recommended_batch") and row.get("recommended_batch"):
        rec["recommended_batch"] = row["recommended_batch"]
    if not rec.get("career_url") and row.get("career_url"):
        rec["career_url"] = row["career_url"]
    if not rec.get("compensation_signal") and row.get("compensation_signal"):
        rec["compensation_signal"] = row["compensation_signal"]
    priorities = [p for p in (rec.get("priority"), row.get("priority")) if isinstance(p, int)]
    if priorities:
        rec["priority"] = min(priorities)
    for field in ("city", "role_evidence", "seniority_signal"):
        if row.get(field) and not rec.get(field):
            rec[field] = row[field]
    rec.setdefault("sources", {})["extra_company_watchlist_20261004"] = row
    merged_names.append(name)

existing_rejected = {
    row.get("company"): row
    for row in candidates.get("researched_not_added", [])
    if isinstance(row, dict) and row.get("company")
}
for row in extra.get("researched_not_added", []):
    if isinstance(row, dict) and row.get("company"):
        existing_rejected[row["company"]] = row
candidates["researched_not_added"] = [
    existing_rejected[name] for name in sorted(existing_rejected, key=str.casefold)
]
candidates["records"] = dict(sorted(records.items(), key=lambda item: item[0].casefold()))

dump(CANDIDATES, candidates)
EXTRA.unlink()

# Fail closed on data loss: every former radar company must now exist with its full source row.
reloaded = load(CANDIDATES)
for row in extra.get("companies", []):
    name = row["company"]
    merged = reloaded["records"].get(name)
    if not merged or merged.get("sources", {}).get("extra_company_watchlist_20261004") != row:
        raise RuntimeError(f"Lost extra-company evidence for {name}")
for row in extra.get("researched_not_added", []):
    if row not in reloaded.get("researched_not_added", []):
        raise RuntimeError(f"Lost researched-not-added evidence for {row.get('company')}")

print(f"Merged {len(merged_names)} radar companies and {len(extra.get('researched_not_added', []))} researched-not-added records.")
