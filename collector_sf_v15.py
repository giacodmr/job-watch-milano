#!/usr/bin/env python3
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

import collector as base

# Experimental SuccessFactors hardening for the v1.5 branch.
# Keep the production collector untouched until this passes a full run.
base.MAX_PAGES = 400


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
        if re.fullmatch(r"\d+", parts[-1] or ""):
            low = "/" + "/".join(parts[:-1]).casefold() + "/"
            if "/viewalljobs/" in low or "/search/" in low:
                return int(parts[-1])
            if "/go/" in low:
                # A single numeric segment on a /go/.../<category-id>/ URL is the
                # category id, not pagination. A later numeric segment is offset.
                numeric_before = [p for p in parts[:-1] if re.fullmatch(r"\d+", p or "")]
                if numeric_before:
                    return int(parts[-1])
    except Exception:
        pass
    return 0


base.sf_startrow = sf_startrow


class SFTilePageParser(base.SFPageParser):
    """Extend the classic jobs2web parser with modern SuccessFactors job tiles.

    Newer Career Site Builder pages render jobs as <li class="job-tile"> rather
    than a Title/Location/Date table. We only read fields already present in the
    public HTML; no API endpoint is inferred here.
    """

    def __init__(self):
        super().__init__()
        self.tile_jobs = []
        self._tile = None
        self._tile_depth = 0
        self._title_depth = 0
        self._location_depth = 0
        self._location_parts = []
        self._location_priority = 0

    @staticmethod
    def _attrs(attrs):
        return {str(k).casefold(): v for k, v in attrs if k}

    @staticmethod
    def _classes(value):
        return {x.casefold() for x in str(value or "").split() if x}

    def _finish_location(self):
        if self._tile is None:
            self._location_parts = []
            self._location_priority = 0
            return
        value = base.clean_text(" ".join(self._location_parts))
        if value and value.casefold() not in {"location", "city", "città", "citta"}:
            self._tile["locations"].append((self._location_priority, value))
        self._location_parts = []
        self._location_priority = 0

    def _finish_tile(self):
        if self._tile is None:
            return
        title = base.clean_text(" ".join(self._tile.get("title_parts") or []))
        candidates = []
        seen = set()
        for priority, value in self._tile.get("locations") or []:
            v = base.clean_text(value)
            if not v:
                continue
            key = v.casefold()
            if key in seen:
                continue
            seen.add(key)
            candidates.append((priority, v))
        # Prefer explicit *-section-city-value / *-section-location-value fields;
        # otherwise use the shortest generic section-field.location value.
        location = None
        if candidates:
            best_priority = max(p for p, _ in candidates)
            location = min((v for p, v in candidates if p == best_priority), key=len)
        raw_url = base.clean_text(self._tile.get("url"))
        source_id = base.clean_text(self._tile.get("source_id"))
        if raw_url and title:
            self.tile_jobs.append(
                {
                    "url": raw_url,
                    "source_id": source_id,
                    "title": title,
                    "location": location,
                    "published_at": None,
                }
            )
        self._tile = None
        self._tile_depth = 0
        self._title_depth = 0
        self._location_depth = 0
        self._location_parts = []
        self._location_priority = 0

    def handle_starttag(self, tag, attrs):
        tag_low = tag.casefold()
        a = self._attrs(attrs)
        classes = self._classes(a.get("class"))

        if self._tile is None and tag_low == "li" and "job-tile" in classes:
            source_id = None
            for cls in classes:
                m = re.fullmatch(r"job-id-(\d+)", cls)
                if m:
                    source_id = m.group(1)
                    break
            self._tile = {
                "url": a.get("data-url"),
                "source_id": source_id,
                "title_parts": [],
                "locations": [],
            }
            self._tile_depth = 1
        elif self._tile is not None:
            self._tile_depth += 1

        if self._tile is not None:
            if self._title_depth > 0:
                self._title_depth += 1
            if self._location_depth > 0:
                self._location_depth += 1

            if tag_low == "a" and "jobtitle-link" in classes:
                if a.get("href"):
                    self._tile["url"] = a.get("href")
                self._title_depth = 1

            element_id = str(a.get("id") or "").casefold()
            explicit_location = bool(
                re.search(r"-section-(?:city|location)-value$", element_id)
            )
            generic_location = "section-field" in classes and "location" in classes
            if self._location_depth == 0 and (explicit_location or generic_location):
                self._location_depth = 1
                self._location_parts = []
                self._location_priority = 2 if explicit_location else 1

        super().handle_starttag(tag, attrs)

    def handle_data(self, data):
        super().handle_data(data)
        if self._tile is None:
            return
        text = base.clean_text(data)
        if not text:
            return
        if self._title_depth > 0:
            self._tile["title_parts"].append(text)
        if self._location_depth > 0:
            self._location_parts.append(text)

    def handle_endtag(self, tag):
        tag_low = tag.casefold()
        super().handle_endtag(tag)
        if self._tile is None:
            return

        if self._title_depth > 0:
            self._title_depth -= 1
        if self._location_depth > 0:
            self._location_depth -= 1
            if self._location_depth == 0:
                self._finish_location()

        self._tile_depth -= 1
        if tag_low == "li" and self._tile_depth <= 0:
            self._finish_tile()


base.SFPageParser = SFTilePageParser
_orig_merge_sf_page_jobs = base.merge_sf_page_jobs


def merge_sf_page_jobs(page_url: str, parser) -> list[dict]:
    merged = {x["url"]: x for x in _orig_merge_sf_page_jobs(page_url, parser)}
    for raw in getattr(parser, "tile_jobs", []) or []:
        url = base.normalize_abs_url(page_url, raw.get("url"))
        if not url or not base.same_host(page_url, url) or "/job/" not in urlparse(url).path.casefold():
            continue
        existing = merged.get(url, {})
        merged[url] = {
            "url": url,
            "title": existing.get("title") or raw.get("title"),
            "location": existing.get("location") or raw.get("location"),
            "published_at": existing.get("published_at") or raw.get("published_at"),
        }
    return list(merged.values())


base.merge_sf_page_jobs = merge_sf_page_jobs


if __name__ == "__main__":
    raise SystemExit(base.main())
