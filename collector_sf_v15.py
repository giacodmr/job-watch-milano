#!/usr/bin/env python3
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

import collector as base

# Experimental SuccessFactors hardening for the v1.5 branch.
# Keep the production collector untouched until this passes a full run.
base.MAX_PAGES = 400

_orig_sf_startrow = base.sf_startrow


def sf_startrow(url: str) -> int:
    """Read SuccessFactors offset from either ?startrow=N or jobs2web path pagination.

    Common public SuccessFactors variants use both forms:
    - /search/?...&startrow=25
    - /viewalljobs/50/
    - /go/Search-Jobs/<category-id>/25/
    Only an already-exposed numeric pagination segment is interpreted; no endpoint is guessed.
    """
    try:
        vals = parse_qs(urlparse(url).query).get("startrow") or []
        if vals:
            return int(vals[0])
    except Exception:
        pass

    try:
        path = unquote(urlparse(url).path)
        parts = [p for p in path.split("/") if p]
        if not parts:
            return 0
        # jobs2web path pagination always exposes the offset as the last numeric
        # segment after a known inventory surface. Category ids in /go/.../<id>/
        # are therefore not mistaken for offsets unless another numeric segment follows.
        if re.fullmatch(r"\d+", parts[-1] or ""):
            low = "/" + "/".join(parts[:-1]).casefold() + "/"
            if "/viewalljobs/" in low or "/search/" in low:
                return int(parts[-1])
            if "/go/" in low:
                numeric_before = [p for p in parts[:-1] if re.fullmatch(r"\d+", p or "")]
                if numeric_before:
                    return int(parts[-1])
    except Exception:
        pass
    return 0


base.sf_startrow = sf_startrow


if __name__ == "__main__":
    raise SystemExit(base.main())
