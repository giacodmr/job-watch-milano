"""Cheap company/location policy, before detail fetch or semantic work."""
from functools import lru_cache
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parent

def geographies(location):
    value = str(location or '').casefold()
    segments = re.split(r'\s*[|;]\s*', value)
    if len(segments)>1:
        return set().union(*(geographies(segment) for segment in segments))
    cities = set()
    if re.search(r'\b(?:milan|milano)\b', value) and not re.search(r'\bmilan\s*,\s*(?:tn|mi|oh|[a-z]{2}\s*,\s*(?:us|usa|united states))\b', value):
        cities.add('Milan')
    if re.search(r'\b(?:rome|roma)\b', value) and not re.search(r'\brome\s*,\s*(?:ga|ny|[a-z]{2}\s*,\s*(?:us|usa|united states))\b', value):
        cities.add('Rome')
    # Exclude known foreign homonyms before recognizing the UK city.
    foreign = re.search(r'\b(?:east london\b.*(?:south africa|zaf)|london\s*,\s*(?:ky|kentucky|on|ontario|oh|ohio|ar|arkansas|tx|texas|ca|california|tn|tennessee|wv|west virginia)|london\b.*(?:canada|south africa|united states|usa))\b', value)
    if re.search(r'\blondon\b', value) and not foreign:
        cities.add('London')
    if re.search(r'\b(?:luxembourg|luxemburg|luxembourg city)\b', value):
        cities.add('Luxembourg')
    return cities

@lru_cache(maxsize=16)
def _companies(path, stamp):
    return {name.casefold(): set(r.get('allowed_locations', []))
            for r in json.loads(Path(path).read_text()).get('companies', [])
            for name in [r['company'], *r.get('aliases', [])]}

def allowed(company, location, root=None):
    cities = geographies(location)
    if cities & {'Milan', 'Rome'}:
        return True  # Preserve the existing Italian search scope.
    path = (root or ROOT) / 'companies_job_watch_v2.json'
    permissions = _companies(str(path), path.stat().st_mtime_ns) if path.exists() else {}
    return bool(cities & permissions.get(str(company or '').casefold(), set()))
