import json
import re
from datetime import datetime, timezone

import requests

API = "https://www.amazon.jobs/en/search.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 JobWatch/1.0",
    "Accept": "application/json,text/plain,*/*",
}

TARGETS = {
    "Milan": {"probe": "Milan", "country_codes": {"ITA", "IT"}},
    "Rome": {"probe": "Rome", "country_codes": {"ITA", "IT"}},
    "London": {"probe": "London", "country_codes": {"GBR", "GB", "UK"}},
}

INCLUDE_TERMS = (
    "business analyst",
    "financial analyst",
    "finance analyst",
    "strategy",
    "strategic",
    "corporate strategy",
    "business operations",
    "business planning",
    "planning analyst",
    "commercial analyst",
    "operations analyst",
    "program analyst",
    "fp&a",
    "finance",
    "economist",
)

EXCLUDE_TERMS = (
    "manager",
    "director",
    "principal",
    "head of",
    "vice president",
    " vp",
    "marketing",
    "advertising",
    "amazon ads",
    "crm",
    "sales account",
    "account manager",
)


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
    vals = []
    v = job.get("normalized_location")
    if isinstance(v, str):
        vals.append(v)
    elif isinstance(v, list):
        vals.extend(str(x) for x in v if x)
    return vals


def country_ok(job, norm, codes):
    candidates = [
        str(job.get("country_code") or ""),
        str(job.get("country") or ""),
        str(norm or ""),
        str(job.get("location") or ""),
    ]
    hay = " | ".join(candidates).upper()
    return any(re.search(rf"(^|[^A-Z]){re.escape(c)}([^A-Z]|$)", hay) for c in codes)


def discover_norms(city, spec):
    data, probe_url = get_json({
        "base_query": spec["probe"],
        "offset": 0,
        "result_limit": 100,
        "sort": "relevant",
    })
    norms = set()
    for job in data.get("jobs", []):
        for norm in normalized_values(job):
            if city.lower() in norm.lower() and country_ok(job, norm, spec["country_codes"]):
                norms.add(norm)
    return sorted(norms), probe_url, int(data.get("hits") or 0)


def enumerate_norm(norm):
    jobs = []
    offset = 0
    page_size = 100
    hits = None
    urls = []
    while hits is None or offset < hits:
        params = [
            ("base_query", ""),
            ("normalized_location[]", norm),
            ("offset", offset),
            ("result_limit", page_size),
            ("sort", "relevant"),
        ]
        data, url = get_json(params)
        urls.append(url)
        page = data.get("jobs", []) or []
        jobs.extend(page)
        hits = int(data.get("hits") or len(page))
        if not page:
            break
        offset += len(page)
        if len(page) < page_size:
            break
        if offset > 5000:
            raise RuntimeError(f"Pagination safety limit exceeded for {norm}: hits={hits}")
    return jobs, hits or 0, urls


def is_target_title(title):
    t = " ".join(str(title or "").lower().split())
    if not any(term in t for term in INCLUDE_TERMS):
        return False
    if any(term in t for term in EXCLUDE_TERMS):
        return False
    return True


def years_mentions(text):
    vals = []
    for m in re.finditer(r"(?i)(\d{1,2})\s*\+?\s*(?:years?|yrs?)", text or ""):
        n = int(m.group(1))
        if 0 < n < 30:
            vals.append(n)
    return sorted(set(vals))


def salary_lines(text):
    if not text:
        return []
    compact = re.sub(r"\s+", " ", text)
    patterns = [
        r"[A-Za-z ,.-]+-\s*[€£$]?\s*[0-9][0-9,\.]*\s*(?:-\s*[€£$]?\s*[0-9][0-9,\.]*)?\s*(?:EUR|GBP|USD|CAD)\s*(?:annually|annual|per year|hourly)?",
        r"[€£$]\s*[0-9][0-9,\.]*\s*(?:-\s*[€£$]?\s*[0-9][0-9,\.]*)?\s*(?:annually|annual|per year|hourly)?",
    ]
    found = []
    for pat in patterns:
        for m in re.finditer(pat, compact, re.I):
            s = m.group(0).strip(" .,-")
            if len(s) <= 180 and s not in found:
                found.append(s)
    return found[:5]


def job_id(job):
    return str(value(job, "id", "id_icims", "job_id", "requisition_id") or value(job, "job_path") or "")


def canonical_url(job):
    path = value(job, "job_path", "url")
    if not path:
        return None
    path = str(path)
    if path.startswith("http"):
        return path
    return "https://www.amazon.jobs" + path


def compact_job(job, city, norm):
    basic = str(value(job, "basic_qualifications") or "")
    pref = str(value(job, "preferred_qualifications") or "")
    desc = str(value(job, "description") or "")
    all_text = " ".join((basic, pref, desc))
    yrs = years_mentions(basic + " " + pref)
    salaries = salary_lines(all_text)
    return {
        "job_id": job_id(job),
        "title": value(job, "title"),
        "location": value(job, "location") or norm,
        "target_city": city,
        "normalized_location": norm,
        "company": value(job, "company_name", "company"),
        "job_category": value(job, "job_category", "category"),
        "business_category": value(job, "business_category"),
        "posted_date": value(job, "posted_date", "posted_at", "updated_time"),
        "apply_url": canonical_url(job),
        "years_mentions": yrs,
        "experience_preferably_le_5": (min(yrs) <= 5 if yrs else None),
        "salary_evidence": salaries,
        "basic_qualifications": basic,
        "preferred_qualifications": pref,
    }


def main():
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": "Amazon Jobs public /en/search.json API",
        "scope": ["Milan", "Rome", "London"],
        "global_coverage": "NOT_CHECKED",
        "global_coverage_reason": "Target-only city search; worldwide inventory completeness is intentionally not certified.",
        "locations": {},
        "target_jobs": [],
    }

    seen = set()
    for city, spec in TARGETS.items():
        norms, probe_url, probe_hits = discover_norms(city, spec)
        city_jobs = []
        total_inventory = 0
        search_urls = []
        for norm in norms:
            jobs, hits, urls = enumerate_norm(norm)
            total_inventory += hits
            search_urls.extend(urls)
            for job in jobs:
                jid = job_id(job)
                key = (city, jid)
                if key in seen:
                    continue
                seen.add(key)
                city_jobs.append((job, norm))

        target = []
        for job, norm in city_jobs:
            title = value(job, "title")
            if is_target_title(title):
                target.append(compact_job(job, city, norm))

        result["locations"][city] = {
            "normalized_locations": norms,
            "probe_hits": probe_hits,
            "inventory_count": len(city_jobs),
            "api_reported_hits_sum": total_inventory,
            "target_jobs_count": len(target),
            "probe_url": probe_url,
            "search_urls": search_urls,
        }
        result["target_jobs"].extend(target)

    result["target_jobs"].sort(key=lambda x: (x["target_city"], (x["title"] or "").lower(), x["job_id"]))
    result["summary"] = {
        "target_jobs_total": len(result["target_jobs"]),
        "Milan": sum(1 for x in result["target_jobs"] if x["target_city"] == "Milan"),
        "Rome": sum(1 for x in result["target_jobs"] if x["target_city"] == "Rome"),
        "London": sum(1 for x in result["target_jobs"] if x["target_city"] == "London"),
    }

    with open("amazon_target_check.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(result["summary"], indent=2))
    for x in result["target_jobs"]:
        print(f"{x['target_city']} | {x['title']} | {x['location']} | {x['apply_url']}")


if __name__ == "__main__":
    main()
