#!/usr/bin/env python3
from __future__ import annotations

import html as htmlmod
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import collector

ROOT = Path(__file__).resolve().parent
TARGETS = {
    "Intesa Sanpaolo", "Worldline", "Swiss Re", "Capgemini Invent", "Mundys",
    "E.ON Italia", "Italgas", "Bolton Group", "Boehringer Ingelheim",
}


def load_targets():
    out = []
    for batch in ("jw1", "jw2", "jw3", "jw4"):
        data = json.loads((ROOT / f"ats_mapping_{batch}.json").read_text(encoding="utf-8"))
        for company in data.get("companies", []):
            if company.get("company") in TARGETS:
                out.append(company)
    return out


def fetch(url):
    text, final = collector.sf_get_html(url)
    p = collector.SFPageParser()
    p.feed(text)
    return text, final, p


def same_host_search_candidates(base, text, parser):
    out = []
    for a in parser.anchors:
        href = a.get("href")
        if not href:
            continue
        u = urljoin(base, href.strip())
        if collector.same_host(base, u) and "/search" in urlparse(u).path.casefold():
            out.append(u)
    for action in re.findall(r"<form[^>]+action=[\"']([^\"']+)", text, re.I):
        u = urljoin(base, htmlmod.unescape(action).strip())
        if collector.same_host(base, u) and "/search" in urlparse(u).path.casefold():
            out.append(u)
    if re.search(r"[\"']/search/?(?:[?#\"'])", text, re.I):
        out.append(urljoin(base, "/search/"))
    return list(dict.fromkeys(out))[:5]


def path_offsets(base, parser):
    current = urlparse(base)
    rows = []
    for a in parser.anchors:
        href = a.get("href")
        if not href:
            continue
        u = urljoin(base, href.strip())
        p = urlparse(u)
        if p.netloc.casefold() != current.netloc.casefold():
            continue
        m = re.search(r"(/go/.*?/\d+/)(\d+)/?$", p.path, re.I)
        if m:
            rows.append((int(m.group(2)), u, a.get("title") or a.get("text")))
    rows.sort(key=lambda x: x[0])
    return rows[:12]


def count_phrases(text, visible):
    pool = visible + " " + re.sub(r"<[^>]+>", " ", text)
    patterns = [
        r"\bShowing\s+\d+\s+to\s+\d+\s+of\s+[\d., ]+\s+Jobs?\b",
        r"\b[\d.,]+\s+Jobs?\b",
        r"\b[\d.,]+\s+(?:posizioni|risultati|offerte)\b",
        r"\b(?:Jobs?|Posizioni|Risultati|Offerte)\s*[:(]?\s*[\d.,]+\b",
    ]
    hits = []
    for pat in patterns:
        for m in re.finditer(pat, pool, re.I):
            value = re.sub(r"\s+", " ", m.group(0)).strip()
            if value not in hits:
                hits.append(value)
            if len(hits) >= 10:
                return hits
    return hits


def job_contexts(base, text, parser):
    contexts = []
    seen = set()
    for a in parser.anchors:
        href = a.get("href")
        if not href:
            continue
        u = urljoin(base, href.strip())
        if "/job/" not in urlparse(u).path.casefold() or u in seen:
            continue
        seen.add(u)
        title = collector.clean_text(a.get("text")) or collector.clean_text(a.get("title"))
        pos = text.find(href)
        if pos < 0:
            pos = text.find(htmlmod.escape(href, quote=True))
        snippet = None
        if pos >= 0:
            window = text[max(0, pos - 1200): pos + 2200]
            window = htmlmod.unescape(window)
            window = re.sub(r"<script\b.*?</script>", " ", window, flags=re.I | re.S)
            window = re.sub(r"<style\b.*?</style>", " ", window, flags=re.I | re.S)
            window = re.sub(r"<[^>]+>", " | ", window)
            window = re.sub(r"\s+", " ", window).strip()
            snippet = window[:1000]
        contexts.append({"url": u, "title": title, "context": snippet})
        if len(contexts) >= 3:
            break
    return contexts


def inspect(company):
    name = company.get("company")
    inv = collector.clean_text((company.get("ats") or {}).get("inventory_url"))
    result = {"company": name, "inventory": inv}
    try:
        text, final, parser = fetch(inv)
        result["initial"] = {
            "url": final,
            "total": collector.parse_sf_total(parser.visible_text),
            "jobs": len(collector.sf_job_anchors(final, parser)),
            "search_candidates": same_host_search_candidates(final, text, parser),
            "path_offsets": path_offsets(final, parser),
            "count_phrases": count_phrases(text, parser.visible_text),
        }

        active_text, active_url, active_parser = text, final, parser
        candidates = result["initial"]["search_candidates"]
        if candidates and (result["initial"]["jobs"] == 0 or result["initial"]["total"] is None):
            candidate = candidates[0]
            try:
                active_text, active_url, active_parser = fetch(candidate)
            except Exception as e:
                result["search_error"] = f"{type(e).__name__}: {e}"

        result["active"] = {
            "url": active_url,
            "total": collector.parse_sf_total(active_parser.visible_text),
            "jobs": len(collector.sf_job_anchors(active_url, active_parser)),
            "rows": len(collector.parse_sf_rows(active_url, active_parser)),
            "next": collector.find_sf_next_url(active_url, active_parser, {active_url}),
            "path_offsets": path_offsets(active_url, active_parser),
            "count_phrases": count_phrases(active_text, active_parser.visible_text),
            "contexts": job_contexts(active_url, active_text, active_parser),
        }
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def main():
    for company in load_targets():
        print(json.dumps(inspect(company), ensure_ascii=False))


if __name__ == "__main__":
    main()
