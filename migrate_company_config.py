#!/usr/bin/env python3
import json
from pathlib import Path

R = Path(__file__).resolve().parent
B = ("jw1", "jw2", "jw3", "jw4")
TODAY = "2026-10-07"


def load(name):
    return json.loads((R / name).read_text(encoding="utf-8"))


def dump(name, payload):
    (R / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def replace_once(name, old, new):
    path = R / name
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"{name}: expected exactly one match for {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


overlay = load("ats_mapping_expansion_20261004.json")
batches = load("job_watch_batches.json")
active = {
    company
    for payload in batches["batches"].values()
    for company in payload["companies"]
}

# 1) Canonical active-employer registry.
base = load("companies_job_watch_v2.json")
additions = load("watchlist_additions.json")
rows = list(base.get("companies") or []) + list(additions.get("companies") or [])
names = [row.get("company") for row in rows]
if len(names) != len(set(names)):
    raise RuntimeError("duplicate company while merging company registry")
by_name = {row["company"]: row for row in rows}
next_id = max(
    [row.get("id", 0) for row in rows if isinstance(row.get("id"), int)] or [0]
) + 1

for batch in B:
    for item in (overlay.get("batches") or {}).get(batch, []):
        name = item.get("company")
        if not name or name in by_name:
            continue
        ats = item.get("ats") or {}
        verification = item.get("verification") or {}
        locations = verification.get("locations") or []
        row = {
            "id": next_id,
            "company": name,
            "tier": None,
            "sector": None,
            "locations": {
                "milan": "Yes" if any(str(v).casefold() in {"milan", "milano"} for v in locations) else "Possible",
                "rome": "Yes" if any(str(v).casefold() in {"rome", "roma"} for v in locations) else "Possible",
                "london": "Yes" if any("london" in str(v).casefold() for v in locations) else "No",
            },
            "career_url": ats.get("career_site") or ats.get("inventory_url"),
            "portal_ats": ats.get("family"),
            "monitoring_priority": "Every run",
            "target_roles": "Use global Job Watch role policy; employer-specific metadata pending curation.",
            "why": "Active employer promoted from the 2026-10-04 monitored expansion; technical evidence is retained in the canonical ATS mapping.",
            "exclusions": "Use global Job Watch exclusions and semantic review rules.",
            "compensation_potential": "TBD",
            "accessibility": verification.get("level") or "TBD",
            "metadata_status": "ACTIVE_TECHNICAL_PROMOTION_PENDING_BUSINESS_ENRICHMENT",
            "added_from": "ats_mapping_expansion_20261004.json",
        }
        if any("luxemb" in str(v).casefold() for v in locations):
            row["locations"]["luxembourg"] = "Yes"
        rows.append(row)
        by_name[name] = row
        next_id += 1

base["version"] = "2.1"
base["updated"] = TODAY
base["authority"] = {
    "scope": "Canonical active-employer business metadata registry.",
    "routing_authority": "job_watch_batches.json",
    "technical_access_authority": "ats_mapping_jw1.json ... ats_mapping_jw4.json",
    "candidate_staging_authority": "company_candidates.json",
    "research_watchlist": "extra_company_watchlist.json",
    "metadata_note": "career_url and portal_ats are retained as descriptive metadata; runtime ATS endpoints and pagination truth live only in ats_mapping_jw*.json.",
}
base["companies"] = rows
dump("companies_job_watch_v2.json", base)

# 2) One operational candidate staging registry, preserving every source row.
expansion = load("extra_company_watchlist_expansion_20261004.json")
discovery = load("discovery_candidates.json")
candidates = {}
promoted = {}
monitored_reviews = []


def add_candidate(source, row, default_status):
    if not isinstance(row, dict) or not row.get("company"):
        return
    name = row["company"]
    store = promoted if name in active else candidates
    record = store.setdefault(
        name,
        {
            "company": name,
            "status": row.get("status") or default_status,
            "recommended_batch": row.get("recommended_batch"),
            "priority": row.get("priority"),
            "first_seen": row.get("first_seen"),
            "last_seen": row.get("last_seen"),
            "career_url": row.get("career_url"),
            "expected_fit": row.get("expected_fit"),
            "compensation_signal": row.get("compensation_signal"),
            "sources": {},
        },
    )
    record["sources"][source] = row
    for field in (
        "status",
        "recommended_batch",
        "priority",
        "first_seen",
        "last_seen",
        "career_url",
        "expected_fit",
        "compensation_signal",
    ):
        if record.get(field) is None and row.get(field) is not None:
            record[field] = row[field]


for section, value in expansion.items():
    if not isinstance(value, list):
        continue
    for row in value:
        if not isinstance(row, dict) or not row.get("company"):
            continue
        if section == "already_monitored_priority_review":
            monitored_reviews.append(row)
        else:
            add_candidate(
                f"employer_expansion_20261004:{section}", row, "STAGED_RESEARCH"
            )

for key, row in (discovery.get("records") or {}).items():
    if isinstance(row, dict):
        add_candidate(
            "autonomous_discovery",
            {"company": row.get("company") or key, **row},
            "STAGED_DISCOVERY",
        )

dump(
    "company_candidates.json",
    {
        "version": "1.0",
        "updated_at": TODAY,
        "purpose": "Single operational staging registry for employers not yet in the active Job Watch company universe.",
        "authority": {
            "scope": "candidate staging and promotion evidence",
            "active_company_registry": "companies_job_watch_v2.json",
            "routing": "job_watch_batches.json",
            "technical_access": "ats_mapping_jw1.json ... ats_mapping_jw4.json",
            "research_watchlist": "extra_company_watchlist.json remains a separate curated research/radar file, not a staging authority.",
        },
        "source_policies": {
            "employer_expansion_20261004": {
                "purpose": expansion.get("purpose"),
                "policy": expansion.get("policy"),
            },
            "autonomous_discovery": {"description": discovery.get("description")},
        },
        "records": dict(sorted(candidates.items(), key=lambda item: item[0].casefold())),
        "promoted_history": dict(sorted(promoted.items(), key=lambda item: item[0].casefold())),
        "monitored_reviews": monitored_reviews,
    },
)

# 3) Promote the dated ATS overlay into canonical per-batch mappings.
alias = (batches.get("coverage_aliases") or {}).get("Telespazio")
if not alias or alias.get("covered_by") != "Leonardo":
    raise RuntimeError("Telespazio alias is not preserved in job_watch_batches.json")

for batch in B:
    mapping = load(f"ats_mapping_{batch}.json")
    mapped = list(mapping.get("companies") or [])
    existing = {row.get("company") for row in mapped}
    additions = (overlay.get("batches") or {}).get(batch, [])
    duplicates = existing & {row.get("company") for row in additions}
    if duplicates:
        raise RuntimeError(f"{batch}: overlay duplicates canonical mapping: {sorted(duplicates)}")
    for row in additions:
        if row.get("company") == "Opella":
            row = json.loads(json.dumps(row))
            row["ats"] = {
                **(row.get("ats") or {}),
                "family": "Custom official careers / Workday frontend",
                "career_site": "https://www.opella.com/en/careers",
                "inventory_url": "https://www.opella.com/en/careers",
                "public_api_or_feed": None,
            }
            row["verification"] = {
                **(row.get("verification") or {}),
                "level": "PARTIAL",
                "method": "official_career_site_dynamic",
                "location_filter_supported": True,
                "locations": ["Italy", "Milan", "Milano", "Rome", "Roma", "London"],
                "pagination": "Official careers page; GitHub runner cannot certify the Workday CXS inventory because the endpoint returns HTTP 403.",
                "total_count_available": False,
                "full_inventory_possible": False,
            }
            row["job_watch_method"] = {
                "primary": "Probe Opella's official careers page and retain official links exposed by the live site.",
                "fallback": "Keep PARTIAL coverage until the Workday CXS inventory is accessible and exhaustively reconcilable.",
            }
            row["limitations"] = list(row.get("limitations") or []) + [
                "2026-10-04 production evidence: Opella Workday CXS returned HTTP 403 from GitHub Actions."
            ]
        mapped.append(row)
    mapping["companies"] = mapped
    mapping["last_mapped"] = max(str(mapping.get("last_mapped") or ""), "2026-10-04")
    mapping["summary"] = {"companies_analyzed": len(mapped)}
    for level in ("FULL", "STRONG", "PARTIAL", "OPAQUE"):
        mapping["summary"][level] = sum(
            str(((row.get("verification") or {}).get("level") or "")).upper() == level
            for row in mapped
        )
    notes = list(mapping.get("notes") or [])
    note = "The 2026-10-04 ATS expansion is now part of this canonical mapping; no runtime overlay is required."
    if note not in notes:
        notes.append(note)
    mapping["notes"] = notes
    dump(f"ats_mapping_{batch}.json", mapping)

# 4) Promote runtime-only expansion fixes into canonical code/state.
collector_path = R / "collector.py"
collector = collector_path.read_text(encoding="utf-8")
anchor = '    if re.search(r"\\bLondon\\b.*\\bCanada\\b", s, re.I):\n        return False\n'
insertion = anchor + '    if re.search(r"\\bEast\\s+London\\b", s, re.I) and re.search(r"\\b(?:ZAF|South\\s+Africa)\\b", s, re.I):\n        return False\n'
if insertion not in collector:
    if collector.count(anchor) != 1:
        raise RuntimeError("collector.py: London/Canada matcher anchor changed")
    collector_path.write_text(collector.replace(anchor, insertion, 1), encoding="utf-8")

cache = load("semantic_jd_cache_jw2.json")
cache_changed = False
for key, row in list((cache.get("records") or {}).items()):
    error = str((row or {}).get("error") or "").casefold()
    if (
        isinstance(row, dict)
        and row.get("status") == "FAILED"
        and row.get("company") in {"Experian", "Contentsquare"}
        and ("http 400" in error or "no lever tenant" in error)
    ):
        cache["records"].pop(key, None)
        cache_changed = True
if cache_changed:
    dump("semantic_jd_cache_jw2.json", cache)

# 5) Update operational references to canonical files.
replace_once(
    "job_watch.py",
    "global_names = ('job_watch_rules.json','job_watch_batches.json','companies_job_watch_v2.json','watchlist_additions.json','user_job_decisions.json')",
    "global_names = ('job_watch_rules.json','job_watch_batches.json','companies_job_watch_v2.json','company_candidates.json','user_job_decisions.json')",
)
replace_once(
    "job_watch.py",
    "if filename in {'companies_job_watch_v2.json','watchlist_additions.json'} and not isinstance(data.get('companies'),list): raise ValueError('Global company universe invalid')",
    "if filename == 'companies_job_watch_v2.json' and not isinstance(data.get('companies'),list): raise ValueError('Global company universe invalid')\n            if filename == 'company_candidates.json' and not isinstance(data.get('records'),dict): raise ValueError('Global candidate staging invalid')",
)

validator_path = R / "validate_job_watch_inputs.py"
validator = validator_path.read_text(encoding="utf-8")
old_config = '    "companies_job_watch_v2.json",\n    "watchlist_additions.json",\n    "discovery_candidates.json",\n'
new_config = '    "companies_job_watch_v2.json",\n    "company_candidates.json",\n'
if old_config not in validator:
    raise RuntimeError("validate_job_watch_inputs.py: config anchor changed")
validator = validator.replace(old_config, new_config, 1)
validation_anchor = "for name in REQUIRED_CONFIG:\n    load(name)\n\n"
validation_extra = (
    "for name in REQUIRED_CONFIG:\n    load(name)\n\n"
    "companies = load(\"companies_job_watch_v2.json\")\n"
    "if not isinstance(companies.get(\"companies\"), list):\n"
    "    raise SystemExit(\"INPUT ERROR: companies_job_watch_v2.json companies must be a list\")\n"
    "company_names = [r.get(\"company\") for r in companies[\"companies\"] if isinstance(r, dict)]\n"
    "if len(company_names) != len(set(company_names)) or any(not x for x in company_names):\n"
    "    raise SystemExit(\"INPUT ERROR: active company registry contains blank/duplicate names\")\n"
    "candidates = load(\"company_candidates.json\")\n"
    "if not isinstance(candidates.get(\"records\"), dict):\n"
    "    raise SystemExit(\"INPUT ERROR: company_candidates.json records must be an object\")\n"
    "for key, row in candidates[\"records\"].items():\n"
    "    if not isinstance(key, str) or not isinstance(row, dict) or row.get(\"company\") != key:\n"
    "        raise SystemExit(f\"INPUT ERROR: invalid company candidate {key}\")\n\n"
)
if validation_anchor not in validator:
    raise RuntimeError("validate_job_watch_inputs.py: validation anchor changed")
validator_path.write_text(
    validator.replace(validation_anchor, validation_extra, 1), encoding="utf-8"
)

# Simplify preflight: canonical registry and mappings are now the only active universe.
preflight_path = R / "preflight_job_watch.py"
preflight = preflight_path.read_text(encoding="utf-8")
preflight = preflight.replace("EXPANSION_MAPPING = 'ats_mapping_expansion_20261004.json'\n", "")
preflight = preflight.replace(
    "'user_job_decisions.json', 'watchlist_additions.json', 'discovery_candidates.json','pipeline_contract.json'",
    "'user_job_decisions.json', 'company_candidates.json','pipeline_contract.json'",
)
block_start = preflight.index("    # The 2026-10-04 expansion is an append-only mapping overlay.")
block_end = preflight.index("    seen = set()", block_start)
preflight = preflight[:block_start] + preflight[block_end:]
universe_old = (
    "    universe = {r.get('company') for name in ('companies_job_watch_v2.json', 'watchlist_additions.json') for r in data.get(name, {}).get('companies', [])}\n"
    "    universe.update(name for names in expansion_by_batch.values() for name in names if name)\n"
)
universe_new = "    universe = {r.get('company') for r in data.get('companies_job_watch_v2.json', {}).get('companies', []) if isinstance(r,dict) and r.get('company')}\n"
if universe_old not in preflight:
    raise RuntimeError("preflight_job_watch.py: universe block changed")
preflight = preflight.replace(universe_old, universe_new, 1)
mapping_old = (
    "                canonical = [r.get('company') for r in item['companies']]\n"
    "                additions = expansion_by_batch.get(b, [])\n"
    "                if set(canonical) & set(additions):\n"
    "                    errors.append(f'{b}: expansion duplicates canonical mapping')\n"
    "                mapped = canonical + additions\n"
    "                if set(mapped) != set(members) or len(mapped) != len(set(mapped)):\n"
    "                    errors.append(f'{b}: mapping does not match batch')\n"
)
mapping_new = (
    "                mapped = [r.get('company') for r in item['companies']]\n"
    "                if set(mapped) != set(members) or len(mapped) != len(set(mapped)):\n"
    "                    errors.append(f'{b}: mapping does not match batch')\n"
)
if mapping_old not in preflight:
    raise RuntimeError("preflight_job_watch.py: mapping block changed")
preflight_path.write_text(preflight.replace(mapping_old, mapping_new, 1), encoding="utf-8")

rules = load("job_watch_rules.json")
policy = rules.get("company_self_improvement_policy") or {}
policy["staging_file"] = "company_candidates.json"
policy["promotion_action"] = "On promotion, add the company to companies_job_watch_v2.json and the correct job_watch_batches.json batch, then create/update the canonical batch ATS mapping. If ATS cannot yet be mapped safely, keep it in company_candidates.json."
policy["cadence"] = "Weekly; company_candidates.json is the single manual staging registry consumed by ChatGPT, not an automatic collector."
rules["company_self_improvement_policy"] = policy
rules["configuration_authority"] = {
    "active_employer_business_metadata": "companies_job_watch_v2.json",
    "batch_routing": "job_watch_batches.json",
    "candidate_staging": "company_candidates.json",
    "curated_employer_research_radar": "extra_company_watchlist.json",
    "technical_ats_access": "ats_mapping_jw1.json ... ats_mapping_jw4.json",
    "principle": "Each concept has one operational authority; descriptive copies do not override it.",
}
rules["updated"] = TODAY
dump("job_watch_rules.json", rules)

for name in ("DAILY.md", "MAINTENANCE.md"):
    path = R / name
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "discovery_candidates.json", "company_candidates.json"
        ),
        encoding="utf-8",
    )

collect_path = R / ".github/workflows/collect_jobs.yml"
collect_path.write_text(
    collect_path.read_text(encoding="utf-8").replace(
        "job_watch_expansion.py", "job_watch.py"
    ),
    encoding="utf-8",
)
sync_path = R / ".github/workflows/sync_semantic_state.yml"
sync = sync_path.read_text(encoding="utf-8")
sync = sync.replace('      - "watchlist_additions.json"\n', "")
sync = sync.replace(
    '      - "discovery_candidates.json"\n',
    '      - "company_candidates.json"\n',
)
sync_path.write_text(sync, encoding="utf-8")

# 6) Remove historical operational layers.
for name in (
    "watchlist_additions.json",
    "extra_company_watchlist_expansion_20261004.json",
    "discovery_candidates.json",
    "ats_mapping_expansion_20261004.json",
    "job_watch_expansion.py",
    "test_job_watch_expansion.py",
):
    path = R / name
    if path.exists():
        path.unlink()

# Hard invariants before this migration is allowed to commit.
registry = {
    row["company"] for row in load("companies_job_watch_v2.json")["companies"]
}
routed = set()
for batch in B:
    members = set(batches["batches"][batch.upper()]["companies"])
    routed.update(members)
    mapped = [
        row["company"] for row in load(f"ats_mapping_{batch}.json")["companies"]
    ]
    if set(mapped) != members or len(mapped) != len(set(mapped)):
        raise RuntimeError(f"{batch}: canonical ATS mapping does not match routing")
if registry != routed:
    raise RuntimeError(
        f"registry/routing mismatch: registry-only={sorted(registry-routed)}, routing-only={sorted(routed-registry)}"
    )
if registry & set(load("company_candidates.json")["records"]):
    raise RuntimeError("active employers remain in candidate staging")

print("Company configuration migration complete.")
