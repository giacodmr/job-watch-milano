#!/usr/bin/env python3
from __future__ import annotations

import re

import collector as base
import collector_v14c  # noqa: F401 - installs Oracle, Workday, SR and Teamtailor layers

# SuccessFactors Recruiting Marketing uses several public templates. Some expose
# their exhaustive job inventory on /go/... category/location pages instead of
# /search/, and many modern templates say "Showing 1 to 25 of N Jobs".
# Both signals are first-party and count-reconcilable; no endpoint is guessed.
_SHOWING_TOTAL = re.compile(
    r"\bShowing\s+\d+\s+to\s+\d+\s+of\s+([\d.,\s]+)\s+Jobs?\b",
    re.I,
)

if not any(getattr(p, "pattern", None) == _SHOWING_TOTAL.pattern for p in base.SF_TOTAL_PATTERNS):
    base.SF_TOTAL_PATTERNS = tuple(base.SF_TOTAL_PATTERNS) + (_SHOWING_TOTAL,)

_original_is_sf_search_path = base.is_sf_search_path


def is_sf_inventory_path(url: str) -> bool:
    if _original_is_sf_search_path(url):
        return True
    # jobs2web / SuccessFactors category and location inventories commonly use
    # /go/<slug>/<numeric-id>/, with pagination staying under the same /go/ path.
    # Completeness is still independently enforced by explicit total == unique
    # job URLs, so recognizing /go/ does not by itself produce VERIFIED.
    return "/go/" in base.urlparse(url).path.casefold()


base.is_sf_search_path = is_sf_inventory_path


def main(argv=None):
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
