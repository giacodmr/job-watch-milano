#!/usr/bin/env python3
from __future__ import annotations

import requests

import collector as base
import collector_v14 as v14

# v1.4 hardening layer used for the second branch test. It deliberately keeps
# the first v1.4 implementation intact while we validate two runtime edge cases.
_original_oracle_get_page = v14.oracle_get_page
_original_v14_choose = v14.choose
_original_workday = base.collect_workday


def oracle_get_page_safe(host: str, site: str, offset: int):
    try:
        return _original_oracle_get_page(host, site, offset)
    except requests.exceptions.SSLError as e:
        # A broken/unsupported TLS chain on the branded career host means the
        # public inventory cannot be safely verified from GitHub Actions. This
        # is an inability to prove completeness, not a bad structured response.
        raise base.NotCheckable(
            f"Oracle Candidate Experience TLS validation failed on {host}; inventory cannot be safely verified"
        ) from e


v14.oracle_get_page = oracle_get_page_safe


def collect_workday_resilient(company: dict):
    """Retry once when a live Workday inventory changes during pagination."""
    last_error = None
    for _attempt in range(2):
        try:
            return _original_workday(company)
        except base.CollectorError as e:
            message = str(e)
            if "paging stopped early" not in message and "count mismatch" not in message:
                raise
            last_error = e

    # Two inconsistent full walks mean we cannot prove an exhaustive snapshot.
    # Preserve the core rule: never claim VERIFIED when counts do not reconcile.
    raise base.NotCheckable(
        f"Workday inventory changed during enumeration after retry: {last_error}"
    )


def choose(company: dict):
    fn = _original_v14_choose(company)
    if fn is _original_workday:
        return collect_workday_resilient
    return fn


base.choose = choose


def main(argv=None):
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
