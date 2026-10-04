#!/usr/bin/env python3
"""Install the 2026-10-04 employer-expansion overlay into the normal Job Watch run.

The canonical ats_mapping_jw*.json files remain untouched. This module merges a
small append-only overlay in memory for collection, Workday reconciliation,
semantic enrichment and audit metrics, then delegates every other stage to
job_watch.py.

It also applies two production-run corrections that must stay coupled to the
overlay until they are promoted into the canonical pipeline:
- Opella's official Workday CXS endpoint is blocked from the GitHub runner, so
  its source is treated as an official-site PARTIAL probe instead of FAILED.
- South-African "East London" locations must not satisfy the London UK matcher.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OVERLAY_PATH = ROOT / "ats_mapping_expansion_20261004.json"
BATCHES = ("jw1", "jw2", "jw3", "jw4")
_ORIGINAL_INVOKE = None

# Failures produced by the first live expansion run because the semantic
# enricher could not see overlay mappings. Drop only these stale cooldown rows
# so the corrected mapping is retried immediately.
_MAPPING_FAILURE_RETRY_COMPANIES = {"Experian", "Contentsquare"}
_MAPPING_FAILURE_TOKENS = ("http 400", "no lever tenant")


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


def _runtime_corrected_row(row: dict) -> dict:
    """Apply live-run corrections without mutating the retained research overlay."""
    out = copy.deepcopy(row)
    if out.get("company") != "Opella":
        return out

    ats = dict(out.get("ats") or {})
    ats.update(
        {
            "family": "Custom official careers / Workday frontend",
            "career_site": "https://www.opella.com/en/careers",
            "inventory_url": "https://www.opella.com/en/careers",
            "public_api_or_feed": None,
        }
    )
    out["ats"] = ats

    verification = dict(out.get("verification") or {})
    verification.update(
        {
            "level": "PARTIAL",
            "method": "official_career_site_dynamic",
            "location_filter_supported": True,
            "locations": ["Italy", "Milan", "Milano", "Rome", "Roma", "London"],
            "pagination": "Official Opella careers page links to Workday country boards; GitHub runner cannot certify the Workday CXS inventory because the endpoint returns HTTP 403.",
            "total_count_available": False,
            "full_inventory_possible": False,
        }
    )
    out["verification"] = verification

    method = dict(out.get("job_watch_method") or {})
    method.update(
        {
            "primary": "Probe Opella's official careers page and retain official country/job links exposed by the live site.",
            "fallback": "Keep PARTIAL coverage until the Opella Workday CXS inventory is accessible and can be exhaustively reconciled from the GitHub runner.",
        }
    )
    out["job_watch_method"] = method

    limitations = list(out.get("limitations") or [])
    note = (
        "Production run 2026-10-04: Opella's chloe.wd3 Workday CXS jobs endpoint "
        "returned HTTP 403 from GitHub Actions; treat as PARTIAL official-source "
        "coverage rather than a collector failure."
    )
    if note not in limitations:
        limitations.append(note)
    out["limitations"] = limitations
    return out


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
    for source_row in additions:
        row = _runtime_corrected_row(source_row)
        name = row["company"]
        if name in existing:
            raise ValueError(f"{name}: expansion would duplicate canonical {batch} mapping")
        rows.append(row)
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


def _expanded_location_matcher(original):
    """Keep the canonical matcher but reject known London false positives."""

    def matcher(location, company_name=None):
        if not original(location, company_name):
            return False
        text = str(location or "")
        if re.search(r"\bEast\s+London\b", text, re.I) and re.search(
            r"\b(?:ZAF|South\s+Africa)\b", text, re.I
        ):
            return False
        return True

    return matcher


def _patched_enrichment_reader(original, root: Path):
    """Expose merged ATS mappings to enrichment and clear stale mapping-bug cooldowns."""

    def reader(name, default=None):
        payload = original(name, default)
        filename = Path(name).name

        mapping_match = re.fullmatch(r"ats_mapping_(jw[1-4])\.json", filename)
        if mapping_match:
            return merged_mapping(mapping_match.group(1), root=root, base=payload)

        cache_match = re.fullmatch(r"semantic_jd_cache_(jw[1-4])\.json", filename)
        if cache_match and isinstance(payload, dict):
            out = copy.deepcopy(payload)
            records = out.get("records")
            if isinstance(records, dict):
                for key, row in list(records.items()):
                    if not isinstance(row, dict):
                        continue
                    error_text = str(row.get("error") or "").casefold()
                    if (
                        row.get("status") == "FAILED"
                        and row.get("company") in _MAPPING_FAILURE_RETRY_COMPANIES
                        and any(token in error_text for token in _MAPPING_FAILURE_TOKENS)
                    ):
                        records.pop(key, None)
            return out

        return payload

    return reader


def collect_batch(batch: str):
    import collector

    batch = str(batch).casefold()
    original_reader = collector.read_json
    original_matcher = collector.location_matches
    collector.read_json = _patched_mapping_reader(original_reader, batch, ROOT)
    collector.location_matches = _expanded_location_matcher(original_matcher)
    try:
        return collector.collect_batch(batch)
    finally:
        collector.read_json = original_reader
        collector.location_matches = original_matcher


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


def enrich_semantic(*args):
    """Run the standard enricher against the same merged mapping used by collection."""
    import enrich_semantic_jds as enrich

    original = enrich.load
    enrich.load = _patched_enrichment_reader(original, ROOT)
    try:
        return enrich.main(*args)
    finally:
        enrich.load = original


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
    if module == "enrich_semantic_jds" and function == "main":
        return enrich_semantic(*args)
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
