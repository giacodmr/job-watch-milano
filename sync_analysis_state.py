#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from harden_job_watch_state import semantic_decision_valid, needs_applied_review, queue_row, queue_sort_key
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1", "jw2", "jw3", "jw4")
OPEN_STATUSES = {"NEW", "STILL_OPEN", "UPDATED"}

# Conservative, unambiguous title-only exclusions. Queue-noise policy refreshed 2026-10-01. There is deliberately no
# positive-title whitelist and no Manager/Senior/Lead exclusion.
HARD_EXCLUSION_RULES = (
    ("internship", re.compile(r"\b(?:intern|internship|stage|tirocinio)\b", re.I)),
    ("m_and_a_title_user_exclusion", re.compile(r"\bM\s*(?:&|&amp;)\s*A\b", re.I)),
    # Narrow job-family exclusions vetted against the 2026-10-01 historical queue.
    # No generic Manager/Senior/Director, Sales, Engineering or BD keyword rule.
    # Priority Amazon/Mastercard and L.68/99 postings still require JD review,
    # except the separately authorized global M&A title exclusion above.
    ("specialist_tax", re.compile(r"\b(?:tax|vat)\b", re.I)),
    ("specialist_legal", re.compile(r"\b(?:legal\s+(?:specialist|consultant|advisor)|commercial legal|legal public sector|paralegal)\b", re.I)),
    ("technical_engineering_narrow", re.compile(
        r"\b(?:ai|python|web|forward deployed|integration|implementation|solutions?|applications support|"
        r"electrical design|civil marine|packaging r&d|mlops|growth|account risk|project|product design|"
        r"ai specification|ai-enabled threat defense|senior android|senior ios|senior software java)\s+"
        r"(?:(?:\w+|&)\s+){0,3}(?:engineer|engineering)\b|"
        r"\b(?:engineering (?:lead|manager|director)|lead analytics engineer|analytics engineering|"
        r"global ai engineering|ai scientist|machine learning engineer|"
        r"project hse (?:manager|coordinator)|corporate safety manager)\b", re.I,
    )),
    ("technical_architecture_narrow", re.compile(
        r"\b(?:application|cloud|it|erp ecosystem|data\s*&\s*ai|security|enterprise\s*&\s*it|"
        r"solutions?|technical)\s+architect\b|\b(?:senior network architect|architecture lead)\b", re.I,
    )),
    ("pure_content_creative_narrow", re.compile(
        r"\b(?:content marketing|seo content|content specialist|content designer|content editor|"
        r"brand marketing designer|creative strategy\s*&\s*integrated campaigns|"
        r"media, channels\s*&\s*content|senior designer offices|staff content designer)\b", re.I,
    )),
    ("frontline_warehouse_store_narrow", re.compile(
        r"\b(?:cold.chain warehouse manager|warehouse manager hazardous goods|device maintenance|"
        r"facilities\s*&\s*maintenance manager|in[- ]store\s+(?:crm|high.end|training)\s+manager|"
        r"deputy store director|in store artisan|in store trainer|store training manager)\b", re.I,
    )),
    ("hr_administration_narrow", re.compile(r"\b(?:benefits program manager|hr director|hr administrator)\b", re.I)),
    ("pure_sales_narrow", re.compile(
        r"\b(?:sales development representative|manager, sales development|head of payout sales|"
        r"director, sales|senior sales manager|financial institution financing sales|"
        r"electronic investment solutions sales|sales\s*-\s*derivatives|"
        r"services sales solution director)\b", re.I,
    )),
    ("generic_non_vacancy", re.compile(
        r"\b(?:candidatura spontanea|talent pool|general application|non trovi posizioni aperte)\b", re.I,
    )),
    # Additional explicitly out-of-scope title families from reviewed open backlog.
    ("admin_clerical_narrow", re.compile(
        r"\b(?:executive assistant|administrative senior professional|pa & internal engagement assistant|"
        r"share plans administrator|mortgage administrator|sales and service administrator|"
        r"speculative applications - mortgage administrator|addetto/a inserimento dati|"
        r"contabilit[aà] fornitori)\b", re.I,
    )),
    ("frontline_store_narrow", re.compile(
        r"\b(?:caf[eè] team member|tecnico audioprotesista|stock manager|responsabile vendite/athlete|"
        r"responsabile vendite\s*-|athlete nike|ma[iî]tre|skincare specialist|"
        r"digital client service advisor)\b", re.I,
    )),
    ("clinical_narrow", re.compile(
        r"\b(?:clinical quality manager|statistical programming|health improvement coordinator|"
        r"infermiere|dermatology nurses|isf specialist|product specialist biosurgery|"
        r"clinical outcome assessment)\b", re.I,
    )),
    ("technical_speciality_narrow", re.compile(
        r"\b(?:specialista ingegneria civile|responsabile topografia|specialista progettazione impianti|"
        r"it infrastructure service manager|signal processing manager|technical leader|"
        r"senior techops|systems integrator)\b", re.I,
    )),
    ("specialist_trading_narrow", re.compile(
        r"\b(?:fx options trader|bond trader|ficc sales vice president)\b", re.I,
    )),
    ("hr_business_partner_narrow", re.compile(
        r"\b(?:hrbp|jdl-hrbp|jdl hrbp|total rewards\s*&\s*mobility policies)\b", re.I,
    )),
    ("generic_or_translator_narrow", re.compile(
        r"\b(?:we.re always on the lookout|freelance translators|freelance-\s*translators|"
        r"freelance\s*translators)\b", re.I,
    )),
    ("field_maintenance_dispatch_narrow", re.compile(
        r"\b(?:delivery station supervisor|gas dispatcher|addetto/a alla manutenzione elettrica|"
        r"assistente alla manutenzione idraulica|manutentore idraulico)\b", re.I,
    )),
    ("internship", re.compile(r"\b(intern|internship|stage|apprentice|apprenticeship)\b|(?<=_)internship(?=_)", re.I)),
    ("software_engineering", re.compile(r"\b(software|backend|frontend|front-end|full[ -]?stack|mobile|platform|systems?)\s+(engineer|developer)\b|\bdeveloper\b", re.I)),
    ("technical_engineering", re.compile(r"\b(data engineer|machine learning engineer|ml engineer|security engineer|network engineer|cloud engineer|devops|site reliability engineer|solutions architect|solution architect|enterprise architect|data architect)\b", re.I)),
    ("data_science", re.compile(r"\b(data scientist|applied scientist|research scientist|machine learning scientist)\b", re.I)),
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
    ("frontline_retail_hospitality", re.compile(
        r"\b(sales associate|store associate|retail associate|shop assistant|store advisor|beauty consultant|"
        r"beauty therapist|beautician|cashier|store cashier|floor manager|store manager|assistant store manager|"
        r"restaurant manager|restaurant supervisor|front office agent|receptionist|concierge)\b", re.I,
    )),
    ("clinical_scientific", re.compile(
        r"\b(informatore scientifico|pharmacist|pharmacy advisor|nurse|nursing|physician|doctor|clinical coding|"
        r"clinical coder|clinical auditor|clinical trial|clinical operations|clinical development|clinical safety|"
        r"drug safety|pharmacovigilance|medical science|health technology assessment|hta|health economist)\b", re.I,
    )),
    ("creative_content", re.compile(
        r"\b(copywriter|art director|creative strategist|creative director|content creator|graphic artist|"
        r"visual merchandis(?:er|ing)|stylist|styling)\b", re.I,
    )),
    ("facilities_property", re.compile(
        r"\b(facilities manager|facility manager|workplace service|workplace services|building manager|property maintenance)\b", re.I,
    )),
    ("technical_it_specialist", re.compile(
        r"\b(cybersecurity|cyber security|security architect|cloudops|cloud ops|sre expert|penetration testing|"
        r"red team|technical specialist|it support|service desk|network specialist|infrastructure engineer)\b", re.I,
    )),
    ("accounting_payroll", re.compile(
        r"\b(accountant|accounting specialist|accounts payable|accounts receivable|payroll specialist|general ledger specialist|"
        r"tax compliance specialist|tax accountant|bookkeeper)\b", re.I,
    )),
    ("customer_service_frontline", re.compile(
        r"\b(customer care representative|customer service associate|customer service representative|assistenza clienti|"
        r"welcomist|stock assistant|stock supervisor|showroom dresser|catering supervisor)\b", re.I,
    )),
    ("pure_marketing_communications", re.compile(
        r"\b(brand ambassador|paid media expert|performance marketing|content marketing specialist|corporate communications|"
        r"brand ambassador assistant|paid media specialist)\b", re.I,
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
    "decision",
    "reason",
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
            # Customer-facing solution/pre-sales engineers can be consultative
            # business roles (rather than pure software engineering). Review
            # the full JD instead of title-excluding this ambiguous family.
            if reason == "technical_engineering_narrow" and re.search(
                r"\b(?:solutions?\s+engineer(?:ing)?|growth engineer|implementation engineer)\b",
                value, re.I,
            ):
                continue
            if reason == "marketing_crm" and MARKETING_CRM_REVIEW_EXCEPTIONS.search(value):
                # Route the role to semantic JD review instead of closing it from title only.
                continue
            return reason
    return None


def salary_below_floor(evidence: dict) -> bool:
    maximum = evidence.get("fixed_base_max_eur")
    return bool(isinstance(maximum, (int, float)) and not isinstance(maximum, bool)
                and 0 < maximum < 33000 and evidence.get("fixed_base_source_url")
                and evidence.get("fixed_base_documented") is True)


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
    old = read_json(path, {})
    volatile = {"synced_at", "generated_at"}
    if {k: v for k, v in old.items() if k not in volatile} == {k: v for k, v in obj.items() if k not in volatile}:
        return
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
    return semantic_decision_valid(decision, {"fingerprint": fingerprint, "title": title,
                                              "priority_company": priority_company})[0]


def add_standard_jobs(current: dict):
    current_all = {}
    current_open = {}
    url_to_key = {}
    for company in current.get("companies", []):
        company_name = company.get("company")
        if company_name == "ION Group":
            continue
        for job in company.get("jobs", []):
            if not company_name or job.get("source_id") is None:
                continue
            key = job_key(company_name, job.get("source_id"))
            item = dict(job)
            item["_company_name"] = company_name
            current_all[key] = item
            ckey = canonical_key(job.get("canonical_url") or job.get("url") or job.get("apply_url"))
            is_open = job.get("status") in OPEN_STATUSES
            # Historical CLOSED rows can share the exact URL with the current
            # stable-ID vacancy (notably after the Amazon UUID migration).
            # Never let a closed key shadow an open key in canonical matching.
            if ckey and (ckey not in url_to_key or is_open):
                url_to_key[ckey] = key
            if is_open:
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

        # Bridge historical UUID-based target-check rows to the stable public
        # Amazon requisition ID used by collector.py.
        stable_sid = None
        m = re.search(r"/jobs/(\d+)(?:/|$)", str(canonical or ""), re.I)
        if m:
            stable_sid = m.group(1)
            stable_key = job_key("Amazon", stable_sid)
            if key is None and stable_key in current_open:
                key = stable_key

        if key is None:
            sid = stable_sid or raw.get("job_id")
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


def sync_batch(batch: str) -> dict:
    current_path = ROOT / f"current_jobs_{batch}.json"
    state_path = ROOT / f"analysis_results_{batch}.json"
    decisions_path = ROOT / f"semantic_decisions_{batch}.json"
    surfaced_path = ROOT / f"surfaced_jobs_{batch}.json"
    queue_path = ROOT / f"semantic_queue_{batch}.json"
    user_decisions_path = ROOT / "user_job_decisions.json"

    current = read_json(current_path, {})
    old_state = read_json(state_path, {"records": {}})
    old_records = old_state.get("records") or {}
    decisions = (read_json(decisions_path, {"records": {}}).get("records") or {})
    surfaced_registry = (read_json(surfaced_path, {"records": {}}).get("records") or {})
    user_decisions_payload = read_json(user_decisions_path, {"records": {}})
    user_decisions = user_decisions_payload.get("records") or {}
    user_decisions_backfilled = False

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
        # Exclude US London (Kentucky) rows already captured in this snapshot.
        loc = str(job.get("location") or "")
        if (re.search(r"\bLondon\s*,\s*(?:KY|Kentucky)\b", loc, re.I)
                and not re.search(r"\bLondon\s*,?\s*(?:UK|GB|England|United Kingdom)\b", loc, re.I)):
            exclusion = "outside_target_geography"
        decision = decisions.get(key) or {}
        if salary_below_floor(job) or (decision.get("fingerprint") == fingerprint and salary_below_floor(decision)):
            exclusion = "salary_below_floor"
        surfaced = surfaced_registry.get(key) or {}
        user_decision = user_decisions.get(key) or {}
        if user_decision and not user_decision.get("fingerprint") and fingerprint:
            user_decision["fingerprint"] = fingerprint
            user_decisions[key] = user_decision
            user_decisions_backfilled = True
        raw_user_decision = user_decision.get("decision")
        user_decision_fingerprint = user_decision.get("fingerprint")
        user_decision_stale = bool(
            raw_user_decision == "NOT_INTERESTED"
            and user_decision_fingerprint
            and user_decision_fingerprint != fingerprint
        )
        effective_user_decision = None if user_decision_stale else raw_user_decision

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
            "user_decision": effective_user_decision,
            "user_decision_original": raw_user_decision,
            "user_decision_fingerprint": user_decision_fingerprint,
            "user_decision_stale": user_decision_stale,
            "user_decision_reason": user_decision.get("reason"),
            "user_decided_at": user_decision.get("decided_at"),
            "suppress_from_apply_now": effective_user_decision in {"APPLIED", "NOT_INTERESTED"},
        }

        if surfaced.get("fingerprint") or old.get("surfaced_fingerprint"):
            rec["surfaced_fingerprint"] = surfaced.get("fingerprint") or old["surfaced_fingerprint"]
        if user_decision.get("rejection_reason"):
            rec["rejection_reason"] = user_decision["rejection_reason"]

        # Preserve Amazon structured JD hints in state/queue.
        for field in (
            "required_years_mentions", "preferred_years_mentions",
            "required_min_years", "experience_status_hint",
            "experience_reason_hint", "industry_experience",
            "business_scope_reason",
        ):
            if field in job:
                rec[field] = job.get(field)

        if effective_user_decision == "NOT_INTERESTED":
            rec.update({
                "needs_analysis": False,
                "analysis_status": "ANALYZED",
                "analysis_method": "user_decision_not_interested",
                "hard_exclusion_reason": None,
                "fit_score": old.get("fit_score"),
                "experience_required": old.get("experience_required"),
                "salary": old.get("salary"),
                "salary_source": old.get("salary_source"),
                "reportable": False,
                "rationale": user_decision.get("reason") or "Explicit user decision: not interested.",
                "analyzed_at": user_decision.get("decided_at") or utc_now(),
            })
            preserved += 1
        elif effective_user_decision == "APPLIED" and not decision_valid(
            decision,
            fingerprint,
            title=job.get("title"),
            priority_company=bool(job.get("_priority_company")),
        ):
            rec.update({
                "needs_analysis": False,
                "analysis_status": "ANALYZED",
                "analysis_method": "user_decision_applied",
                "hard_exclusion_reason": None,
                "fit_score": old.get("fit_score"),
                "experience_required": old.get("experience_required"),
                "salary": old.get("salary"),
                "salary_source": old.get("salary_source"),
                "reportable": False,
                "rationale": user_decision.get("reason") or "Explicit user decision: already applied.",
                "analyzed_at": user_decision.get("decided_at") or utc_now(),
            })
            preserved += 1
        elif exclusion and (exclusion in {"m_and_a_title_user_exclusion", "outside_target_geography", "internship", "salary_below_floor"} or (not bool(job.get("_priority_company")) and not re.search(
            r"(?:l\.?\s*68\s*/\s*99|law\s*68\s*/\s*99|protected categor|categorie protette|categoria protetta)",
            str(job.get("title") or ""),
            re.I,
        ))):
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
                "analyzed_at": old.get("analyzed_at") if old.get("fingerprint") == fingerprint and old.get("hard_exclusion_reason") == exclusion else utc_now(),
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
        if decision.get("analysis_method") == "chatgpt_semantic_triage" and not rec["needs_analysis"]:
            rec.update(fit_score=0, reportable=False)
        # Pending material deltas survive NEW -> STILL_OPEN and failed/unfinished daily runs.
        material_change = bool(old and old.get("fingerprint") != fingerprint)
        delta_pending = bool(
            old.get("delta_pending") or job.get("status") in {"NEW", "UPDATED"}
            or material_change or user_decision_stale
        )
        if not rec["needs_analysis"] and (not rec.get("reportable") or surfaced.get("fingerprint") == fingerprint):
            delta_pending = False
        if delta_pending:
            rec["delta_pending"] = True
        rec["applied_material_update"] = bool(effective_user_decision == "APPLIED" and (
            job.get("status") == "UPDATED" or material_change or old.get("applied_material_update")
        ) and surfaced.get("fingerprint") != fingerprint)
        if needs_applied_review(rec):
            rec.update(needs_analysis=True, analysis_status="PENDING", analysis_method=None)
        records[key] = rec

    # Historical rows remain so surfaced history is not lost.
    for key, old in old_records.items():
        if key in records:
            continue
        rec = dict(old)
        rec["current_open"] = False
        if rec.get("company") == "ION Group":
            rec["excluded_company"] = True
            rec["reportable"] = False
        if key in current_all:
            rec["current_status"] = current_all[key].get("status")
            rec["last_seen_at"] = current.get("generated_at") or utc_now()
        records[key] = rec

    open_records = [r for r in records.values() if r.get("current_open")]
    pending_records = [(k, r) for k, r in records.items() if r.get("current_open") and r.get("needs_analysis")]
    analyzed = [r for r in open_records if r.get("analysis_status") == "ANALYZED" and not r.get("needs_analysis")]
    hard_rule_analyzed = [r for r in analyzed if r.get("analysis_method") == "hard_rule_title"]
    semantic_analyzed = [r for r in analyzed if r.get("analysis_method") != "hard_rule_title"]
    reportable = [
        r for r in analyzed
        if r.get("reportable") is True
        and r.get("user_decision") not in {"APPLIED", "NOT_INTERESTED"}
    ]
    active_shortlist = [
        r for r in open_records
        if r.get("user_decision") in {"TO_REVIEW", "INTERESTED"}
    ]
    surfaced = [r for r in reportable if r.get("surfaced_at")]

    queue_records = [queue_row(key, rec) for key, rec in pending_records]
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
            "user_decisions_registry": user_decisions_path.name,
            "never_reviewed_never_surfaced_guard": True,
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
            "active_shortlist": len(active_shortlist),
            "applied_open": sum(1 for r in open_records if r.get("user_decision") == "APPLIED"),
            "not_interested_open": sum(1 for r in open_records if r.get("user_decision") == "NOT_INTERESTED"),
            "stale_user_decisions": sum(1 for r in open_records if r.get("user_decision_stale")),
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
        "triage_decision_fields": ["fingerprint", "analysis_status", "analysis_method=chatgpt_semantic_triage", "decision=REJECT", "reason", "rationale", "analyzed_at"],
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

    if user_decisions_backfilled:
        user_decisions_payload["records"] = user_decisions
        user_decisions_payload["updated_at"] = utc_now()
        write_json(user_decisions_path, user_decisions_payload)

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
