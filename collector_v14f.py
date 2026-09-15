#!/usr/bin/env python3
from __future__ import annotations

import copy

import collector as base
import collector_v14e as v14e  # installs the validated v1.4 layers

# Additional public ATS backends evidenced by current official job URLs or the
# already-verified application backend in the ATS mapping. They are explicit
# overrides: the collector never derives these strings from company names.
v14e.WORKDAY_PUBLIC_OVERRIDES.update(
    {
        "Mastercard": "https://mastercard.wd1.myworkdayjobs.com/CorporateCareers",
        "Cisco": "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers",
        "GE Vernova": "https://gevernova.wd5.myworkdayjobs.com/Vernova_ExternalSite",
        "Alvarez & Marsal": "https://alvarezandmarsal.wd1.myworkdayjobs.com/alvarezandmarsal",
    }
)

_original_smartrecruiters = base.collect_smartrecruiters
_previous_choose = base.choose


def collect_smartrecruiters_resilient(company: dict):
    """Retry once if totalFound moves while the public inventory is paged."""
    last_error = None
    for _attempt in range(2):
        try:
            return _original_smartrecruiters(company)
        except base.CollectorError as e:
            message = str(e)
            if "count mismatch" not in message and "paging stopped early" not in message:
                raise
            last_error = e

    raise base.NotCheckable(
        f"SmartRecruiters inventory changed during enumeration after retry: {last_error}"
    )


# Existing SmartRecruiters dispatchers resolve the function dynamically from
# base, so this hardens H&M/Roland Berger/ServiceNow without duplicating logic.
base.collect_smartrecruiters = collect_smartrecruiters_resilient


def collect_wise(company: dict):
    """Wise publishes its canonical jobs on the public SmartRecruiters board."""
    patched = copy.deepcopy(company)
    ats = dict(patched.get("ats") or {})
    ats["family"] = "SmartRecruiters"
    ats["tenant"] = "Wise"
    ats["inventory_url"] = "https://jobs.smartrecruiters.com/Wise"
    patched["ats"] = ats
    return collect_smartrecruiters_resilient(patched)


def choose(company: dict):
    if base.clean_text(company.get("company")) == "Wise":
        return collect_wise
    return _previous_choose(company)


base.choose = choose


def main(argv=None):
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
