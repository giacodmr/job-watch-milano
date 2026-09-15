from pathlib import Path

path = Path("collector.py")
text = path.read_text(encoding="utf-8")
marker = "# === JOB WATCH V1.5 SUCCESSFACTORS UNFILTERED SEARCH HELPER ==="
if marker in text:
    raise SystemExit("SuccessFactors unfiltered-search helper already present")
needle = '\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
if needle not in text:
    raise SystemExit("collector.py final main guard not found")
block = r'''
# === JOB WATCH V1.5 SUCCESSFACTORS UNFILTERED SEARCH HELPER ===
def is_unfiltered_search_url(url: str) -> bool:
    """Accept only a demonstrably unfiltered inventory/search URL.

    Empty keyword plus sort controls are benign. A non-zero startrow, a
    non-empty keyword, or any other facet/filter parameter is not suitable as
    the starting point for an exhaustive inventory proof.
    """
    p = urlparse(url)
    params = parse_qs(p.query, keep_blank_values=True)
    allowed = {"q", "startrow", "sortcolumn", "sortdirection"}
    for key, values in params.items():
        k = key.casefold()
        if k not in allowed:
            return False
        cleaned = [clean_text(v) or "" for v in values]
        if k == "q" and any(cleaned):
            return False
        if k == "startrow" and any(v not in ("", "0") for v in cleaned):
            return False
    return True
'''
text = text.replace(needle, "\n" + block.strip() + "\n" + needle)
path.write_text(text, encoding="utf-8")
print("Applied conservative unfiltered-search helper")
