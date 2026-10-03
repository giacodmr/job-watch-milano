#!/usr/bin/env python3
"""Apply fail-closed semantic-state guardrails after sync_analysis_state.py."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1", "jw2", "jw3", "jw4")
SEMANTIC_METHODS = {
    "chatgpt_semantic",
    "chatgpt_semantic_title_metadata",
    "chatgpt_semantic_full_jd",
}
REQUIRED_SEMANTIC_FIELDS = (
    "fingerprint",
    "analysis_status",
    "analysis_method",
    "fit_score",
    "experience_required",
    "mandatory_years_experience",
    "preferred_years_experience",
    "mandatory_vs_preferred_requirements",
    "people_management_required",
    "individual_contributor_possible",
    "decision_scope_and_ownership",
    "role_level_assessment",
    "seniority_evidence",
    "final_experience_status",
    "salary",
    "salary_source",
    "reportable",
    "rationale",
    "analyzed_at",
)
SENIOR_RE = re.compile(r"\b(manager|senior|lead|head|director)\b", re.I)
PROTECTED_RE = re.compile(
    r"(?:l\.?\s*68\s*/\s*99|law\s*68\s*/\s*99|protected categor|categorie protette|categoria protetta)",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(name: str, default=None):
    path = ROOT / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dump(name: str, payload) -> None:
    (ROOT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def semantic_decision_valid(decision: dict, rec: dict) -> tuple[bool, str | None]:
    if not isinstance(decision, dict):
        return False, "semantic_decision_missing"
    missing = [field for field in REQUIRED_SEMANTIC_FIELDS if field not in decision]
    if missing:
        return False, "semantic_decision_missing_fields:" + ",".join(missing)
    if decision.get("fingerprint") != rec.get("fingerprint"):
        return False, "semantic_decision_fingerprint_mismatch"
    if decision.get("analysis_status") != "ANALYZED":
        return False, "semantic_decision_not_analyzed"
    if decision.get("analysis_method") not in SEMANTIC_METHODS:
        return False, "semantic_decision_invalid_method"
    if not isinstance(decision.get("fit_score"), (int, float)):
        return False, "semantic_decision_fit_score_invalid"
    if not isinstance(decision.get("reportable"), bool):
        return False, "semantic_decision_reportable_invalid"
    if not str(decision.get("rationale") or "").strip():
        return False, "semantic_decision_rationale_missing"
    if decision.get("final_experience_status") not in {"TARGET_0_5", "REVIEW_UNCLEAR", "OUT_GT5_MANDATORY"}:
        return False, "semantic_decision_experience_status_invalid"
    if decision.get("role_level_assessment") not in {"ENTRY_JUNIOR", "EARLY_MID", "MID", "SENIOR", "UNCLEAR"}:
        return False, "semantic_decision_role_level_invalid"
    if not str(decision.get("seniority_evidence") or "").strip():
        return False, "semantic_decision_seniority_evidence_missing"

    title = str(rec.get("title") or "")
    protected = bool(PROTECTED_RE.search(title))
    l68_status = decision.get("l68_status")
    if l68_status is not None and l68_status not in {"NO", "PREFERRED", "REQUIRED", "RESERVED", "INVITED", "AMBIGUOUS"}:
        return False, "semantic_decision_l68_status_invalid"
    protected_semantics = protected or (l68_status not in {None, "NO"})
    if rec.get("priority_company") or SENIOR_RE.search(title) or protected_semantics:
        if decision.get("analysis_method") != "chatgpt_semantic_full_jd":
            return False, "full_jd_required"
    if protected_semantics:
        if not isinstance(decision.get("ordinary_twin_found"), bool):
            return False, "ordinary_twin_check_missing"
    if l68_status in {"REQUIRED", "RESERVED"} and decision.get("reportable") is True:
        return False, "protected_required_role_cannot_be_reportable_without_confirmed_eligibility"
    return True, None


def needs_applied_review(rec: dict) -> bool:
    return bool(
        rec.get("current_open")
        and rec.get("user_decision") == "APPLIED"
        and rec.get("current_status") == "UPDATED"
        and rec.get("analysis_method") == "user_decision_applied"
    )


def mark_pending(rec: dict, reason: str) -> None:
    rec.update({
        "needs_analysis": True,
        "analysis_status": "PENDING",
        "analysis_method": None,
        "hard_exclusion_reason": None,
        "fit_score": None,
        "experience_required": None,
        "salary": None,
        "salary_source": None,
        "reportable": None,
        "rationale": None,
        "analyzed_at": None,
        "guardrail_reason": reason,
    })


def queue_row(key: str, rec: dict) -> dict:
    return {
        "job_key": key,
        "company": rec.get("company"),
        "source_id": rec.get("source_id"),
        "title": rec.get("title"),
        "location": rec.get("location"),
        "target_city": rec.get("target_city"),
        "priority_company": rec.get("priority_company"),
        "role_family": rec.get("role_family"),
        "job_category": rec.get("job_category"),
        "current_status": rec.get("current_status"),
        "threshold": rec.get("threshold"),
        "canonical_url": rec.get("canonical_url"),
        "apply_url": rec.get("apply_url"),
        "fingerprint": rec.get("fingerprint"),
        "first_seen_at": rec.get("first_seen_at"),
        "user_decision": rec.get("user_decision"),
        "user_decision_reason": rec.get("user_decision_reason"),
        "user_decision_stale": rec.get("user_decision_stale"),
        "never_reviewed": rec.get("analysis_status") != "ANALYZED",
        "never_surfaced": not bool(rec.get("surfaced_at")),
        "amazon_semantic_source": "amazon_target_check.json" if rec.get("company") == "Amazon" and rec.get("priority_company") else None,
        "required_years_mentions": rec.get("required_years_mentions"),
        "preferred_years_mentions": rec.get("preferred_years_mentions"),
        "required_min_years": rec.get("required_min_years"),
        "experience_status_hint": rec.get("experience_status_hint"),
        "experience_reason_hint": rec.get("experience_reason_hint"),
        "guardrail_reason": rec.get("guardrail_reason"),
        "applied_material_update": bool(rec.get("applied_material_update")),
    }


def queue_sort_key(row: dict):
    status_rank = {"NEW": 0, "UPDATED": 1, "STILL_OPEN": 2}
    city = (row.get("target_city") or row.get("location") or "").casefold()
    if "milan" in city or "milano" in city:
        city_rank = 0
    elif "rome" in city or "roma" in city:
        city_rank = 1
    elif "luxembourg" in city or "luxemburg" in city:
        city_rank = 2
    elif "london" in city:
        city_rank = 3
    else:
        city_rank = 4
    return (
        0 if row.get("user_decision") in {"TO_REVIEW", "INTERESTED"} else 1,
        0 if row.get("applied_material_update") else 1,
        0 if row.get("priority_company") else 1,
        status_rank.get(row.get("current_status"), 9),
        city_rank,
        row.get("first_seen_at") or "",
        (row.get("company") or "").casefold(),
        (row.get("title") or "").casefold(),
    )


def harden_batch(batch: str) -> dict:
    state_name = f"analysis_results_{batch}.json"
    queue_name = f"semantic_queue_{batch}.json"
    decision_name = f"semantic_decisions_{batch}.json"
    state = load(state_name, {"records": {}}) or {"records": {}}
    queue = load(queue_name, {"records": []}) or {"records": []}
    decisions = (load(decision_name, {"records": {}}) or {}).get("records") or {}
    records = state.get("records") or {}

    schema_resets = 0
    applied_updates = 0
    for key, rec in records.items():
        if not rec.get("current_open"):
            continue
        rec.pop("guardrail_reason", None)
        rec["applied_material_update"] = False

        if rec.get("analysis_method") in SEMANTIC_METHODS:
            valid, reason = semantic_decision_valid(decisions.get(key) or {}, rec)
            if not valid:
                mark_pending(rec, reason or "semantic_decision_invalid")
                schema_resets += 1

        if needs_applied_review(rec):
            mark_pending(rec, "applied_vacancy_materially_updated")
            rec["applied_material_update"] = True
            applied_updates += 1

    pending = [(key, rec) for key, rec in records.items() if rec.get("current_open") and rec.get("needs_analysis")]
    qrecords = [queue_row(key, rec) for key, rec in pending]
    qrecords.sort(key=queue_sort_key)

    summary = state.setdefault("summary", {})
    open_records = [rec for rec in records.values() if rec.get("current_open")]
    analyzed = [rec for rec in open_records if rec.get("analysis_status") == "ANALYZED" and not rec.get("needs_analysis")]
    summary["pending_analysis"] = len(pending)
    summary["analyzed_current"] = len(analyzed)

    queue["records"] = qrecords
    queue["pending_count"] = len(qrecords)
    queue["guardrails_applied_at"] = utc_now()
    queue["guardrail_schema_resets"] = schema_resets
    queue["guardrail_applied_updates"] = applied_updates

    dump(state_name, state)
    dump(queue_name, queue)
    return {"batch": batch.upper(), "schema_resets": schema_resets, "applied_updates": applied_updates, "pending": len(qrecords)}


def main() -> int:
    results = [harden_batch(batch) for batch in BATCHES]
    for row in results:
        print(
            f"{row['batch']} guardrails: schema_resets={row['schema_resets']} "
            f"applied_updates={row['applied_updates']} pending={row['pending']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
