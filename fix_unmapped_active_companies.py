#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1", "jw2", "jw3", "jw4")


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def dump(name, payload):
    (ROOT / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


batches = load("job_watch_batches.json")
registry = load("companies_job_watch_v2.json")
candidates = load("company_candidates.json")
registry_by_name = {
    row["company"]: row
    for row in registry.get("companies", [])
    if isinstance(row, dict) and row.get("company")
}
records = candidates.setdefault("records", {})
promoted_history = candidates.setdefault("promoted_history", {})
demoted = {}

for batch in BATCHES:
    batch_key = batch.upper()
    members = list(batches["batches"][batch_key]["companies"])
    mapping = load(f"ats_mapping_{batch}.json")
    mapped = {
        row.get("company")
        for row in mapping.get("companies", [])
        if isinstance(row, dict) and row.get("company")
    }
    missing = [name for name in members if name not in mapped]
    if not missing:
        continue
    demoted[batch_key] = missing
    batches["batches"][batch_key]["companies"] = [
        name for name in members if name not in set(missing)
    ]
    for name in missing:
        existing = records.setdefault(
            name,
            {
                "company": name,
                "status": "NEEDS_ATS_MAPPING",
                "recommended_batch": batch_key,
                "priority": None,
                "first_seen": None,
                "last_seen": "2026-10-07",
                "career_url": None,
                "expected_fit": None,
                "compensation_signal": None,
                "sources": {},
            },
        )
        existing["status"] = "NEEDS_ATS_MAPPING"
        existing["recommended_batch"] = existing.get("recommended_batch") or batch_key
        existing["last_seen"] = "2026-10-07"
        existing.setdefault("sources", {})["batch_integrity_20261007"] = {
            "company": name,
            "former_batch": batch_key,
            "reason": "Company was routed as active but had no canonical ATS mapping; it cannot be claimed as monitored until official source access is mapped and validated.",
        }
        previous = promoted_history.pop(name, None)
        if isinstance(previous, dict):
            for source, payload in (previous.get("sources") or {}).items():
                existing["sources"].setdefault(source, payload)
            for field in (
                "priority",
                "first_seen",
                "career_url",
                "expected_fit",
                "compensation_signal",
            ):
                if existing.get(field) is None and previous.get(field) is not None:
                    existing[field] = previous[field]
        registry_row = registry_by_name.pop(name, None)
        if registry_row:
            existing["sources"]["active_registry_before_demote"] = registry_row
            if existing.get("career_url") is None:
                existing["career_url"] = registry_row.get("career_url")

registry["companies"] = [
    row
    for row in registry.get("companies", [])
    if isinstance(row, dict) and row.get("company") in registry_by_name
]
candidates["records"] = dict(
    sorted(records.items(), key=lambda item: item[0].casefold())
)
candidates["promoted_history"] = dict(
    sorted(promoted_history.items(), key=lambda item: item[0].casefold())
)
candidates["updated_at"] = "2026-10-07"

dump("job_watch_batches.json", batches)
dump("companies_job_watch_v2.json", registry)
dump("company_candidates.json", candidates)

active_registry = {row["company"] for row in registry["companies"]}
routed = set()
for batch in BATCHES:
    members = set(batches["batches"][batch.upper()]["companies"])
    routed.update(members)
    mapped_rows = load(f"ats_mapping_{batch}.json")["companies"]
    mapped = [row["company"] for row in mapped_rows]
    if set(mapped) != members or len(mapped) != len(set(mapped)):
        raise RuntimeError(f"{batch}: mapping still differs from active routing")
if active_registry != routed:
    raise RuntimeError(
        f"registry/routing mismatch after demotion: registry-only={sorted(active_registry-routed)}, routing-only={sorted(routed-active_registry)}"
    )
if active_registry & set(candidates["records"]):
    raise RuntimeError("candidate staging still overlaps the active registry")

print("Demoted batch-only companies to NEEDS_ATS_MAPPING:", {k: len(v) for k, v in demoted.items()})
