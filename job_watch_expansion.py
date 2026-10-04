#!/usr/bin/env python3
"""Install the 2026-10-04 employer-expansion overlay into the normal Job Watch run.

The canonical ats_mapping_jw*.json files remain untouched. This module merges a
small append-only overlay in memory for collection, Workday reconciliation and
audit metrics, then delegates every other stage to job_watch.py.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OVERLAY_PATH = ROOT / "ats_mapping_expansion_20261004.json"
BATCHES = ("jw1", "jw2", "jw3", "jw4")
_ORIGINAL_INVOKE = None


def load_overlay(root: Path = ROOT) -> dict[str, Any]:
    path = root / OVERLAY_PATH.name
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != "1.0":
        raise ValueError("Unsupported Job Watch expansion overlay version")
    batches = data.get("batches")
    if not isinstance(batches, dict) or set(batches) != set(BATCHES):
        raise ValueError("Expansion overlay must define exactly jw1-jw4")
    for batch, rows in batches.items():
        if not isinstance(rows, list):
            raise ValueError(f"Expansion overlay {batch} must be a list")
        names = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("company"):
                raise ValueError(f"Expansion overlay {batch} has an invalid company row")
            if str(row.get("batch", "")).casefold() != batch:
                raise ValueError(f"{row.get('company')}: overlay batch mismatch")
            if not ((row.get("ats") or {}).get("inventory_url")):
                raise ValueError(f"{row.get('company')}: inventory_url missing")
            names.append(row["company"])
        if len(names) != len(set(names)):
            raise ValueError(f"Expansion overlay {batch} contains duplicate companies")
    return data


def merged_mapping(batch: str, root: Path = ROOT, base: dict | None = None) -> dict:
    batch = str(batch).casefold()
    if batch not in BATCHES:
        raise ValueError(f"Unknown Job Watch batch: {batch}")
    if base is None:
        base = json.loads((root / f"ats_mapping_{batch}.json").read_text(encoding="utf-8"))
    if not isinstance(base, dict):
        raise ValueError(f"Canonical mapping for {batch} is not an object")

    out = copy.deepcopy(base)
    rows = list(out.get("companies") or [])
    existing = {row.get("company") for row in rows if isinstance(row, dict) and row.get("company")}

    additions = (load_overlay(root).get("batches") or {}).get(batch) or []
    for row in additions:
        name = row["company"]
        if name in existing:
            raise ValueError(f"{name}: expansion would duplicate canonical {batch} mapping")
        rows.append(copy.deepcopy(row))
        existing.add(name)

    out["companies"] = rows
    out["last_mapped"] = max(str(out.get("last_mapped") or ""), "2026-10-04")
    summary = dict(out.get("summary") or {})
    summary["companies_analyzed"] = len(rows)
    for level in ("FULL", "STRONG", "PARTIAL", "OPAQUE"):
        summary[level] = sum(
            1
            for row in rows
            if str(((row.get("verification") or {}).get("level") or "")).upper() == level
        )
    out["summary"] = summary
    return out


def _patched_mapping_reader(original, batch: str, root: Path):
    target = f"ats_mapping_{batch}.json"

    def reader(path, default=None):
        payload = original(path, default)
        if Path(path).name == target:
            return merged_mapping(batch, root=root, base=payload)
        return payload

    return reader


def collect_batch(batch: str):
    import collector

    batch = str(batch).casefold()
    original = collector.read_json
    collector.read_json = _patched_mapping_reader(original, batch, ROOT)
    try:
        return collector.collect_batch(batch)
    finally:
        collector.read_json = original


def reconcile_batch(batch: str):
    import reconcile_workday_target_paths as reconcile

    batch = str(batch).casefold()
    original = reconcile.read_json

    def reader(name, default=None):
        payload = original(name, default)
        if Path(name).name == f"ats_mapping_{batch}.json":
            return merged_mapping(batch, root=ROOT, base=payload)
        return payload

    reconcile.read_json = reader
    try:
        return reconcile.reconcile_batch(batch)
    finally:
        reconcile.read_json = original


def write_batch_metrics(batch: str):
    """Run the normal audit while exposing the same expanded mapping used to collect."""
    import audit_job_watch as audit

    batch = str(batch).casefold()
    original = audit.read_json

    def reader(path, default):
        payload = original(path, default)
        if Path(path).name == f"ats_mapping_{batch}.json":
            return merged_mapping(batch, root=ROOT, base=payload)
        return payload

    audit.read_json = reader
    try:
        return audit.write_batch_metrics(batch)
    finally:
        audit.read_json = original


def invoke(module: str, function: str, *args):
    if module == "collector" and function == "collect_batch":
        return collect_batch(*args)
    if module == "reconcile_workday_target_paths" and function == "reconcile_batch":
        return reconcile_batch(*args)
    if module == "audit_job_watch" and function == "write_batch_metrics":
        return write_batch_metrics(*args)
    if _ORIGINAL_INVOKE is None:
        raise RuntimeError("Expansion runner is not installed")
    return _ORIGINAL_INVOKE(module, function, *args)


def regenerate(name: str):
    """Fresh-process regeneration used by job_watch.publish on an origin/main race."""
    subprocess.run(
        [sys.executable, str(ROOT / "job_watch_expansion.py"), name],
        cwd=ROOT,
        check=True,
    )


def install():
    global _ORIGINAL_INVOKE
    load_overlay(ROOT)  # fail closed before touching any generated state
    import job_watch

    if _ORIGINAL_INVOKE is None:
        _ORIGINAL_INVOKE = job_watch.invoke
    job_watch.invoke = invoke
    job_watch.regenerate = regenerate
    return job_watch


def main():
    job_watch = install()
    return job_watch.main()


if __name__ == "__main__":
    raise SystemExit(main())
