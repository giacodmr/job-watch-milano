"""The 23:00 Rome collection supplies the following Worker/Daily workday."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROME = ZoneInfo('Europe/Rome')


def workday(stamp):
    value = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Collection timestamp requires timezone')
    local = value.astimezone(ROME)
    return local.date() + timedelta(days=local.hour >= 23)


def recovery_needed(root, at):
    import json
    def load(name):
        try:
            return json.loads((root/name).read_text())
        except (ValueError, OSError):
            return {}
    expected = workday(at)
    snapshots = {}
    for batch in ('jw1','jw2','jw3','jw4'):
        data = load(f'current_jobs_{batch}.json')
        stamp = data.get('generated_at')
        try:
            if workday(stamp) != expected:
                return True
        except (AttributeError, TypeError, ValueError):
            return True
        summary = data.get('summary') or {}
        if any(int(summary.get(field,0)) for field in ('FAILED','NOT_CHECKED','PARTIAL')):
            return True
        snapshots[batch.upper()] = stamp
    state = load('job_watch_run_state.json')
    if state.get('source_generated_at') != snapshots:
        return True
    amazon = load('amazon_target_check.json')
    stamp = amazon.get('checked_at')
    try:
        if workday(stamp) != expected:
            return True
    except (AttributeError, TypeError, ValueError):
        return True
    locations = amazon.get('locations') or {}
    if any((locations.get(city) or {}).get('coverage') != 'VERIFIED' for city in ('Milan','Rome','London','Luxembourg')):
        return True
    return (state.get('priority_snapshot_at') or {}).get('Amazon') != stamp
