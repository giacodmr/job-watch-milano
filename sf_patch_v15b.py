#!/usr/bin/env python3
from pathlib import Path

path = Path("collector.py")
text = path.read_text(encoding="utf-8")
old = '''_find_sf_search_url_v14 = find_sf_search_url

def find_sf_search_url(base: str, parser: SFPageParser) -> str | None:
    existing = _find_sf_search_url_v14(base, parser)
    if existing:
        return existing
    candidates = []
    for action in getattr(parser, "form_actions", []) or []:
        u = normalize_abs_url(base, clean_text(action))
        if not u or not same_host(base, u):
            continue
        if "/search/" in urlparse(u).path.casefold() or urlparse(u).path.casefold().endswith("/search"):
            candidates.append(u)
    if not candidates:
        return None
    candidates = list(dict.fromkeys(candidates))
    candidates.sort(key=lambda u: (0 if not urlparse(u).query else 1, len(urlparse(u).path), len(u)))
    return candidates[0]
'''
new = '''_find_sf_search_url_v14 = find_sf_search_url

def find_sf_search_url(base: str, parser: SFPageParser) -> str | None:
    # A same-host form action is stronger evidence of the actual search inventory
    # than navigation/category anchors on /viewalljobs/ landing pages.
    candidates = []
    for action in getattr(parser, "form_actions", []) or []:
        u = normalize_abs_url(base, clean_text(action))
        if not u or not same_host(base, u):
            continue
        if "/search/" in urlparse(u).path.casefold() or urlparse(u).path.casefold().endswith("/search"):
            candidates.append(u)
    if candidates:
        candidates = list(dict.fromkeys(candidates))
        candidates.sort(key=lambda u: (0 if not urlparse(u).query else 1, len(urlparse(u).path), len(u)))
        return candidates[0]
    return _find_sf_search_url_v14(base, parser)
'''
if old not in text:
    raise SystemExit("Expected v1.5 search-discovery block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Prioritized evidenced SuccessFactors form search actions")
