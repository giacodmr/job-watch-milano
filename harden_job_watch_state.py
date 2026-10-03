#!/usr/bin/env python3
"""Shared semantic validation and queue projection; sync applies these in one pass."""
from __future__ import annotations

import re

SEMANTIC_METHODS = {
    "chatgpt_semantic",
    "chatgpt_semantic_title_metadata",
    "chatgpt_semantic_full_jd",
    "chatgpt_semantic_triage",
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


def semantic_decision_valid(decision: dict, rec: dict) -> tuple[bool, str | None]:
    if not isinstance(decision, dict):
        return False, "semantic_decision_missing"
    if decision.get("analysis_method") == "chatgpt_semantic_triage":
        required = ("fingerprint", "analysis_status", "analysis_method", "decision", "reason", "rationale", "analyzed_at")
        if any(not decision.get(f) for f in required):
            return False, "triage_missing_fields"
        if decision["fingerprint"] != rec.get("fingerprint") or decision["analysis_status"] != "ANALYZED":
            return False, "triage_stale_or_pending"
        if decision["decision"] != "REJECT" or decision["reason"] not in {"WRONG_FUNCTION", "WRONG_LOCATION", "PURE_SALES", "TOO_TECHNICAL"}:
            return False, "triage_must_be_obvious_rejection"
        if rec.get("priority_company") or SENIOR_RE.search(str(rec.get("title") or "")) or PROTECTED_RE.search(str(rec.get("title") or "")) or decision.get("l68_status") not in {None, "NO"}:
            return False, "full_jd_required"
        if decision.get("reportable") is True:
            return False, "triage_cannot_be_reportable"
        return True, None
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
        and (rec.get("current_status") == "UPDATED" or rec.get("applied_material_update"))
        and rec.get("analysis_method") == "user_decision_applied"
    )


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
