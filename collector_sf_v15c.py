#!/usr/bin/env python3
from __future__ import annotations

import collector_sf_v15b as exp

base = exp.base
_ParentSFParser = base.SFPageParser


class SFMultilocationTileParser(_ParentSFParser):
    """Treat Career Site Builder `multilocation` as public location metadata."""

    def handle_starttag(self, tag, attrs):
        patched = list(attrs)
        classes = ""
        for key, value in attrs:
            if str(key).casefold() == "class":
                classes = str(value or "")
                break
        class_set = {x.casefold() for x in classes.split() if x}
        if "section-field" in class_set and "multilocation" in class_set and "location" not in class_set:
            patched = []
            for key, value in attrs:
                if str(key).casefold() == "class":
                    value = f"{value or ''} location".strip()
                patched.append((key, value))
        super().handle_starttag(tag, patched)


base.SFPageParser = SFMultilocationTileParser


if __name__ == "__main__":
    raise SystemExit(base.main())
