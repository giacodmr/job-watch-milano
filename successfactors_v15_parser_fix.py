from pathlib import Path

path = Path("collector.py")
text = path.read_text(encoding="utf-8")
marker = "# === JOB WATCH V1.5 SUCCESSFACTORS CONSERVATIVE METADATA ==="
if marker in text:
    raise SystemExit("conservative SuccessFactors parser already present")
needle = '\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
if needle not in text:
    raise SystemExit("collector.py final main guard not found")
block = r'''
# === JOB WATCH V1.5 SUCCESSFACTORS CONSERVATIVE METADATA ===
# Do not use proximity/token heuristics for location. Start from the v1.4
# table parser and add only the explicit Career Site Builder field-id metadata.
# This deliberately prefers NOT_CHECKED over a false location match.
def merge_sf_page_jobs(base: str, parser: SFPageParser) -> list[dict]:
    jobs = _merge_sf_page_jobs_v14(base, parser)
    for job in jobs:
        if not clean_text(job.get("location")):
            job["location"] = _sf_card_location(parser, job["url"])
        if not clean_text(job.get("published_at")):
            job["published_at"] = _sf_card_date(parser, job["url"])
    return jobs
'''
text = text.replace(needle, "\n" + block.strip() + "\n" + needle)
path.write_text(text, encoding="utf-8")
print("Applied conservative SuccessFactors metadata parser")
