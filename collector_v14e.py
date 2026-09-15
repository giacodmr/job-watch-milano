#!/usr/bin/env python3
from __future__ import annotations

import copy

import collector as base
import collector_v14b as hardening
import collector_v14d  # noqa: F401 - installs Oracle, Workday hardening, SR, Teamtailor and SF layers

# Public Workday boards independently evidenced from live official job URLs/pages.
# These are explicit mappings only: no hostname/site guessing is performed.
WORKDAY_PUBLIC_OVERRIDES = {
    "Euronext": "https://hrhub.wd3.myworkdayjobs.com/Euronext_Career_Page",
    "ING Italia": "https://ing.wd3.myworkdayjobs.com/ICSGBLCOR",
    "Salesforce": "https://salesforce.wd12.myworkdayjobs.com/External_Career_Site",
    "Roche": "https://roche.wd3.myworkdayjobs.com/roche-ext",
    "Sanofi": "https://sanofi.wd3.myworkdayjobs.com/SanofiCareers",
    "Unilever": "https://unilever.wd3.myworkdayjobs.com/Unilever_Experienced_Professionals",
    "Johnson & Johnson": "https://jj.wd5.myworkdayjobs.com/JJ",
    "Diageo": "https://diageo.wd3.myworkdayjobs.com/Diageo_Careers",
    "Novartis": "https://novartis.wd3.myworkdayjobs.com/Novartis_Careers",
}

_previous_choose = base.choose
_previous_known_skip = base.known_skip_reason


def workday_override_company(company: dict) -> dict:
    name = base.clean_text(company.get("company"))
    inventory = WORKDAY_PUBLIC_OVERRIDES.get(name or "")
    if not inventory:
        return company
    patched = copy.deepcopy(company)
    ats = dict(patched.get("ats") or {})
    ats["family"] = "Workday"
    ats["inventory_url"] = inventory
    patched["ats"] = ats
    return patched


def collect_verified_workday_override(company: dict):
    patched = workday_override_company(company)
    try:
        return hardening.collect_workday_resilient(patched)
    except base.CollectorError as e:
        # A very large inventory exceeding our explicit page ceiling is an
        # inability to prove completeness safely, not proof that the feed failed.
        if "pagination safety limit" in str(e).casefold():
            raise base.NotCheckable(
                f"Workday inventory exceeds safe exhaustive-page limit: {e}"
            ) from e
        raise


def known_skip_reason(company: dict) -> str | None:
    name = base.clean_text(company.get("company"))
    if name in WORKDAY_PUBLIC_OVERRIDES:
        # Supersedes legacy invalid Lever/other mappings only because an explicit,
        # independently evidenced public Workday board is now configured.
        return None
    return _previous_known_skip(company)


def choose(company: dict):
    name = base.clean_text(company.get("company"))
    if name in WORKDAY_PUBLIC_OVERRIDES:
        return collect_verified_workday_override
    return _previous_choose(company)


base.known_skip_reason = known_skip_reason
base.choose = choose


def main(argv=None):
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
