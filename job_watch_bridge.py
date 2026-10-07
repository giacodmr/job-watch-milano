#!/usr/bin/env python3
"""GitHub Actions bridge for ChatGPT Job Watch worker packets.

Requests are small versioned JSON files committed under .job_watch_bridge/requests/.
Full JD packets are written only to a temporary output path for Actions artifact/log
transport. Semantic decisions are applied only through semantic_worker.apply_packet.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from pipeline_state import BATCHES

ROOT = Path(__file__).resolve().parent
REQUEST_DIR = ROOT / ".job_watch_bridge" / "requests"
VERSION = "1.0"
MAX_LIMIT = 5


def _fail(message: str) -> ValueError:
    return ValueError(message)


def load_request(path: Path) -> dict:
    path = path.resolve()
    request_root = REQUEST_DIR.resolve()
    if request_root not in path.parents or path.suffix != ".json":
        raise _fail("request_path_outside_bridge")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise _fail("request_must_be_object")
    if data.get("version") != VERSION:
        raise _fail("request_version_invalid")
    request_id = str(data.get("request_id") or "")
    if request_id != path.stem:
        raise _fail("request_id_filename_mismatch")
    if data.get("action") not in {"select", "apply"}:
        raise _fail("request_action_invalid")
    if data.get("batch") not in BATCHES:
        raise _fail("request_batch_invalid")
    return data


def validate_select_request(data: dict) -> None:
    limit = data.get("limit")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise _fail("select_limit_invalid")
    if data.get("fetch") is not True:
        raise _fail("select_requires_fetch")
    for field in ("expected_job_key", "expected_fingerprint"):
        if field in data and not str(data.get(field) or "").strip():
            raise _fail(f"{field}_invalid")


def validate_apply_request(data: dict) -> dict:
    parent = str(data.get("parent_request_id") or "")
    if not parent:
        raise _fail("parent_request_id_missing")
    packet_sha = str(data.get("packet_sha256") or "")
    if len(packet_sha) != 64 or any(c not in "0123456789abcdef" for c in packet_sha.lower()):
        raise _fail("packet_sha256_invalid")
    patch = data.get("patch")
    if not isinstance(patch, dict):
        raise _fail("patch_missing")
    if patch.get("batch") != data["batch"]:
        raise _fail("patch_batch_mismatch")
    if not isinstance(patch.get("snapshot"), dict) or not patch["snapshot"]:
        raise _fail("patch_snapshot_missing")
    decisions = patch.get("semantic_decisions")
    if not isinstance(decisions, dict) or not 1 <= len(decisions) <= MAX_LIMIT:
        raise _fail("patch_decision_count_invalid")
    return patch


def _run_json_command(args: list[str]) -> dict:
    proc = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(
            f"command_failed:{' '.join(args)}\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"command_returned_non_json:{proc.stdout[-2000:]}") from exc


def select(data: dict, output: Path) -> dict:
    validate_select_request(data)
    args = [sys.executable, "semantic_worker.py", "select", data["batch"], "--limit", str(data["limit"]), "--fetch"]
    packet = _run_json_command(args)
    records = packet.get("records") or []
    if not records:
        raise RuntimeError("select_returned_no_records")
    first = records[0]
    expected_key = data.get("expected_job_key")
    if expected_key and first.get("job_key") != expected_key:
        raise RuntimeError(f"unexpected_first_job:{first.get('job_key')}")
    expected_fingerprint = data.get("expected_fingerprint")
    if expected_fingerprint and first.get("fingerprint") != expected_fingerprint:
        raise RuntimeError(f"unexpected_fingerprint:{first.get('fingerprint')}")
    if any(rec.get("jd_error") for rec in records):
        errors = {rec.get("job_key"): rec.get("jd_error") for rec in records if rec.get("jd_error")}
        raise RuntimeError("jd_fetch_failed:" + json.dumps(errors, ensure_ascii=False, sort_keys=True))
    if any(not (rec.get("jd") or {}).get("text") for rec in records):
        raise RuntimeError("jd_missing_from_packet")
    output.write_text(json.dumps(packet, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    raw = output.read_bytes()
    return {
        "version": VERSION,
        "request_id": data["request_id"],
        "action": "select",
        "batch": data["batch"],
        "record_count": len(records),
        "job_keys": [rec.get("job_key") for rec in records],
        "fingerprints": [rec.get("fingerprint") for rec in records],
        "packet_sha256": hashlib.sha256(raw).hexdigest(),
    }


def pending_counts() -> dict:
    from sync_analysis_state import project_batch

    by_batch = {batch.upper(): len(project_batch(batch, ROOT)["queue"]) for batch in BATCHES}
    return {"by_batch": by_batch, "total": sum(by_batch.values())}


def apply(data: dict, patch_path: Path, receipt_path: Path) -> dict:
    patch = validate_apply_request(data)
    before = pending_counts()
    patch_path.write_text(json.dumps(patch, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "semantic_worker.py", "apply", data["batch"], "--patch", str(patch_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(f"apply_failed\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}")
    subprocess.run([sys.executable, "job_watch.py", "sync"], cwd=ROOT, check=True)
    after = pending_counts()
    receipt = {
        "version": VERSION,
        "request_id": data["request_id"],
        "parent_request_id": data["parent_request_id"],
        "action": "apply",
        "batch": data["batch"],
        "packet_sha256": data["packet_sha256"],
        "apply_stdout": proc.stdout.strip(),
        "pending_before": before,
        "pending_after": after,
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--packet-output", type=Path)
    parser.add_argument("--patch-output", type=Path, default=Path("/tmp/job-watch-bridge-patch.json"))
    parser.add_argument("--receipt-output", type=Path, default=Path("/tmp/job-watch-bridge-receipt.json"))
    args = parser.parse_args()

    data = load_request(args.request)
    if data["action"] == "select":
        if not args.packet_output:
            parser.error("--packet-output required for select")
        result = select(data, args.packet_output)
    else:
        result = apply(data, args.patch_output, args.receipt_output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
