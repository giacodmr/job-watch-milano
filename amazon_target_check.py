import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://www.amazon.jobs/en/search.json"
OUTPUT = Path("amazon_target_check.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 JobWatch/2.0",
    "Accept": "application/json,text/plain,*/*",
}

TARGETS = {
    "Milan": {"probe": "Milan", "country_codes": {"ITA", "IT"}},
    "Rome": {"probe": "Rome", "country_codes": {"ITA", "IT"}},
    "London": {"probe": "London", "country_codes": {"GBR", "GB", "UK"}},
}

BUSINESS_CATEGORY_TERMS = (
    "buying", "planning", "instock", "business", "merchant", "finance", "accounting",
    "project", "program", "product management", "sales", "advertising", "account management",
    "supply chain", "transportation", "operations management", "customer service",
)

BUSINESS_TITLE_TERMS = (
    "vendor manager", "vendor specialist", "brand specialist", "brand manager", "category manager",
    "product manager", "program manager", "project manager", "portfolio manager",
    "customer success", "customer solutions", "customer experience", "account manager",
    "business development", "partnership", "merchant", "retail", "buyer", "buying",
    "business analyst", "financial analyst", "finance", "fp&a", "strategy", "strategic",
    "business operations", "business planning", "commercial", "planning", "operations analyst",
    "supply chain", "capacity planning", "procurement", "economist", "chief of staff",
)

TECHNICAL_TITLE_EXCLUSIONS = (
    "software development engineer", "software engineer", "systems development engineer",
    "data engineer", "applied scientist", "research scientist", "machine learning",
    "security engineer", "network engineer", "hardware", "front end engineer",
    "quality assurance engineer", "solutions architect", " engineer", "architect",
    "scientist", "designer", "engineering manager", "maintenance", "construction",
    "realty", "tax manager", "tax analyst", "counsel", "legal", "talent acquisition",
    "recruit", "human resources", "hr business partner", "marketing", "marketer",
    "advertising", "sales account manager", "account executive", "design & innovation",
    "pathways operations manager",
)

INTERNSHIP_TERMS = ("intern", "internship", "apprentice", "apprenticeship")
OPEN_STATUSES = {"NEW", "UPDATED", "STILL_OPEN"}


def get_json(params):
    r = requests.get(API, params=params, headers=HEADERS, timeout=45)
    r.raise_for_status()
    return r.json(), r.url


def value(job, *keys):
    for key in keys:
        v = job.get(key)
        if v not in (None, "", []):
            return v
    return None


def normalized_values(job):
    v = job.get("normalized_location")
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [str(x) for x in v if x]
    return []


def country_ok(job, norm, codes):
    hay = " | ".join([
        str(job.get("country_code") or ""), str(job.get("country") or ""),
        str(norm or ""), str(job.get("location") or ""),
    ]).upper()
    return any(re.search(rf"(^|[^A-Z]){re.escape(c)}([^A-Z]|$)", hay) for c in codes)


def discover_norms(city, spec):
    data, probe_url = get_json({
        "base_query": spec["probe"], "offset": 0, "result_limit": 100, "sort": "relevant",
    })
    norms = set()
    for job in data.get("jobs", []):
        for norm in normalized_values(job):
            if city.lower() in norm.lower() and country_ok(job, norm, spec["country_codes"]):
                norms.add(norm)
    return sorted(norms), probe_url, int(data.get("hits") or 0)


def enumerate_norm(norm):
    jobs, urls = [], []
    offset, page_size, hits = 0, 100, None
    while hits is None or offset < hits:
        params = [
            ("base_query", ""), ("normalized_location[]", norm), ("offset", offset),
            ("result_limit", page_size), ("sort", "recent"),
        ]
        data, url = get_json(params)
        urls.append(url)
        page = data.get("jobs", []) or []
        jobs.extend(page)
        hits = int(data.get("hits") or len(page))
        if not page or len(page) < page_size:
            break
        offset += len(page)
        if offset > 5000:
            raise RuntimeError(f"Pagination safety limit exceeded for {norm}: hits={hits}")
    if hits is not None and len(jobs) != hits:
        raise RuntimeError(f"Amazon count mismatch for {norm}: retrieved={len(jobs)} hits={hits}")
    return jobs, hits or 0, urls


def norm_text(v):
    if isinstance(v, (list, tuple, set)):
        return " | ".join(str(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return str(v or "")


def is_business_role(job):
    title = " ".join(str(value(job, "title") or "").casefold().split())
    category = " ".join(str(value(job, "job_category", "category") or "").casefold().split())
    business_category = " ".join(str(value(job, "business_category") or "").casefold().split())
    if any(term in title for term in INTERNSHIP_TERMS):
        return False, "internship"
    if any(term in title for term in TECHNICAL_TITLE_EXCLUSIONS):
        return False, "technical_title"
    if any(term in title for term in BUSINESS_TITLE_TERMS):
        return True, "business_title"
    hay = f"{category} | {business_category}"
    if any(term in hay for term in BUSINESS_CATEGORY_TERMS):
        return True, "business_category"
    return False, "outside_business_scope"


def years_mentions(text):
    text = re.sub(r"(?i)(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\s*(?:years?|yrs?)", r"\1 years", text or "")
    vals = []
    for m in re.finditer(r"(?i)(?<![\d\-–—])(\d{1,2})\s*\+?\s*(?:years?|yrs?)", text):
        n = int(m.group(1))
        if 0 < n < 30:
            vals.append(n)
    return sorted(set(vals))


def experience_bucket(job):
    raw = value(job, "industry_experience", "experience", "experience_level")
    return norm_text(raw) or None


def experience_decision(job):
    basic = str(value(job, "basic_qualifications") or "")
    pref = str(value(job, "preferred_qualifications") or "")
    required = years_mentions(basic)
    preferred = years_mentions(pref)
    required_min = max(required) if required else None
    bucket = experience_bucket(job)
    bucket_l = (bucket or "").casefold()
    if required_min is not None and required_min > 5:
        status = "OUT"
        reason = f"basic qualifications require at least {required_min} years"
    elif required_min is not None:
        status = "TARGET"
        reason = f"basic qualifications require up to {required_min} years"
    elif any(x in bucket_l for x in ("seven_plus", "7+", "7 plus", "7 or more")):
        status = "OUT"
        reason = "Amazon industry-experience bucket is 7+ years"
    elif bucket:
        status = "REVIEW"
        reason = f"no numeric minimum in basic qualifications; Amazon bucket={bucket}"
    else:
        status = "REVIEW"
        reason = "no numeric minimum exposed in basic qualifications"
    return required, preferred, required_min, bucket, status, reason


def job_id(job):
    return str(value(job, "id", "id_icims", "job_id", "requisition_id") or value(job, "job_path") or "")


def canonical_url(job):
    path = value(job, "job_path", "url")
    if not path:
        return None
    path = str(path)
    return path if path.startswith("http") else "https://www.amazon.jobs" + path


def role_family(title):
    t = str(title or "").casefold()
    if any(x in t for x in ("vendor", "category", "brand", "retail", "buyer", "buying")):
        return "Retail / Vendor / Category / Brand"
    if any(x in t for x in ("product manager", "program manager", "project manager", "portfolio manager")):
        return "Product / Program / Project"
    if any(x in t for x in ("customer", "account manager", "business development", "partnership", "merchant")):
        return "Customer / Account / Business Development"
    if any(x in t for x in ("finance", "financial", "fp&a", "economist")):
        return "Finance / Economics"
    if any(x in t for x in ("strategy", "strategic", "business operations", "business planning", "business analyst", "commercial")):
        return "Strategy / Business / Commercial"
    if any(x in t for x in ("supply chain", "operations", "planning", "procurement")):
        return "Operations / Supply Chain / Planning"
    return "Other Business"


def compact_job(job, city, norm, scope_reason):
    basic = str(value(job, "basic_qualifications") or "")
    pref = str(value(job, "preferred_qualifications") or "")
    required, preferred, required_min, bucket, exp_status, exp_reason = experience_decision(job)
    return {
        "job_id": job_id(job),
        "title": value(job, "title"),
        "role_family": role_family(value(job, "title")),
        "business_scope_reason": scope_reason,
        "location": value(job, "location") or norm,
        "target_city": city,
        "normalized_location": norm,
        "company": value(job, "company_name", "company"),
        "job_category": value(job, "job_category", "category"),
        "business_category": value(job, "business_category"),
        "industry_experience": bucket,
        "posted_date": value(job, "posted_date", "posted_at", "updated_time"),
        "apply_url": canonical_url(job),
        "required_years_mentions": required,
        "preferred_years_mentions": preferred,
        "required_min_years": required_min,
        "experience_status": exp_status,
        "experience_reason": exp_reason,
        "basic_qualifications": basic,
        "preferred_qualifications": pref,
    }


def fingerprint(job):
    keys = (
        "title", "role_family", "location", "target_city", "company", "job_category", "business_category",
        "industry_experience", "posted_date", "apply_url", "required_years_mentions", "preferred_years_mentions",
        "required_min_years", "experience_status", "basic_qualifications", "preferred_qualifications",
    )
    raw = json.dumps({k: job.get(k) for k in keys}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def load_previous():
    if not OUTPUT.exists():
        return {}
    try:
        old = json.loads(OUTPUT.read_text(encoding="utf-8"))
        return {str(j.get("job_id")): j for j in old.get("target_jobs", []) if j.get("job_id")}
    except Exception:
        return {}


def main():
    previous = load_previous()
    result = {
        "version": "2.0",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": "Amazon Jobs public /en/search.json API",
        "scope": ["Milan", "Rome", "London"],
        "experience_policy": "Business roles are included when Basic Qualifications do not explicitly require >5 years. Unknown numeric requirements are retained for manual review to avoid false negatives. Amazon's 4-6 years bucket is therefore reviewed from the JD rather than excluded wholesale.",
        "global_coverage": "NOT_CHECKED",
        "global_coverage_reason": "All official Amazon Jobs inventory is exhausted for the three target cities, but worldwide inventory is intentionally not certified.",
        "locations": {}, "target_jobs": [], "excluded_business_jobs": [],
    }

    current_by_id = {}
    excluded_by_id = {}
    all_open_ids = set()
    for city, spec in TARGETS.items():
        norms, probe_url, probe_hits = discover_norms(city, spec)
        city_jobs, total_inventory, search_urls = [], 0, []
        seen_city = set()
        for norm in norms:
            jobs, hits, urls = enumerate_norm(norm)
            total_inventory += hits
            search_urls.extend(urls)
            for job in jobs:
                jid = job_id(job)
                if not jid or jid in seen_city:
                    continue
                seen_city.add(jid)
                all_open_ids.add(jid)
                city_jobs.append((job, norm))

        business_count = target_count = excluded_exp_count = 0
        for job, norm in city_jobs:
            in_scope, scope_reason = is_business_role(job)
            if not in_scope:
                continue
            business_count += 1
            item = compact_job(job, city, norm, scope_reason)
            item["fingerprint"] = fingerprint(item)
            if item["experience_status"] == "OUT":
                excluded_exp_count += 1
                excluded_by_id[item["job_id"]] = item
                continue
            old = previous.get(item["job_id"])
            if old is None:
                item["status"] = "NEW"
            elif old.get("fingerprint") and old.get("fingerprint") != item["fingerprint"]:
                item["status"] = "UPDATED"
            else:
                item["status"] = "STILL_OPEN"
            current_by_id.setdefault(item["job_id"], item)
            target_count += 1

        result["locations"][city] = {
            "coverage": "VERIFIED",
            "normalized_locations": norms,
            "probe_hits": probe_hits,
            "inventory_count": len(city_jobs),
            "api_reported_hits_sum": total_inventory,
            "business_jobs_count": business_count,
            "target_or_review_jobs_count": target_count,
            "excluded_explicit_gt5_count": excluded_exp_count,
            "probe_url": probe_url,
            "search_urls": search_urls,
        }

    city_rank = {"Milan": 0, "Rome": 1, "London": 2}
    deduped = {}
    for item in current_by_id.values():
        jid = item["job_id"]
        prev_item = deduped.get(jid)
        if prev_item is None or city_rank.get(item["target_city"], 99) < city_rank.get(prev_item["target_city"], 99):
            deduped[jid] = item
    current_by_id = deduped

    result["target_jobs"] = list(current_by_id.values())
    result["excluded_business_jobs"] = list(excluded_by_id.values())

    for jid, old in previous.items():
        if jid not in current_by_id and jid not in all_open_ids and old.get("status") != "CLOSED":
            closed = dict(old)
            closed["status"] = "CLOSED"
            result["target_jobs"].append(closed)

    result["target_jobs"].sort(key=lambda x: (city_rank.get(x.get("target_city"), 99), x.get("status") or "", (x.get("title") or "").casefold(), x.get("job_id") or ""))
    result["excluded_business_jobs"].sort(key=lambda x: (city_rank.get(x.get("target_city"), 99), (x.get("title") or "").casefold(), x.get("job_id") or ""))
    active = [x for x in result["target_jobs"] if x.get("status") in OPEN_STATUSES]
    result["summary"] = {
        "target_jobs_open": len(active),
        "TARGET_explicit_le5": sum(x.get("status") in OPEN_STATUSES and x.get("experience_status") == "TARGET" for x in result["target_jobs"]),
        "REVIEW_no_numeric_minimum": sum(x.get("status") in OPEN_STATUSES and x.get("experience_status") == "REVIEW" for x in result["target_jobs"]),
        "excluded_explicit_gt5": len(result["excluded_business_jobs"]),
        "NEW": sum(x.get("status") == "NEW" for x in result["target_jobs"]),
        "UPDATED": sum(x.get("status") == "UPDATED" for x in result["target_jobs"]),
        "STILL_OPEN": sum(x.get("status") == "STILL_OPEN" for x in result["target_jobs"]),
        "CLOSED": sum(x.get("status") == "CLOSED" for x in result["target_jobs"]),
        "Milan": sum(x.get("target_city") == "Milan" and x.get("status") in OPEN_STATUSES for x in result["target_jobs"]),
        "Rome": sum(x.get("target_city") == "Rome" and x.get("status") in OPEN_STATUSES for x in result["target_jobs"]),
        "London": sum(x.get("target_city") == "London" and x.get("status") in OPEN_STATUSES for x in result["target_jobs"]),
    }

    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("AMAZON", json.dumps(result["summary"], ensure_ascii=False))
    for x in result["target_jobs"]:
        if x.get("status") in {"NEW", "UPDATED", "CLOSED"}:
            print(f"  {x.get('status')} | {x.get('target_city')} | {x.get('experience_status')} | {x.get('title')} | {x.get('apply_url')}")


if __name__ == "__main__":
    main()
