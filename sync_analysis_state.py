#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1", "jw2", "jw3", "jw4")
OPEN_STATUSES = {"NEW", "STILL_OPEN", "UPDATED"}

# Conservative, unambiguous title-only exclusions. There is deliberately no
# positive-title whitelist and no Manager/Senior/Lead exclusion.
HARD_EXCLUSION_RULES = (
    ("internship", re.compile(r"\b(intern|internship|stage|apprentice|apprenticeship)\b", re.I)),
    ("software_engineering", re.compile(r"\b(software|backend|frontend|front-end|full[ -]?stack|mobile|platform|systems?)\s+(engineer|developer)\b|\bdeveloper\b", re.I)),
    ("technical_engineering", re.compile(r"\b(data engineer|machine learning engineer|ml engineer|security engineer|network engineer|cloud engineer|devops|site reliability engineer|solutions architect|solution architect|enterprise architect|data architect)\b", re.I)),
    ("data_science", re.compile(r"\b(data scientist|applied scientist|research scientist|machine learning scientist)\b", re.I)),
    ("marketing_crm", re.compile(r"\b(marketing|crm|brand marketing|product marketing|growth marketing|performance marketing)\b", re.I)),
    ("hr_recruiting", re.compile(r"\b(recruiter|recruiting|talent acquisition|human resources|people partner|hr business partner)\b", re.I)),
    ("legal", re.compile(r"\b(counsel|lawyer|legal counsel|legal advisor|attorney)\b", re.I)),
    ("pure_sales", re.compile(r"\b(account executive|sales representative|sales executive|sales account|inside sales|field sales|telesales)\b", re.I)),
    ("insurance_technical", re.compile(r"\b(underwriter|underwriting|claims|actuarial|actuary)\b", re.I)),
    # Front-line retail/hospitality roles are unambiguously outside the user's
    # Business/Strategy/Finance target. Keep this list concrete: do not infer
    # seniority or exclude generic Manager titles.
    ("frontline_retail_hospitality", re.compile(
        r"\b(client advisor|sales advisor|fashion advisor|beauty advisor|sales assistant|"
        r"stockist|stock keeper|tailor|bartender|barman|cameriere|chef de rang|chef de partie|"
        r"hostess|hospitality assistant|hospitality host|makeup artist|"
        r"fragrance (?:consultant|specialist|expert)|barista|waiter|waitress)\b",
        re.I,
    )),
    # Hands-on trade/maintenance titles that cannot plausibly meet the target
    # profile. Generic Project/Operations/Manager wording is intentionally not
    # included.
    ("field_trade_maintenance", re.compile(
        r"\b(giuntista|cable jointer|cable jointing helper|motorista|manutentore|"
        r"maintenance electrician|maintenance mechanic|field service technician)\b",
        re.I,
    )),
    # Clinical/scientific delivery roles are outside the business target even
    # when they contain Analyst/Manager wording.
    ("clinical_scientific", re.compile(
        r"\b(clinical research associate|clinical science associate|medical scientific liaison|"
        r"\bmsl\b|biostatistic(?:ian|s)?|statistical programmer|translational medicine|"
        r"research associate(?:\s+i{1,3})?|medical affairs manager|medical manager|medical head)\b",
        re.I,
    )),
    ("creative_design", re.compile(
        r"\b(product|ux|ui|visual|fashion|graphic)\s+(?:senior\s+)?designer\b",
        re.I,
    )),
)

# Marketing/CRM words are not sufficient for a hard exclusion when the title itself
# also signals a broader strategy, analytics, commercial-planning or transformation role.
MARKETING_CRM_REVIEW_EXCEPTIONS = re.compile(
    r"\b(trade marketing|shopper marketing|marketing strategy|category(?: management| development)?|"
    r"commercial excellence|commercial strategy|revenue growth management|net revenue management|"
    r"revenue management|pricing|monetization|sales strategy|sales operations|commercial operations|"
    r"business insights?|customer insights?|business planning|commercial planning|strategy|strategic|"
    r"marketplace|seller|e-?commerce|go[- ]to[- ]market|route[- ]to[- ]market|\bgtm\b|\brtm\b|"
    r"business excellence|business integration|customer strategy|transformation)\b",
    re.I,
)

SEMANTIC_FIELDS = (
    "fit_score",
    "experience_required",
    "mandatory_years_experience",
    "preferred_years_experience",
    "mandatory_vs_preferred_requirements",
    "people_management_required",
    "direct_reports_or_team_lead_scope",
    "individual_contributor_possible",
    "decision_scope_and_ownership",
    "budget_or_p_and_l_ownership",
    "domain_experience_required",
    "education_or_certifications_required",
    "role_level_assessment",
    "seniority_evidence",
    "final_experience_status",
    "l68_status",
    "l68_evidence",
    "l68_requirement_location",
    "ordinary_twin_found",
    "ordinary_twin_job_id",
    "ordinary_twin_url",
    "ordinary_twin_similarity",
    "protected_twin_found",
    "protected_twin_job_id",
    "protected_twin_url",
    "protected_twin_similarity",
    "salary",
    "salary_source",
    "reportable",
    "rationale",
    "analyzed_at",
)


def hard_exclusion_reason(title: str | None) -> str | None:
    value = str(title or "")
    for reason, pattern in HARD_EXCLUSION_RULES:
        if pattern.search(value):
            if reason == "marketing_crm" and MARKETING_CRM_REVIEW_EXCEPTIONS.search(value):
                # Route the role to semantic JD review instead of closing it from title only.
                continue
            return reason
    return None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, obj) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def job_key(company: str, source_id) -> str:
    return f"{company}::{source_id}"


def canonical_key(url: str | None) -> str | None:
    if not url:
        return None
    return str(url).split("#", 1)[0].rstrip("/").casefold()


def threshold_for(location: str | None) -> int:
    loc = (location or "").casefold()
    return 80 if ("london" in loc or "luxembourg" in loc or "luxemburg" in loc) else 70


def decision_valid(
    decision: dict,
    fingerprint: str | None,
    *,
    title: str | None = None,
    priority_company: bool = False,
) -> bool:
    """Validate a persisted semantic decision before it can clear the queue.

    Priority roles and titles that look senior by wording (Manager/Senior/Lead/
    Head/Director) must have been checked against the full official JD. This is
    the guardrail that prevents title-based false negatives/positives.
    """
    if not isinstance(decision, dict):
        return False
    if decision.get("fingerprint") != fingerprint:
        return False
    if decision.get("analysis_status") != "ANALYZED":
        return False
    if not isinstance(decision.get("reportable"), bool):
        return False
    if not isinstance(decision.get("fit_score"), (int, float)):
        return False
    if not str(decision.get("rationale") or "").strip():
        return False
    if decision.get("final_experience_status") not in {"TARGET_0_5", "REVIEW_UNCLEAR", "OUT_GT5_MANDATORY"}:
        return False
    if decision.get("role_level_assessment") not in {"ENTRY_JUNIOR", "EARLY_MID", "MID", "SENIOR", "UNCLEAR"}:
        return False
    if not str(decision.get("seniority_evidence") or "").strip():
        return False
    if "mandatory_vs_preferred_requirements" not in decision:
        return False
    senior_wording = bool(re.search(r"\b(manager|senior|lead|head|director)\b", str(title or ""), re.I))
    protected_wording = bool(re.search(
        r"(?:l\.?\s*68\s*/\s*99|law\s*68\s*/\s*99|protected categor|categorie protette|categoria protetta)",
        str(title or ""),
        re.I,
    ))

    # Backward compatibility: historical semantic decisions created before the
    # L.68/99 policy are treated as NO only when the title itself contains no
    # protected-category signal. Protected titles must be re-read from the full
    # official JD and explicitly classified.
    l68_status = decision.get("l68_status")
    if l68_status is None and not protected_wording:
        l68_status = "NO"
    if l68_status not in {"NO", "PREFERRED", "REQUIRED", "RESERVED", "INVITED", "AMBIGUOUS"}:
        return False
    if l68_status != "NO":
        if "ordinary_twin_found" not in decision or not isinstance(decision.get("ordinary_twin_found"), bool):
            return False

    if priority_company or senior_wording or protected_wording or l68_status != "NO":
        if decision.get("analysis_method") != "chatgpt_semantic_full_jd":
            return False
    # Do not silently route a protected-category must-have/reserved vacancy as
    # candidable when eligibility has not been explicitly established.
    if l68_status in {"REQUIRED", "RESERVED"} and decision.get("reportable") is True:
        return False
    return True


def add_standard_jobs(current: dict):
    current_all = {}
    current_open = {}
    url_to_key = {}
    for company in current.get("companies", []):
        company_name = company.get("company")
        for job in company.get("jobs", []):
            if not company_name or job.get("source_id") is None:
                continue
            key = job_key(company_name, job.get("source_id"))
            item = dict(job)
            item["_company_name"] = company_name
            current_all[key] = item
            ckey = canonical_key(job.get("canonical_url") or job.get("url") or job.get("apply_url"))
            if ckey:
                url_to_key[ckey] = key
            if job.get("status") in OPEN_STATUSES:
                current_open[key] = item
    return current_all, current_open, url_to_key


def overlay_amazon_priority(batch: str, current_all: dict, current_open: dict, url_to_key: dict):
    if batch != "jw2":
        return
    source = read_json(ROOT / "amazon_target_check.json", {})
    for raw in source.get("target_jobs", []):
        if raw.get("status") not in OPEN_STATUSES:
            continue
        canonical = raw.get("apply_url")
        ckey = canonical_key(canonical)
        key = url_to_key.get(ckey) if ckey else None
        if key is None:
            sid = raw.get("job_id")
            if not sid:
                continue
            key = job_key("Amazon", sid)
            item = {
                "source_id": sid,
                "title": raw.get("title"),
                "location": raw.get("location") or raw.get("normalized_location") or raw.get("target_city"),
                "canonical_url": canonical,
                "apply_url": canonical,
                "fingerprint": raw.get("fingerprint"),
                "status": raw.get("status"),
                "_company_name": "Amazon",
            }
            current_all[key] = item
            current_open[key] = item
            if ckey:
                url_to_key[ckey] = key
        item = current_open.get(key)
        if not item:
            continue
        item.update({
            "_priority_company": True,
            "target_city": raw.get("target_city"),
            "role_family": raw.get("role_family"),
            "job_category": raw.get("job_category"),
            "business_scope_reason": raw.get("business_scope_reason"),
            "basic_qualifications": raw.get("basic_qualifications"),
            "preferred_qualifications": raw.get("preferred_qualifications"),
            "required_years_mentions": raw.get("required_years_mentions"),
            "preferred_years_mentions": raw.get("preferred_years_mentions"),
            "required_min_years": raw.get("required_min_years"),
            "experience_status_hint": raw.get("experience_status"),
            "experience_reason_hint": raw.get("experience_reason"),
            "industry_experience": raw.get("industry_experience"),
            "l68_status_hint": raw.get("l68_status"),
            "l68_evidence_hint": raw.get("l68_evidence"),
            "l68_requirement_location_hint": raw.get("l68_requirement_location"),
            "ordinary_twin_found_hint": raw.get("ordinary_twin_found"),
            "ordinary_twin_job_id_hint": raw.get("ordinary_twin_job_id"),
            "ordinary_twin_url_hint": raw.get("ordinary_twin_url"),
            "ordinary_twin_similarity_hint": raw.get("ordinary_twin_similarity"),
            "protected_twin_found_hint": raw.get("protected_twin_found"),
            "protected_twin_job_id_hint": raw.get("protected_twin_job_id"),
            "protected_twin_url_hint": raw.get("protected_twin_url"),
            "protected_twin_similarity_hint": raw.get("protected_twin_similarity"),
        })
        # The dedicated Amazon fingerprint includes the qualifications and is
        # the correct freshness key for semantic analysis.
        if raw.get("fingerprint"):
            item["fingerprint"] = raw.get("fingerprint")
        item["status"] = raw.get("status")
        item["location"] = raw.get("location") or item.get("location")


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
        0 if row.get("priority_company") else 1,
        status_rank.get(row.get("current_status"), 9),
        city_rank,
        row.get("first_seen_at") or "",
        (row.get("company") or "").casefold(),
        (row.get("title") or "").casefold(),
    )


def sync_batch(batch: str) -> dict:
    current_path = ROOT / f"current_jobs_{batch}.json"
    state_path = ROOT / f"analysis_results_{batch}.json"
    decisions_path = ROOT / f"semantic_decisions_{batch}.json"
    surfaced_path = ROOT / f"surfaced_jobs_{batch}.json"
    queue_path = ROOT / f"semantic_queue_{batch}.json"

    current = read_json(current_path, {})
    old_state = read_json(state_path, {"records": {}})
    old_records = old_state.get("records") or {}
    decisions = (read_json(decisions_path, {"records": {}}).get("records") or {})
    surfaced_registry = (read_json(surfaced_path, {"records": {}}).get("records") or {})

    current_all, current_open, url_to_key = add_standard_jobs(current)
    overlay_amazon_priority(batch, current_all, current_open, url_to_key)

    # Mastercard is collected through the standard Workday inventory, but it is
    # a priority company in JW1 just like Amazon is in JW2. Mark it explicitly
    # so queue ordering and reporting reconciliation apply the priority policy.
    if batch == "jw1":
        for item in current_open.values():
            if (item.get("_company_name") or "").casefold() == "mastercard":
                item["_priority_company"] = True

    records = {}
    preserved = 0
    reset = 0

    for key, job in current_open.items():
        company_name = job.get("_company_name")
        fingerprint = job.get("fingerprint")
        old = old_records.get(key) or {}
        exclusion = hard_exclusion_reason(job.get("title"))
        decision = decisions.get(key) or {}
        surfaced = surfaced_registry.get(key) or {}

        rec = {
            "company": company_name,
            "source_id": str(job.get("source_id")),
            "title": job.get("title"),
            "location": job.get("location"),
            "target_city": job.get("target_city"),
            "priority_company": bool(job.get("_priority_company")),
            "role_family": job.get("role_family"),
            "job_category": job.get("job_category"),
            "canonical_url": job.get("canonical_url") or job.get("url"),
            "apply_url": job.get("apply_url"),
            "fingerprint": fingerprint,
            "current_status": job.get("status"),
            "current_open": True,
            "threshold": threshold_for(job.get("target_city") or job.get("location")),
            "first_seen_at": old.get("first_seen_at") or current.get("generated_at") or utc_now(),
            "last_seen_at": current.get("generated_at") or utc_now(),
            "surfaced_at": surfaced.get("surfaced_at") or old.get("surfaced_at"),
            "surfaced_status": surfaced.get("surfaced_status") or old.get("surfaced_status"),
        }

        # Preserve Amazon structured JD hints in state/queue.
        for field in (
            "required_years_mentions", "preferred_years_mentions",
            "required_min_years", "experience_status_hint",
            "experience_reason_hint", "industry_experience",
            "business_scope_reason",
        ):
            if field in job:
                rec[field] = job.get(field)

        if exclusion:
            rec.update({
                "needs_analysis": False,
                "analysis_status": "ANALYZED",
                "analysis_method": "hard_rule_title",
                "hard_exclusion_reason": exclusion,
                "fit_score": 0,
                "experience_required": None,
                "salary": None,
                "salary_source": None,
                "reportable": False,
                "rationale": f"Hard-excluded by approved conservative title rule: {exclusion}.",
                "analyzed_at": utc_now(),
            })
            preserved += 1
        elif decision_valid(
            decision,
            fingerprint,
            title=job.get("title"),
            priority_company=bool(job.get("_priority_company")),
        ):
            rec.update({
                "needs_analysis": False,
                "analysis_status": "ANALYZED",
                "analysis_method": decision.get("analysis_method") or "chatgpt_semantic",
                "hard_exclusion_reason": None,
            })
            for field in SEMANTIC_FIELDS:
                if field in decision:
                    rec[field] = decision.get(field)
            preserved += 1
        else:
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
            })
            reset += 1
        records[key] = rec

    # Historical rows remain so surfaced history is not lost.
    for key, old in old_records.items():
        if key in records:
            continue
        rec = dict(old)
        rec["current_open"] = False
        if key in current_all:
            rec["current_status"] = current_all[key].get("status")
            rec["last_seen_at"] = current.get("generated_at") or utc_now()
        records[key] = rec

    open_records = [r for r in records.values() if r.get("current_open")]
    pending_records = [(k, r) for k, r in records.items() if r.get("current_open") and r.get("needs_analysis")]
    analyzed = [r for r in open_records if r.get("analysis_status") == "ANALYZED" and not r.get("needs_analysis")]
    hard_rule_analyzed = [r for r in analyzed if r.get("analysis_method") == "hard_rule_title"]
    semantic_analyzed = [r for r in analyzed if r.get("analysis_method") != "hard_rule_title"]
    reportable = [r for r in analyzed if r.get("reportable") is True]
    surfaced = [r for r in reportable if r.get("surfaced_at")]

    queue_records = []
    for key, rec in pending_records:
        queue_records.append({
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
            "amazon_semantic_source": "amazon_target_check.json" if rec.get("company") == "Amazon" and rec.get("priority_company") else None,
            "required_years_mentions": rec.get("required_years_mentions"),
            "preferred_years_mentions": rec.get("preferred_years_mentions"),
            "required_min_years": rec.get("required_min_years"),
            "experience_status_hint": rec.get("experience_status_hint"),
            "experience_reason_hint": rec.get("experience_reason_hint"),
        })
    queue_records.sort(key=queue_sort_key)

    payload = {
        "version": "2.0",
        "batch": batch.upper(),
        "synced_at": utc_now(),
        "source_generated_at": current.get("generated_at"),
        "policy": {
            "milan_rome_threshold": 70,
            "london_luxembourg_threshold": 80,
            "no_top_n_cap": True,
            "semantic_analysis_required": True,
            "semantic_analysis_owner": "ChatGPT recurring JW task",
            "manager_senior_lead_auto_exclusion": False,
            "decision_registry": decisions_path.name,
            "surfaced_registry": surfaced_path.name,
            "queue_file": queue_path.name,
        },
        "summary": {
            "open_extracted": len(current_open),
            "open_state_records": len(open_records),
            "valid_current_analysis": preserved,
            "pending_analysis": len(pending_records),
            "analyzed_current": len(analyzed),
            "hard_rule_analyzed": len(hard_rule_analyzed),
            "semantic_analyzed": len(semantic_analyzed),
            "reportable_current": len(reportable),
            "surfaced_current": len(surfaced),
        },
        "records": records,
    }
    write_json(state_path, payload)

    queue_payload = {
        "version": "1.0",
        "batch": batch.upper(),
        "generated_at": utc_now(),
        "pending_count": len(queue_records),
        "instructions": (
            "ChatGPT may close only clearly impossible roles from title+metadata; any plausibly relevant role requires the full official JD. "
            "Manager/Senior/Lead is never an automatic exclusion and business-compatible Manager/Senior/Lead roles require full-JD review. "
            "Persist completed decisions in the matching semantic_decisions file using job_key and the exact fingerprint."
        ),
        "required_decision_fields": [
            "fingerprint", "analysis_status=ANALYZED", "analysis_method=chatgpt_semantic_title_metadata|chatgpt_semantic_full_jd",
            "fit_score", "experience_required", "mandatory_years_experience",
            "preferred_years_experience", "mandatory_vs_preferred_requirements",
            "people_management_required", "individual_contributor_possible",
            "decision_scope_and_ownership", "role_level_assessment",
            "seniority_evidence", "final_experience_status", "salary",
            "salary_source", "reportable", "rationale", "analyzed_at"
        ],
        "records": queue_records,
    }
    write_json(queue_path, queue_payload)
    return payload


def main() -> int:
    for batch in BATCHES:
        p = sync_batch(batch)
        s = p["summary"]
        print(
            f"{batch.upper()} open={s['open_extracted']} analyzed={s['analyzed_current']} "
            f"semantic={s['semantic_analyzed']} pending={s['pending_analysis']} "
            f"reportable={s['reportable_current']} surfaced={s['surfaced_current']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
