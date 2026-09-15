#!/usr/bin/env python3
from __future__ import annotations

import collector as base
import collector_v14 as oracle_layer
import collector_v14f  # noqa: F401 - installs all validated v1.4 layers through v14f

_original_oracle = oracle_layer.collect_oracle


def collect_oracle_resilient(company: dict):
    """Retry one complete Oracle inventory walk when the live total moves mid-run."""
    last_error = None
    for _attempt in range(2):
        try:
            return _original_oracle(company)
        except base.NotCheckable as e:
            message = str(e).casefold()
            if not any(
                marker in message
                for marker in (
                    "pagination stopped early",
                    "count mismatch",
                    "total changed",
                )
            ):
                raise
            last_error = e

    raise base.NotCheckable(
        f"Oracle inventory changed during enumeration after retry: {last_error}"
    )


# oracle_layer.choose resolves collect_oracle in its own module namespace at call
# time, so replacing the function here hardens every Oracle company without
# duplicating dispatch logic or inventing a new backend.
oracle_layer.collect_oracle = collect_oracle_resilient


def main(argv=None):
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
