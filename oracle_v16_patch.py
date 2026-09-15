from pathlib import Path

path = Path("collector.py")
text = path.read_text(encoding="utf-8")

if "# === JOB WATCH V1.6 ORACLE STABLE SNAPSHOTS ===" in text:
    raise SystemExit("Oracle v1.6 patch already applied")

text = text.replace('COLLECTOR_VERSION = "1.5"', 'COLLECTOR_VERSION = "1.6"', 1)
text = text.replace('job-watch-milano/1.5', 'job-watch-milano/1.6', 1)
text = text.replace('ORACLE_PAGE_LIMIT = 25', 'ORACLE_PAGE_LIMIT = 200', 1)

old_total = '''        if total is None:
            try:
                total = int(root.get("TotalJobsCount"))
            except (TypeError, ValueError) as e:
                raise NotCheckable("Oracle inventory has no valid TotalJobsCount") from e
'''
new_total = '''        try:
            page_total = int(root.get("TotalJobsCount"))
        except (TypeError, ValueError) as e:
            raise NotCheckable("Oracle inventory has no valid TotalJobsCount") from e
        if total is None:
            total = page_total
        elif page_total != total:
            raise NotCheckable(f"Oracle total changed during pagination: {total}->{page_total}")
'''
if old_total not in text:
    raise SystemExit("Oracle total block not found")
text = text.replace(old_total, new_total, 1)

old_return = '''    return {"coverage": "VERIFIED", "collector": "oracle_recruiting_cloud_ce_metadata", "inventory_count": len(rows), "jobs": jobs, "source_url": source_url or inventory}
'''
new_return = '''    return {
        "coverage": "VERIFIED",
        "collector": "oracle_recruiting_cloud_ce_metadata",
        "inventory_count": len(rows),
        "jobs": jobs,
        "source_url": source_url or inventory,
        "_inventory_ids": sorted(seen),
    }
'''
if old_return not in text:
    raise SystemExit("Oracle return block not found")
text = text.replace(old_return, new_return, 1)

old_collect = '''def collect_oracle(company):
    last_error = None
    for _attempt in range(2):
        try:
            return _collect_oracle_once(company)
        except NotCheckable as e:
            msg = str(e).casefold()
            if not any(x in msg for x in ("pagination stopped early", "count mismatch", "total changed")):
                raise
            last_error = e
    raise NotCheckable(f"Oracle inventory changed during enumeration after retry: {last_error}")
'''
new_collect = '''def collect_oracle(company):
    """Require two consecutive identical exhaustive Oracle snapshots.

    A single mathematically reconciled pagination can still race a live board if
    one requisition closes while another opens. Oracle's public CE endpoint caps
    findReqs pages at 200, so use that maximum to minimize the race window, then
    verify the complete requisition-id set a second time. Any instability remains
    NOT_CHECKED rather than being promoted to VERIFIED.
    """
    previous = None
    previous_ids = None
    last_error = None
    for _attempt in range(4):
        try:
            current = _collect_oracle_once(company)
        except NotCheckable as e:
            msg = str(e).casefold()
            retryable = any(
                token in msg
                for token in (
                    "pagination stopped early",
                    "count mismatch",
                    "total changed",
                    "inventory changed",
                )
            )
            if not retryable:
                raise
            last_error = e
            previous = None
            previous_ids = None
            continue

        ids = tuple(current.pop("_inventory_ids", ()))
        if len(ids) != int(current.get("inventory_count") or 0):
            raise NotCheckable(
                f"Oracle stable-snapshot ID reconciliation failed: ids={len(ids)}, "
                f"inventory={current.get('inventory_count')}"
            )

        if previous is not None and previous_ids == ids and previous.get("inventory_count") == current.get("inventory_count"):
            current["collector"] = "oracle_recruiting_cloud_ce_stable_metadata_v16"
            return current

        previous = current
        previous_ids = ids
        last_error = NotCheckable(
            f"Oracle inventory snapshot changed or has not yet been repeated identically: "
            f"count={current.get('inventory_count')}"
        )

    raise NotCheckable(f"Oracle inventory did not yield two consecutive identical exhaustive snapshots: {last_error}")
'''
if old_collect not in text:
    raise SystemExit("Oracle collect block not found")
text = text.replace(old_collect, new_collect, 1)

needle = '\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
if needle not in text:
    raise SystemExit("final main guard not found")
version_block = '''\n# === JOB WATCH V1.6 ORACLE STABLE SNAPSHOTS ===\n_collect_batch_v15_oracle = collect_batch\ndef collect_batch(batch: str, workers: int = DEFAULT_WORKERS):\n    payload = _collect_batch_v15_oracle(batch, workers=workers)\n    payload["version"] = "1.6"\n    write_json(ROOT / f"current_jobs_{batch}.json", payload)\n    return payload\n'''
text = text.replace(needle, version_block + needle, 1)
path.write_text(text, encoding="utf-8")
print("Applied generic Oracle v1.6 stable-snapshot hardening")
