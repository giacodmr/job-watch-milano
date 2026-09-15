from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
COLLECTOR = ROOT / 'collector.py'
text = COLLECTOR.read_text(encoding='utf-8')

# Generic support for the second public Avature result-card theme observed at Bain:
# location is an explicit subtitle element rather than list-item-location.
repls = [
    (
        '        self._capture_ref = False\n        self._ref_tag = None\n        self._ref_parts = []\n',
        '        self._capture_ref = False\n        self._ref_tag = None\n        self._ref_parts = []\n        self._capture_subtitle = False\n        self._subtitle_tag = None\n        self._subtitle_parts = []\n',
    ),
    (
        '            self._card = {"text": [], "anchors": [], "location": None, "posted": None, "ref": None}\n',
        '            self._card = {"text": [], "anchors": [], "location": None, "posted": None, "ref": None, "subtitle": None}\n',
    ),
    (
        '            if "list-item-ref" in classes:\n                self._capture_ref = True\n                self._ref_tag = tag\n                self._ref_parts = []\n',
        '            if "list-item-ref" in classes:\n                self._capture_ref = True\n                self._ref_tag = tag\n                self._ref_parts = []\n            if "article__header__text__subtitle" in classes:\n                self._capture_subtitle = True\n                self._subtitle_tag = tag\n                self._subtitle_parts = []\n',
    ),
    (
        '        if self._capture_ref:\n            self._ref_parts.append(data)\n',
        '        if self._capture_ref:\n            self._ref_parts.append(data)\n        if self._capture_subtitle:\n            self._subtitle_parts.append(data)\n',
    ),
    (
        '        if self._capture_ref and tag == self._ref_tag:\n            self._card["ref"] = " ".join(" ".join(self._ref_parts).split()) or None\n            self._capture_ref = False\n            self._ref_tag = None\n            self._ref_parts = []\n',
        '        if self._capture_ref and tag == self._ref_tag:\n            self._card["ref"] = " ".join(" ".join(self._ref_parts).split()) or None\n            self._capture_ref = False\n            self._ref_tag = None\n            self._ref_parts = []\n        if self._capture_subtitle and tag == self._subtitle_tag:\n            self._card["subtitle"] = " ".join(" ".join(self._subtitle_parts).split()) or None\n            self._capture_subtitle = False\n            self._subtitle_tag = None\n            self._subtitle_parts = []\n',
    ),
    (
        '    location = clean_text(card.get("location"))\n    posted = clean_text(card.get("posted"))\n',
        '    location = clean_text(card.get("location")) or clean_text(card.get("subtitle"))\n    posted = clean_text(card.get("posted"))\n',
    ),
]
for old, new in repls:
    if old not in text:
        raise SystemExit('expected collector fragment missing: ' + old[:100])
    text = text.replace(old, new, 1)
COLLECTOR.write_text(text, encoding='utf-8')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def find_company(data, name):
    rows = [x for x in data.get('companies', []) if x.get('company') == name]
    if len(rows) != 1:
        raise SystemExit(f'{name}: expected exactly one mapping, got {len(rows)}')
    return rows[0]


def recompute(data):
    levels = {'FULL': 0, 'STRONG': 0, 'PARTIAL': 0, 'OPAQUE': 0}
    for row in data.get('companies', []):
        level = ((row.get('verification') or {}).get('level'))
        if level in levels:
            levels[level] += 1
    summary = data.setdefault('summary', {})
    summary['companies_analyzed'] = len(data.get('companies', []))
    summary.update(levels)

# Bain: global inventory is exactly enumerable, but two of 281 live result cards
# have no public structured location and their detail pages expose no location field.
# Therefore company-level Job Watch completeness cannot be certified.
p = ROOT / 'ats_mapping_jw2.json'
data = load(p)
row = find_company(data, 'Bain & Company')
ats = row.setdefault('ats', {})
ats['inventory_url'] = 'https://careers.bain.com/jobs/SearchJobs'
v = row.setdefault('verification', {})
v.update({
    'level': 'STRONG',
    'method': 'official_avature_exact_inventory_location_incomplete',
    'location_filter_supported': True,
    'total_count_available': True,
    'full_inventory_possible': False,
    'pagination': 'Server-rendered SearchJobs inventory; tenant-fixed page size 10; zero-based folderOffset; numeric stable FolderDetail ID.',
})
row['job_watch_method'] = {
    'primary': 'Use the official Bain Avature SearchJobs inventory for discovery; do not claim VERIFIED while any enumerated requisition lacks structured public location metadata.',
    'fallback': 'Keep NOT_CHECKED until every public requisition has a structurally determinable location or an exact target-location facet can itself be reconciled.'
}
row['limitations'] = [
    'Validated from GitHub Actions on 2026-09-15: 281 declared results, 281 result cards, 281 unique stable FolderDetail IDs across 29 contiguous pages, with stable total and first page on reread.',
    '279 of 281 cards exposed location in the explicit article__header__text__subtitle field.',
    'Requisitions 102466 and 100635 exposed no location in the result card; their public detail pages exposed Job Title, Job ID, Work Areas and Employment Type but no structured location field.',
    'Because target locations cannot be determined structurally for the complete inventory, company coverage remains NOT_CHECKED despite exact global enumeration.'
]
row['last_mapped'] = '2026-09-15'
recompute(data)
save(p, data)

print('Conservative Bain evidence and generic subtitle support applied')
