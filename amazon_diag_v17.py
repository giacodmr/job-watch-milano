#!/usr/bin/env python3
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
import time
import requests

API = "https://www.amazon.jobs/en/search.json"
TIMEOUT = 45
PAGE = 100
WORKERS = 9
HTTP_RETRIES = 6
SNAPSHOT_ATTEMPTS = 5
CHECK_FACETS = ["category", "schedule_type_id", "employee_class", "job_function_id", "normalized_country_code"]


def session():
    s = requests.Session()
    s.headers.update({"User-Agent":"job-watch-milano/amazon-diagnostic","Accept":"application/json"})
    return s


def get(s, params):
    last = None
    for attempt in range(HTTP_RETRIES):
        try:
            r = s.get(API, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            ctype = (r.headers.get("content-type") or "").casefold()
            if "json" not in ctype:
                raise RuntimeError(f"non-json HTTP {r.status_code} content-type={ctype} bytes={len(r.content)}")
            d = r.json()
            if d.get("error"):
                raise RuntimeError(f"Amazon API error: {d.get('error')}")
            return d
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last = exc
            if attempt + 1 >= HTTP_RETRIES:
                break
            time.sleep((0.8 * (attempt + 1)) + random.uniform(0.0, 0.5))
    raise RuntimeError(f"Amazon request remained unavailable after retries: {last}")


def flat(data, name):
    out = {}
    for item in ((data.get("facets") or {}).get(name + "_facet") or []):
        if isinstance(item, dict):
            for k, v in item.items():
                try: out[str(k)] = int(v)
                except (TypeError, ValueError): pass
    return out


def snapshot():
    s = session()
    params=[("offset","0"),("result_limit","1"),("sort","recent")]
    for f in CHECK_FACETS: params.append(("facets[]",f))
    d=get(s,params)
    facets={f:flat(d,f) for f in CHECK_FACETS}
    sums={f:sum(v.values()) for f,v in facets.items()}
    if not facets["category"]:
        raise RuntimeError("Amazon category facet missing")
    print("SNAPSHOT", {"hits":d.get("hits"),"sums":sums,"category_values":len(facets["category"]),"category_max":max(facets["category"].values())})
    if len(set(sums.values())) != 1:
        raise RuntimeError(f"independent facet sums disagree: {sums}")
    total=next(iter(sums.values()))
    if total <= 10000:
        raise RuntimeError(f"expected uncapped facet total >10000, got {total}")
    return total, facets


def collect_category(name, expected):
    s=session(); seen={}; offset=0
    while offset < expected:
        d=get(s,[("offset",str(offset)),("result_limit",str(PAGE)),("sort","recent"),("category[]",name)])
        hits=int(d.get("hits") or 0)
        if hits != expected:
            raise RuntimeError(f"total changed {expected}->{hits} at offset {offset}")
        rows=d.get("jobs") or []
        if not rows:
            raise RuntimeError(f"no rows before expected total at offset {offset}")
        for job in rows:
            jid=str(job.get("id") or "").strip()
            if not jid:
                raise RuntimeError("missing stable job id")
            if jid in seen:
                raise RuntimeError(f"duplicate id {jid}")
            seen[jid]=job
        offset += len(rows)
    if len(seen) != expected:
        raise RuntimeError(f"reconciled {len(seen)} != {expected}")
    return name, seen


def enumerate_once(attempt):
    total, facets = snapshot()
    categories=facets["category"]
    if any(v >= 10000 for v in categories.values()):
        raise RuntimeError("category partition contains capped bucket")
    print("ATTEMPT_START", attempt, {"total":total,"categories":len(categories)})

    results={}; union={}; memberships={}; errors=[]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures={ex.submit(collect_category,name,count):(name,count) for name,count in categories.items()}
        for fut in as_completed(futures):
            name,count=futures[fut]
            try:
                _name,rows=fut.result()
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                continue
            results[name]=len(rows)
            for jid,job in rows.items():
                memberships.setdefault(jid,[]).append(name)
                union.setdefault(jid,job)
    if errors:
        raise RuntimeError("; ".join(errors[:6]))

    summed=sum(results.values())
    overlaps={jid:names for jid,names in memberships.items() if len(names)>1}
    print("ENUMERATION", {"categories":len(results),"summed":summed,"unique":len(union),"expected_total":total,"overlap_count":len(overlaps)})
    if summed != total:
        raise RuntimeError(f"category retrieved sum {summed} != total {total}")
    if overlaps:
        raise RuntimeError(f"category partition overlaps: {len(overlaps)}")
    if len(union) != total:
        raise RuntimeError(f"global unique reconciliation mismatch {len(union)} != {total}")

    total2, facets2=snapshot()
    if total2 != total or facets2["category"] != categories:
        raise RuntimeError(f"inventory changed during enumeration: {total}->{total2}")
    print("AMAZON_GLOBAL_EXHAUSTIVE_OK", total)
    return total


def main():
    last=None
    for attempt in range(1,SNAPSHOT_ATTEMPTS+1):
        try:
            enumerate_once(attempt)
            return
        except Exception as exc:
            last=exc
            print("ATTEMPT_REJECTED",attempt,repr(exc))
            if attempt < SNAPSHOT_ATTEMPTS:
                time.sleep(2.5)
    raise SystemExit(f"Amazon inventory did not remain stable for an exhaustive snapshot: {last}")


if __name__ == "__main__":
    main()
