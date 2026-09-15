import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://www.amazon.jobs/en/search.json"
OUTPUT = Path("amazon_target_check.json")
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
    "business analyst", "financial analyst", "finance analyst", "strategy",
    "strategic", "corporate strategy", "business operations", "business planning",
    "planning analyst", "commercial analyst", "operations analyst", "program analyst",
    "fp&a", "finance", "economist",
)

EXCLUDE_TERMS = (
    "manager", " mgr", "director", "principal", "head of", "vice president", " vp",
    "marketing", "advertising", "amazon ads", "crm", "sales account", "account manager",
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
            ("result_limit", page_size), ("sort", "relevant"),
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
    return jobs, hits or 0, urls


def is_target_title(title):
    t = " ".join(str(title or "").lower().split())
    return any(term in t for term in INCLUDE_TERMS) and not any(term in t for term in EXCLUDE_TERMS)


def years_mentions(text):
    vals = []
    for m in re.finditer(r"(?i)(\d{1,2})\s*\+?\s*(?:years?|yrs?)", text or ""):
        n = int(m.group(1))
        if 0 < n < 30:
            vals.append(n)
    return sorted(set(vals))


def job_id(job):
    return str(value(job, "id", "id_icims", "job_id", "requisition_id") or value(job, "job_path") or "")


def canonical_url(job):
    path = value(job, "job_path", "url")
    if not path:
        return None
    path = str(path)
    return path if path.startswith("http") else "https://www.amazon.jobs" + path


def compact_job(job, city, norm):
    basic = str(value(job, "basic_qualifications") or "")
    pref = str(value(job, "preferred_qualifications") or "")
    yrs = years_mentions(basic + " " + pref)
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
        "basic_qualifications": basic,
        "preferred_qualifications": pref,
    }


def fingerprint(job):
    # Ignore volatile status fields; detect meaningful listing changes.
    keys = ("title", "location", "target_city", "company", "job_category", "business_category",
            "posted_date", "apply_url", "years_mentions", "experience_preferably_le_5",
            "basic_qualifications", "preferred_qualifications")
    raw = json.dumps({k: job.get(k) for k in keys}, ensure_ascii=False, sort_keys=True)
    import hashlib
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
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": "Amazon Jobs public /en/search.json API",
        "scope": ["Milan", "Rome", "London"],
        "global_coverage": "NOT_CHECKED",
        "global_coverage_reason": "Target-only city search; worldwide inventory completeness is intentionally not certified.",
        "locations": {}, "target_jobs": [],
    }

    seen = set()
    current_by_id = {}
    for city, spec in TARGETS.items():
        norms, probe_url, probe_hits = discover_norms(city, spec)
        city_jobs, total_inventory, search_urls = [], 0, []
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
            if not is_target_title(value(job, "title")):
                continue
            item = compact_job(job, city, norm)
            item["fingerprint"] = fingerprint(item)
            old = previous.get(item["job_id"])
            if old is None:
                item["status"] = "NEW"
            elif old.get("fingerprint") and old.get("fingerprint") != item["fingerprint"]:
                item["status"] = "UPDATED"
            else:
                item["status"] = "STILL_OPEN"
            target.append(item)
            current_by_id[item["job_id"]] = item

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

    # Preserve disappeared prior target jobs as CLOSED for one snapshot.
    for jid, old in previous.items():
        if jid not in current_by_id and old.get("status") != "CLOSED":
            closed = dict(old)
            closed["status"] = "CLOSED"
            result["target_jobs"].append(closed)

    result["target_jobs"].sort(key=lambda x: (x.get("target_city") or "", x.get("status") or "", (x.get("title") or "").lower(), x.get("job_id") or ""))
    active = [x for x in result["target_jobs"] if x.get("status") != "CLOSED"]
    result["summary"] = {
        "target_jobs_open": len(active),
        "NEW": sum(x.get("status") == "NEW" for x in result["target_jobs"]),
        "UPDATED": sum(x.get("status") == "UPDATED" for x in result["target_jobs"]),
        "STILL_OPEN": sum(x.get("status") == "STILL_OPEN" for x in result["target_jobs"]),
        "CLOSED": sum(x.get("status") == "CLOSED" for x in result["target_jobs"]),
        "Milan": sum(x.get("target_city") == "Milan" and x.get("status") != "CLOSED" for x in result["target_jobs"]),
        "Rome": sum(x.get("target_city") == "Rome" and x.get("status") != "CLOSED" for x in result["target_jobs"]),
        "London": sum(x.get("target_city") == "London" and x.get("status") != "CLOSED" for x in result["target_jobs"]),
    }

    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("AMAZON", json.dumps(result["summary"], ensure_ascii=False))
    for x in result["target_jobs"]:
        if x.get("status") in {"NEW", "UPDATED", "CLOSED"}:
            print(f"  {x.get('status')} | {x.get('target_city')} | {x.get('title')} | {x.get('apply_url')}")


if __name__ == "__main__":
    main()
