#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import collector

ROOT = Path(__file__).resolve().parent
TARGETS = {
    "Intesa Sanpaolo", "Worldline", "Swiss Re", "EY / EY-Parthenon",
    "Capgemini Invent", "Terna", "Italgas", "E.ON Italia", "ENGIE Italia",
    "Mundys", "Pirelli", "Heineken Italia", "Moncler Group", "Bolton Group",
    "Boehringer Ingelheim",
}


def mappings():
    out = []
    for batch in ("jw1", "jw2", "jw3", "jw4"):
        data = json.loads((ROOT / f"ats_mapping_{batch}.json").read_text(encoding="utf-8"))
        for c in data.get("companies", []):
            if c.get("company") in TARGETS:
                out.append((batch.upper(), c))
    return out


def compact_anchor(a):
    return {
        "href": a.get("href"),
        "text": collector.clean_text(a.get("text")),
        "title": collector.clean_text(a.get("title")),
        "aria": collector.clean_text(a.get("aria_label")),
        "rel": collector.clean_text(a.get("rel")),
    }


def inspect(batch, company):
    name = company.get("company")
    inventory = collector.clean_text((company.get("ats") or {}).get("inventory_url"))
    result = {"batch": batch, "company": name, "inventory": inventory}
    try:
        html_text, current_url = collector.sf_get_html(inventory)
        parser = collector.SFPageParser()
        parser.feed(html_text)
        result["initial_url"] = current_url
        result["initial_total"] = collector.parse_sf_total(parser.visible_text)
        result["initial_job_anchors"] = len(collector.sf_job_anchors(current_url, parser))
        result["initial_rows"] = len(parser.rows)
        result["initial_parsed_rows"] = len(collector.parse_sf_rows(current_url, parser))
        result["is_inventory_path"] = collector.is_sf_search_path(current_url)

        if not collector.is_sf_search_path(current_url):
            discovered = collector.find_sf_search_url(current_url, parser)
            result["discovered_inventory"] = discovered
            if discovered:
                html_text, current_url = collector.sf_get_html(discovered)
                parser = collector.SFPageParser()
                parser.feed(html_text)

        result["active_url"] = current_url
        result["total"] = collector.parse_sf_total(parser.visible_text)
        jobs = collector.sf_job_anchors(current_url, parser)
        result["job_anchors"] = len(jobs)
        result["rows"] = len(parser.rows)
        result["parsed_rows"] = len(collector.parse_sf_rows(current_url, parser))
        result["next_url"] = collector.find_sf_next_url(current_url, parser, {current_url})

        interesting = []
        for a in parser.anchors:
            href = a.get("href") or ""
            text = " ".join(x for x in (a.get("text"), a.get("title"), a.get("aria_label")) if x)
            low = (href + " " + text).casefold()
            if any(k in low for k in ("startrow", "next", "successiv", "weiter", "/search", "/viewalljobs", "/go/")):
                interesting.append(compact_anchor(a))
        result["interesting_anchors"] = interesting[:25]

        startrows = sorted(set(int(x) for x in re.findall(r"startrow(?:=|%3[dD])(\d+)", html_text, re.I)))
        result["raw_startrows"] = startrows[:30]
        result["raw_job_href_count"] = len(re.findall(r"href=[\"'][^\"']*/job/", html_text, re.I))
        result["html_size"] = len(html_text)
        result["form_actions"] = re.findall(r"<form[^>]+action=[\"']([^\"']+)", html_text, re.I)[:10]
        result["pagination_tokens"] = sorted(set(re.findall(r"(?:startrow|page|offset|from)\s*[=:]\s*[\"']?(\d+)", html_text, re.I)))[:30]

        # Capture only short structural excerpts, never full page content.
        excerpts = []
        for pat in (r"Showing\s+\d+\s+to\s+\d+\s+of\s+[\d,. ]+\s+Jobs?", r"Results?\s+\d+\s*[-–—]\s*\d+\s+of\s+[\d,. ]+", r"startrow.{0,100}"):
            for m in re.finditer(pat, html_text, re.I | re.S):
                excerpts.append(re.sub(r"\s+", " ", m.group(0))[:180])
                if len(excerpts) >= 8:
                    break
            if len(excerpts) >= 8:
                break
        result["excerpts"] = excerpts
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def main():
    rows = [inspect(batch, company) for batch, company in mappings()]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
