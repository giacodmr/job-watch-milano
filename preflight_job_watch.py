#!/usr/bin/env python3
"""Read-only preflight: broken workflow references and configuration/schema drift."""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ('jw1', 'jw2', 'jw3', 'jw4')


def validate(root=ROOT):
    errors = []
    data = {}
    for path in root.glob('*.json'):
        try:
            data[path.name] = json.loads(path.read_text())
        except (ValueError, OSError) as e:
            errors.append(f'{path.name}: invalid JSON: {e}')
    entrypoints = list(root.glob('.github/workflows/*.y*ml'))
    if (root / 'job_watch.py').is_file():
        entrypoints.append(root / 'job_watch.py')
    for path in entrypoints:
        # All script references, including compile/test commands and path triggers.
        for name in set(re.findall(r'(?<![\w/])([\w./-]+\.py)\b', path.read_text())):
            target = root / name
            if not target.is_file():
                errors.append(f'{path.name}: missing script {name}')
            else:
                try:
                    ast.parse(target.read_text())
                except SyntaxError as e:
                    errors.append(f'{name}: syntax error {e}')
    for name in ('job_watch_rules.json', 'job_watch_batches.json', 'companies_job_watch_v2.json',
                 'user_job_decisions.json', 'job_watch_run_state.json', 'watchlist_additions.json', 'discovery_candidates.json'):
        if not isinstance(data.get(name), dict):
            errors.append(f'{name}: required object missing')
    batches = data.get('job_watch_batches.json', {}).get('batches', {})
    if set(batches) != {b.upper() for b in BATCHES}:
        errors.append('job_watch_batches.json: JW1-JW4 required')
    seen = set()
    excluded = set(data.get('job_watch_rules.json', {}).get('excluded_companies', []))
    universe = {r.get('company') for name in ('companies_job_watch_v2.json', 'watchlist_additions.json') for r in data.get(name, {}).get('companies', [])}
    for b in BATCHES:
        members = batches.get(b.upper(), {}).get('companies', [])
        if not members or len(members) != len(set(members)) or seen.intersection(members):
            errors.append(f'{b}: empty or duplicate company assignments')
        seen.update(members)
        if set(members) & excluded or not set(members) <= universe:
            errors.append(f'{b}: excluded/unknown company assigned')
        for stem in ('ats_mapping', 'current_jobs', 'analysis_results', 'semantic_queue', 'semantic_decisions', 'surfaced_jobs', 'semantic_jd_cache'):
            name = f'{stem}_{b}.json'; item = data.get(name)
            if not isinstance(item, dict) or str(item.get('batch', '')).lower() != b:
                errors.append(f'{name}: required schema/batch mismatch')
                continue
            if not re.fullmatch(r'[12]\.\d+', str(item.get('version', ''))):
                errors.append(f'{name}: unsupported/missing schema version')
            field = 'companies' if stem in {'ats_mapping','current_jobs'} else 'records'
            expected = list if field == 'companies' or stem == 'semantic_queue' else dict
            if not isinstance(item.get(field), expected):
                errors.append(f'{name}: incompatible {field} schema')
            if stem == 'ats_mapping' and isinstance(item.get('companies'), list):
                mapped = [r.get('company') for r in item['companies']]
                if set(mapped) != set(members) or len(mapped) != len(set(mapped)):
                    errors.append(f'{b}: mapping does not match batch')
    if seen != universe:
        errors.append('company universe does not match batch union')
    return errors


def main():
    errors = validate()
    if errors:
        raise SystemExit('PREFLIGHT ERROR:\n' + '\n'.join(errors))
    print('Workflow references, JSON and batch schemas validated.')


if __name__ == '__main__':
    main()
