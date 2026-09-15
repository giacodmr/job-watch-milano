#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
TODAY = "2026-09-15"

WORKDAY_BOARDS = {
    "Euronext": "https://hrhub.wd3.myworkdayjobs.com/Euronext_Career_Page",
    "ING Italia": "https://ing.wd3.myworkdayjobs.com/ICSGBLCOR",
    "Mastercard": "https://mastercard.wd1.myworkdayjobs.com/CorporateCareers",
    "Salesforce": "https://salesforce.wd12.myworkdayjobs.com/External_Career_Site",
    "Alvarez & Marsal": "https://alvarezandmarsal.wd1.myworkdayjobs.com/alvarezandmarsal",
    "Cisco": "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers",
    "GE Vernova": "https://gevernova.wd5.myworkdayjobs.com/Vernova_ExternalSite",
    "Roche": "https://roche.wd3.myworkdayjobs.com/roche-ext",
    "Sanofi": "https://sanofi.wd3.myworkdayjobs.com/SanofiCareers",
    "Johnson & Johnson": "https://jj.wd5.myworkdayjobs.com/JJ",
    "Diageo": "https://diageo.wd3.myworkdayjobs.com/Diageo_Careers",
    "Novartis": "https://novartis.wd3.myworkdayjobs.com/Novartis_Careers",
}

SMARTRECRUITERS_BOARDS = {
    "Wise": "Wise",
    "Roland Berger": "RolandBerger",
    "ServiceNow": "ServiceNow",
}


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def workday_cxs(board: str) -> str:
    p = urlparse(board)
    host = p.netloc
    tenant = host.split(".")[0]
    parts = [unquote(x) for x in p.path.split("/") if x]
    if not host or not parts:
        raise RuntimeError(f"Invalid Workday board: {board}")
    site = parts[0]
    return f"https://{host}/wday/cxs/{tenant}/{site}/jobs"


def promote_mappings() -> None:
    found_workday = set()
    found_sr = set()
    for batch in ("jw1", "jw2", "jw3", "jw4"):
        path = ROOT / f"ats_mapping_{batch}.json"
        data = load_json(path)
        changed = False
        for company in data.get("companies") or []:
            name = company.get("company")
            if name in WORKDAY_BOARDS:
                board = WORKDAY_BOARDS[name]
                ats = dict(company.get("ats") or {})
                ats["family"] = "Workday"
                ats["inventory_url"] = board
                ats["public_api_or_feed"] = workday_cxs(board)
                company["ats"] = ats
                verification = dict(company.get("verification") or {})
                verification.update(
                    {
                        "level": "FULL",
                        "method": "workday_cxs_inventory",
                        "total_count_available": True,
                        "full_inventory_possible": True,
                        "pagination": "Workday CXS limit/offset; exact total reconciliation required",
                    }
                )
                company["verification"] = verification
                company["last_mapped"] = TODAY
                found_workday.add(name)
                changed = True
            elif name in SMARTRECRUITERS_BOARDS:
                tenant = SMARTRECRUITERS_BOARDS[name]
                ats = dict(company.get("ats") or {})
                ats["family"] = "SmartRecruiters"
                ats["tenant"] = tenant
                ats["inventory_url"] = f"https://jobs.smartrecruiters.com/{tenant}"
                ats["public_api_or_feed"] = f"https://api.smartrecruiters.com/v1/companies/{tenant}/postings"
                company["ats"] = ats
                verification = dict(company.get("verification") or {})
                verification.update(
                    {
                        "level": "FULL",
                        "method": "smartrecruiters_public_posting_api",
                        "total_count_available": True,
                        "full_inventory_possible": True,
                        "pagination": "SmartRecruiters limit/offset; exact totalFound reconciliation required",
                    }
                )
                company["verification"] = verification
                company["last_mapped"] = TODAY
                found_sr.add(name)
                changed = True
        if changed:
            save_json(path, data)

    missing = (set(WORKDAY_BOARDS) - found_workday) | (set(SMARTRECRUITERS_BOARDS) - found_sr)
    if missing:
        raise RuntimeError(f"Mapping promotion targets not found: {sorted(missing)}")


def clean_experimental_history() -> None:
    # The experimental branch briefly treated Unilever's explicitly partial
    # Experienced Professionals board as complete. Do not let those test rows
    # survive as UNKNOWN history when the final conservative v1.4 restores it
    # to NOT_CHECKED.
    path = ROOT / "current_jobs_jw4.json"
    if not path.exists():
        return
    data = load_json(path)
    changed = False
    for company in data.get("companies") or []:
        if company.get("company") == "Unilever":
            company["jobs"] = []
            company["target_jobs_count"] = 0
            changed = True
    if changed:
        save_json(path, data)


ENHANCEMENTS = r'''

# === JOB WATCH V1.4 STANDALONE ENHANCEMENTS ===
# Generic extensions validated on the ats-oracle-v14 branch. No company-specific
# endpoint guessing lives here: verified backend URLs belong in the mapping JSONs.

ORACLE_SCOPE_NAME = "Oracle Recruiting Cloud / Oracle HCM Candidate Experience"
TEAMTAILOR_SCOPE_NAME = "Teamtailor public career board"
ORACLE_HOST_RE = re.compile(r"https?://([A-Za-z0-9.-]+\.oraclecloud\.com)(?=[:/\"'\\]|$)", re.I)
ORACLE_SITE_RE = re.compile(r"/sites/([^/?#]+)(?:/|$)", re.I)
ORACLE_PAGE_LIMIT = 25
TT_COUNT_RE = re.compile(r"\b([\d.,]+)\s+jobs?\b", re.I)
TT_JOB_PATH_RE = re.compile(r"/jobs/(\d+)(?:[-/]|$)", re.I)
SF_SHOWING_TOTAL_RE = re.compile(r"\bShowing\s+\d+\s+to\s+\d+\s+of\s+([\d.,\s]+)\s+Jobs?\b", re.I)

if not any(getattr(p, "pattern", None) == SF_SHOWING_TOTAL_RE.pattern for p in SF_TOTAL_PATTERNS):
    SF_TOTAL_PATTERNS = tuple(SF_TOTAL_PATTERNS) + (SF_SHOWING_TOTAL_RE,)

_is_sf_search_path_v13 = is_sf_search_path

def is_sf_search_path(url: str) -> bool:
    if _is_sf_search_path_v13(url):
        return True
    return "/go/" in urlparse(url).path.casefold()


_collect_workday_v13 = collect_workday

def collect_workday(company):
    last_error = None
    for _attempt in range(2):
        try:
            return _collect_workday_v13(company)
        except CollectorError as e:
            message = str(e).casefold()
            if "pagination safety limit" in message:
                raise NotCheckable(f"Workday inventory exceeds safe exhaustive-page limit: {e}") from e
            if "paging stopped early" not in message and "count mismatch" not in message:
                raise
            last_error = e
    raise NotCheckable(f"Workday inventory changed during enumeration after retry: {last_error}")


_collect_smartrecruiters_v13 = collect_smartrecruiters

def collect_smartrecruiters(company):
    last_error = None
    for _attempt in range(2):
        try:
            return _collect_smartrecruiters_v13(company)
        except CollectorError as e:
            message = str(e).casefold()
            if "count mismatch" not in message and "paging stopped early" not in message:
                raise
            last_error = e
    raise NotCheckable(f"SmartRecruiters inventory changed during enumeration after retry: {last_error}")


class TeamtailorPageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.visible_parts = []
        self.jobs = []
        self.current = None
        self.in_job_anchor = False

    def _finish_current(self):
        if self.current is None:
            return
        title = clean_text(" ".join(self.current.get("title_parts") or []))
        parts = [clean_text(x) for x in self.current.get("context_parts") or []]
        parts = [x for x in parts if x and x != title]
        self.current["title"] = title
        self.current["context_parts"] = parts
        self.jobs.append(self.current)
        self.current = None
        self.in_job_anchor = False

    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "a":
            return
        a = {str(k).casefold(): v for k, v in attrs if k}
        href = a.get("href")
        if not href:
            return
        absolute = urljoin(self.base_url, href)
        p = urlparse(absolute)
        if p.netloc.casefold() != urlparse(self.base_url).netloc.casefold():
            return
        m = TT_JOB_PATH_RE.search(unquote(p.path))
        if not m:
            return
        self._finish_current()
        self.current = {"source_id": m.group(1), "url": absolute, "title_parts": [], "context_parts": []}
        self.in_job_anchor = True

    def handle_endtag(self, tag):
        if tag.casefold() == "a" and self.in_job_anchor:
            self.in_job_anchor = False

    def handle_data(self, data):
        s = clean_text(data)
        if not s:
            return
        self.visible_parts.append(s)
        if self.current is not None:
            self.current["context_parts"].append(s)
            if self.in_job_anchor:
                self.current["title_parts"].append(s)

    def close(self):
        super().close()
        self._finish_current()

    @property
    def visible_text(self):
        return " ".join(self.visible_parts)


def teamtailor_total(text: str):
    matches = []
    for m in TT_COUNT_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(1))
        if digits:
            matches.append(int(digits))
    unique = sorted(set(matches))
    return unique[0] if len(unique) == 1 else None


def teamtailor_location(parts):
    candidates = [x for x in parts if TARGET_LOCATION_RE.search(x or "")]
    return min(candidates, key=len) if candidates else None


def collect_teamtailor(company):
    name = company.get("company")
    ats = company.get("ats") or {}
    inventory = clean_text(ats.get("inventory_url"))
    if not inventory:
        raise CollectorError("Teamtailor inventory URL missing")
    try:
        page_html, final_url = get_html(inventory)
    except Exception as e:
        raise NotCheckable(f"Teamtailor public board could not be read safely: {e}") from e
    parser = TeamtailorPageParser(final_url)
    parser.feed(page_html)
    parser.close()
    expected = teamtailor_total(parser.visible_text)
    if expected is None:
        raise NotCheckable("Teamtailor board does not expose one reconcilable public job total")
    unique = {}
    for raw in parser.jobs:
        sid = clean_text(raw.get("source_id"))
        url = clean_text(raw.get("url"))
        title = clean_text(raw.get("title"))
        if sid and url and title:
            unique[sid] = raw
    if len(unique) != expected:
        raise NotCheckable(f"Teamtailor board count mismatch: retrieved={len(unique)}, total={expected}")
    jobs = []
    for sid, raw in unique.items():
        loc = teamtailor_location(raw.get("context_parts") or [])
        if not location_matches(loc):
            continue
        jobs.append(compact_job(name, sid, title=raw.get("title"), location=loc, canonical=raw.get("url"), apply_url=raw.get("url")))
    return {"coverage": "VERIFIED", "collector": "teamtailor_public_board_metadata", "inventory_count": len(unique), "jobs": jobs, "source_url": final_url}


def oracle_family(company):
    family = (clean_text((company.get("ats") or {}).get("family")) or "").casefold()
    if "taleo" in family:
        return False
    return any(x in family for x in ("oracle recruiting cloud", "oracle hcm", "oracle fusion"))


def oracle_site_from_inventory(inventory: str):
    m = ORACLE_SITE_RE.search(urlparse(inventory).path)
    if not m:
        return None
    site = unquote(m.group(1)).strip()
    return site if site and SAFE_TENANT_RE.fullmatch(site) else None


def oracle_public_job_base(inventory: str, site: str):
    p = urlparse(inventory)
    m = re.search(rf"^(.*?/sites/{re.escape(site)})(?:/.*)?$", p.path, re.I)
    if not m:
        raise NotCheckable("Oracle Candidate Experience site path could not be normalized")
    return f"{p.scheme or 'https'}://{p.netloc}{m.group(1)}"


def oracle_backend_hosts(inventory: str):
    p = urlparse(inventory)
    hosts = [p.netloc] if p.netloc else []
    try:
        r = get_response(inventory)
        text = html.unescape(r.text).replace("\\/", "/")
        for m in ORACLE_HOST_RE.finditer(text):
            host = m.group(1)
            if host.casefold() not in {x.casefold() for x in hosts}:
                hosts.append(host)
        final_host = urlparse(r.url).netloc
        if final_host and final_host.casefold() not in {x.casefold() for x in hosts}:
            hosts.append(final_host)
    except requests.RequestException:
        pass
    return hosts


def oracle_extract_root(data):
    if not isinstance(data, dict):
        raise NotCheckable("Oracle Candidate Experience returned non-object JSON")
    items = data.get("items")
    root = items[0] if isinstance(items, list) and items else data if "requisitionList" in data else None
    if not isinstance(root, dict):
        raise NotCheckable("Oracle Candidate Experience response has no requisition inventory")
    return root


def oracle_location(raw):
    values = []
    primary = clean_text(raw.get("PrimaryLocation"))
    if primary:
        values.append(primary)
    for field in ("secondaryLocations", "otherWorkLocations"):
        for item in raw.get(field) or []:
            if not isinstance(item, dict):
                continue
            value = clean_text(item.get("Name"))
            if not value:
                pieces = [clean_text(item.get("TownOrCity")), clean_text(item.get("Region1")), clean_text(item.get("Country"))]
                value = ", ".join(x for x in pieces if x) or None
            if value and value not in values:
                values.append(value)
    return " | ".join(values) if values else None


def oracle_source_id(raw):
    for field in ("Id", "RequisitionId", "RequisitionNumber", "ExternalRequisitionId"):
        value = clean_text(raw.get(field))
        if value:
            return value
    return None


def oracle_get_page(host: str, site: str, offset: int):
    endpoint = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    finder = f"findReqs;siteNumber={site},limit={ORACLE_PAGE_LIMIT},offset={offset}"
    headers = {"Accept": "application/vnd.oracle.adf.resourcecollection+json, application/json", "Ora-Irc-Language": "en", "REST-Framework-Version": "1"}
    try:
        r = get_session().get(endpoint, params={"onlyData": "true", "expand": "requisitionList.secondaryLocations", "finder": finder}, headers=headers, timeout=TIMEOUT)
    except requests.exceptions.SSLError as e:
        raise NotCheckable(f"Oracle Candidate Experience TLS validation failed on {host}; inventory cannot be safely verified") from e
    if r.status_code in {401, 403, 404, 406, 410}:
        raise NotCheckable(f"Oracle public Candidate Experience endpoint unavailable on {host}: HTTP {r.status_code}")
    r.raise_for_status()
    try:
        return r.json(), r.url
    except ValueError as e:
        raise NotCheckable(f"Oracle endpoint on {host} did not return JSON") from e


def _collect_oracle_once(company):
    name = company.get("company")
    ats = company.get("ats") or {}
    inventory = clean_text(ats.get("inventory_url"))
    if not inventory:
        raise CollectorError("Oracle inventory URL missing")
    site = oracle_site_from_inventory(inventory)
    if not site:
        raise NotCheckable("Oracle Candidate Experience site number is not present in mapped inventory URL")
    public_base = oracle_public_job_base(inventory, site)
    hosts = oracle_backend_hosts(inventory)
    if not hosts:
        raise NotCheckable("No Oracle Candidate Experience host could be evidenced")
    selected_host = None
    first_data = None
    source_url = None
    reasons = []
    for host in hosts:
        try:
            first_data, source_url = oracle_get_page(host, site, 0)
            oracle_extract_root(first_data)
            selected_host = host
            break
        except NotCheckable as e:
            reasons.append(str(e))
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            if status in {401, 403, 404, 406, 410}:
                reasons.append(f"{host}: HTTP {status}")
                continue
            raise CollectorError(f"Oracle Candidate Experience HTTP failure on {host}: {e}") from e
        except requests.RequestException as e:
            raise CollectorError(f"Oracle Candidate Experience request failure on {host}: {e}") from e
    if selected_host is None or first_data is None:
        raise NotCheckable(f"Oracle inventory could not be safely enumerated: {'; '.join(reasons[-3:]) or 'no usable public endpoint'}")
    rows = []
    seen = set()
    total = None
    offset = 0
    for page_index in range(MAX_PAGES):
        data = first_data if page_index == 0 else oracle_get_page(selected_host, site, offset)[0]
        root = oracle_extract_root(data)
        page = root.get("requisitionList")
        if not isinstance(page, list):
            raise NotCheckable("Oracle response does not expose requisitionList as an array")
        if total is None:
            try:
                total = int(root.get("TotalJobsCount"))
            except (TypeError, ValueError) as e:
                raise NotCheckable("Oracle inventory has no valid TotalJobsCount") from e
        for raw in page:
            if not isinstance(raw, dict):
                continue
            sid = oracle_source_id(raw)
            if not sid:
                raise NotCheckable("Oracle requisition lacks a stable public identifier")
            if sid not in seen:
                seen.add(sid)
                rows.append(raw)
        if len(rows) >= total:
            break
        if not page:
            raise NotCheckable(f"Oracle pagination stopped early: retrieved={len(rows)}, total={total}")
        offset += len(page)
    else:
        raise NotCheckable("Oracle inventory exceeds safe exhaustive-page limit")
    if total is None or len(rows) != total:
        raise NotCheckable(f"Oracle count mismatch: retrieved={len(rows)}, total={total}")
    jobs = []
    for raw in rows:
        sid = oracle_source_id(raw)
        loc = oracle_location(raw)
        if not sid or not location_matches(loc):
            continue
        canonical = f"{public_base}/job/{sid}"
        jobs.append(compact_job(name, sid, title=raw.get("Title"), location=loc, department=raw.get("Department") or raw.get("Organization"), employment_type=clean_text(raw.get("JobType")) or clean_text(raw.get("ContractType")), published_at=raw.get("PostedDate"), canonical=canonical, apply_url=canonical))
    return {"coverage": "VERIFIED", "collector": "oracle_recruiting_cloud_ce_metadata", "inventory_count": len(rows), "jobs": jobs, "source_url": source_url or inventory}


def collect_oracle(company):
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


def verified_smartrecruiters_feed(company):
    ats = company.get("ats") or {}
    family = (clean_text(ats.get("family")) or "").casefold()
    verification = company.get("verification") or {}
    tenant = clean_text(ats.get("tenant"))
    feed = clean_text(ats.get("public_api_or_feed"))
    return bool("smartrecruiters" in family and "attrax" not in family and verification.get("full_inventory_possible") is True and tenant and SAFE_TENANT_RE.fullmatch(tenant) and feed and urlparse(feed).netloc.casefold() == "api.smartrecruiters.com")


_choose_v13 = choose

def choose(company):
    if oracle_family(company):
        inventory = clean_text((company.get("ats") or {}).get("inventory_url")) or ""
        if oracle_site_from_inventory(inventory):
            return collect_oracle
    fn = _choose_v13(company)
    if fn is not None:
        return fn
    ats = company.get("ats") or {}
    family = (clean_text(ats.get("family")) or "").casefold()
    verification = company.get("verification") or {}
    if verified_smartrecruiters_feed(company):
        return collect_smartrecruiters
    if "teamtailor" in family and verification.get("full_inventory_possible") is True:
        inventory = clean_text(ats.get("inventory_url")) or ""
        if "/jobs" in urlparse(inventory).path.casefold():
            return collect_teamtailor
    return None


_unsupported_result_v13 = unsupported_result

def unsupported_result(company, reason=None):
    result = _unsupported_result_v13(company, reason)
    if result.get("collector") == "unsupported_or_unverified_v1_3":
        result["collector"] = "unsupported_or_unverified_v1_4"
    if result.get("reason"):
        result["reason"] = result["reason"].replace("collector v1.3", "collector v1.4")
    return result


_collect_batch_v13 = collect_batch

def collect_batch(batch: str, workers: int = DEFAULT_WORKERS):
    payload = _collect_batch_v13(batch, workers=workers)
    payload["version"] = "1.4"
    scope = list(payload.get("collector_scope") or [])
    for value in (ORACLE_SCOPE_NAME, TEAMTAILOR_SCOPE_NAME):
        if value not in scope:
            scope.append(value)
    payload["collector_scope"] = scope
    write_json(ROOT / f"current_jobs_{batch}.json", payload)
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
'''


def build_standalone_collector() -> None:
    path = ROOT / "collector.py"
    text = path.read_text(encoding="utf-8")
    marker = "# === JOB WATCH V1.4 STANDALONE ENHANCEMENTS ==="
    if marker in text:
        return
    guard = '\nif __name__ == "__main__":\n    raise SystemExit(main())'
    pos = text.rfind(guard)
    if pos < 0:
        raise RuntimeError("collector.py final main guard not found")
    text = text[:pos].rstrip() + "\n"
    text = text.replace('COLLECTOR_VERSION = "1.3"', 'COLLECTOR_VERSION = "1.4"')
    text = text.replace('job-watch-milano/1.3', 'job-watch-milano/1.4')
    path.write_text(text + ENHANCEMENTS.lstrip("\n"), encoding="utf-8")


PRODUCTION_WORKFLOW = '''name: Collect Job Watch vacancies

on:
  workflow_dispatch:
  schedule:
    - cron: "30 6 * * *"
      timezone: "Europe/Rome"

permissions:
  contents: write

concurrency:
  group: job-watch-collector
  cancel-in-progress: false

jobs:
  collect:
    runs-on: ubuntu-latest
    timeout-minutes: 20

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependency
        run: python -m pip install --disable-pip-version-check requests

      - name: Syntax check
        run: python -m py_compile collector.py

      - name: Collect public ATS inventories
        run: python collector.py

      - name: Commit updated vacancy snapshots
        shell: bash
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add current_jobs_jw1.json current_jobs_jw2.json current_jobs_jw3.json current_jobs_jw4.json
          if git diff --cached --quiet; then
            echo "No changes to commit."
            exit 0
          fi
          git commit -m "Update Job Watch vacancy snapshots"
          git push
'''


def write_production_workflow() -> None:
    path = ROOT / ".github" / "workflows" / "collect_jobs.yml"
    path.write_text(PRODUCTION_WORKFLOW, encoding="utf-8")


def main() -> None:
    promote_mappings()
    clean_experimental_history()
    build_standalone_collector()
    write_production_workflow()
    print("Prepared standalone collector v1.4 and promoted verified ATS mappings.")


if __name__ == "__main__":
    main()
