#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re

import collector

URLS = {
    "Italgas": "https://carriere.italgas.it/search/?createNewAlert=false&q=&optionsFacetsDD_customfield2=&optionsFacetsDD_customfield1=&locationsearch=",
    "Bolton": "https://jobs.boltongroup.net/search/",
    "Boehringer": "https://jobs.boehringer-ingelheim.com/search/",
}

PATTERNS = (
    r".{0,220}startrow.{0,260}",
    r".{0,220}pagination.{0,260}",
    r".{0,220}data-(?:page|offset|start|url)[^>]{0,220}",
    r".{0,220}(?:page|offset)\s*[=:]\s*[\"']?\d+.{0,220}",
    r".{0,220}aria-label=[\"'][^\"']*(?:next|successiv|avanti|page|pagina)[^\"']*[\"'].{0,220}",
)


def main():
    for name, url in URLS.items():
        try:
            text, final = collector.sf_get_html(url)
            clean = html.unescape(text).replace("\n", " ").replace("\r", " ")
            snippets = []
            for pat in PATTERNS:
                for m in re.finditer(pat, clean, re.I | re.S):
                    s = re.sub(r"\s+", " ", m.group(0)).strip()
                    if s not in snippets:
                        snippets.append(s[:700])
                    if len(snippets) >= 25:
                        break
                if len(snippets) >= 25:
                    break
            hrefs = []
            for href in re.findall(r"href=[\"']([^\"']+)[\"']", clean, re.I):
                low = href.casefold()
                if any(x in low for x in ("startrow", "page=", "offset=")):
                    hrefs.append(href)
            print(json.dumps({
                "company": name,
                "url": final,
                "hrefs": list(dict.fromkeys(hrefs))[:30],
                "snippets": snippets,
            }, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"company": name, "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
