"""Freshness and recovery guards for the Rome Job Watch workday.

The Collector and Worker deliberately answer different questions:
- ``worker_snapshot_ready`` checks whether persisted snapshots are fresh and
  internally coherent enough to analyse jobs that were actually collected.
- ``recovery_needed`` additionally asks whether the Collector should retry
  recoverable coverage gaps.

Coverage warnings must never become a global Worker deadlock.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROME = ZoneInfo('Europe/Rome')
BATCHES = ('jw1', 'jw2', 'jw3', 'jw4')
AMAZON_CITIES = ('Milan', 'Rome', 'London', 'Luxembourg')


def workday(stamp):
    value = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Collection timestamp requires timezone')
    local = value.astimezone(ROME)
    return local.date() + timedelta(days=local.hour >= 23)


def _load(root, name):
    import json
    try:
        return json.loads((root / name).read_text())
    except (ValueError, OSError):
        return {}


def _same_workday(stamp, expected):
    try:
        return workday(stamp) == expected
    except (AttributeError, TypeError, ValueError):
        return False


def worker_snapshot_ready(root, at):
    """Return True when the Worker may safely analyse available inventory.

    Coverage quality is deliberately not part of this gate. PARTIAL, FAILED or
    NOT_CHECKED sources remain visible in health and may cause Collector recovery,
    but do not invalidate jobs successfully collected from other sources.
    """
    expected = workday(at)
    snapshots = {}
    for batch in BATCHES:
        data = _load(root, f'current_jobs_{batch}.json')
        stamp = data.get('generated_at')
        if not _same_workday(stamp, expected):
            return False
        snapshots[batch.upper()] = stamp

    state = _load(root, 'job_watch_run_state.json')
    if state.get('source_generated_at') != snapshots:
        return False

    amazon = _load(root, 'amazon_target_check.json')
    stamp = amazon.get('checked_at')
    if not _same_workday(stamp, expected):
        return False
    return (state.get('priority_snapshot_at') or {}).get('Amazon') == stamp


def recovery_needed(root, at):
    """Return True when the Collector should retry the current Rome workday.

    Persistent PARTIAL coverage is maintenance debt and is non-blocking. FAILED
    and NOT_CHECKED sources are retried by Collector fallbacks, as is incomplete
    Amazon priority coverage. These coverage states do not block a Worker once
    ``worker_snapshot_ready`` is true.
    """
    if not worker_snapshot_ready(root, at):
        return True

    for batch in BATCHES:
        summary = (_load(root, f'current_jobs_{batch}.json').get('summary') or {})
        if any(int(summary.get(field, 0)) for field in ('FAILED', 'NOT_CHECKED')):
            return True

    amazon = _load(root, 'amazon_target_check.json')
    locations = amazon.get('locations') or {}
    return any(
        (locations.get(city) or {}).get('coverage') != 'VERIFIED'
        for city in AMAZON_CITIES
    )
