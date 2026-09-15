from pathlib import Path

path = Path("collector.py")
text = path.read_text(encoding="utf-8")
old = '''def collect_successfactors(company):
    last_error = None
    for attempt in range(2):
        try:
            return _collect_successfactors_paged_strict(company)
        except NotCheckable as paged_error:
            last_error = paged_error
            message = str(paged_error).casefold()
            if any(token in message for token in ("inventory not exhaustible", "pagination repeated a page")):
                try:
                    return _collect_successfactors_tile_strict(company)
                except NotCheckable as tile_error:
                    last_error = tile_error
                    tmsg = str(tile_error).casefold()
                    retryable = any(token in tmsg for token in ("total changed", "reconciliation", "stopped early", "repeated a page"))
                    if retryable and attempt == 0:
                        continue
                    raise
            retryable = any(token in message for token in ("total changed", "reconciliation", "repeated a page"))
            if retryable and attempt == 0:
                continue
            raise
    raise NotCheckable(f"SuccessFactors inventory remained unstable after retry: {last_error}")
'''
new = '''def collect_successfactors(company):
    last_error = None
    for attempt in range(2):
        try:
            return _collect_successfactors_paged_strict(company)
        except NotCheckable as paged_error:
            last_error = paged_error
            message = str(paged_error).casefold()
            paged_retryable = any(
                token in message
                for token in (
                    "total changed",
                    "reconciliation",
                    "repeated a page",
                    "inventory not exhaustible",
                )
            )
            if any(token in message for token in ("inventory not exhaustible", "pagination repeated a page")):
                try:
                    return _collect_successfactors_tile_strict(company)
                except NotCheckable as tile_error:
                    last_error = tile_error
                    tmsg = str(tile_error).casefold()
                    tile_retryable = any(
                        token in tmsg
                        for token in ("total changed", "reconciliation", "stopped early", "repeated a page")
                    )
                    # If the normal paginated inventory was provably structured but
                    # one enumeration attempt stalled, retry that primary method once
                    # even when this portal has no tile fallback. This keeps transient
                    # page/range instability as NOT_CHECKED rather than a false failure.
                    if attempt == 0 and (paged_retryable or tile_retryable):
                        continue
                    raise
            if paged_retryable and attempt == 0:
                continue
            raise
    raise NotCheckable(f"SuccessFactors inventory remained unstable after retry: {last_error}")
'''
if old not in text:
    raise SystemExit("collect_successfactors v1.5 block not found exactly")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Applied SuccessFactors primary-pagination retry hardening")
