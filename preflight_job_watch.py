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
    required_scripts = ('job_watch.py','pipeline_state.py','collector.py','reconcile_workday_target_paths.py','amazon_target_check.py','sync_analysis_state.py','harden_job_watch_state.py','daily_worklist.py','enrich_semantic_jds.py','audit_job_watch.py','certify_job_watch.py','validate_job_watch_state.py','validate_job_watch_inputs.py','preflight_job_watch.py','test_daily_pipeline.py','test_job_watch_guardrails.py','test_workday_path_reconciliation.py','test_pipeline_resilience.py')
    for name in required_scripts:
        if not (root/name).is_file(): errors.append(f'Pipeline contract: missing entrypoint {name}')
    for path in root.glob('*.py'):
        try: ast.parse(path.read_text())
        except SyntaxError as exc: errors.append(f'{path.name}: syntax error {exc}')
    from pipeline_state import STATES, PRIORITY_STATES, COVERAGE_STATES, ERROR_SCOPES
    declared = data.get('pipeline_contract.json',{})
    if declared:
        for name,allowed in [('states',STATES),('priority_states',PRIORITY_STATES),('coverage_states',COVERAGE_STATES),('error_categories',set(ERROR_SCOPES))]:
            if set(declared.get(name,[])) != set(allowed): errors.append(f'pipeline_contract.json: invalid {name}')
    controller = root/'job_watch.py'
    if controller.exists():
        for node in ast.walk(ast.parse(controller.read_text())):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='invoke' and node.args and isinstance(node.args[0],ast.Constant):
                module = node.args[0].value
                if isinstance(module,str) and not (root/(module+'.py')).is_file(): errors.append(f'job_watch.py: missing stage module {module}')
    for path in entrypoints:
        content = path.read_text()
        for selectors in re.findall(r'python(?:3)?\s+-m\s+unittest\s+([^\n]+)',content):
            for selector in selectors.split():
                selector = selector.strip("\"'")
                if selector.startswith('-') or selector in {'discover'}: continue
                module = selector.removesuffix('.py').split('.')[0]
                if re.fullmatch(r'test_[\w]+',module) and not (root/(module+'.py')).is_file():
                    errors.append(f'{path.name}: missing test {module}')
        # Status literals in workflow Python snippets obey the shared contract.
        for value in re.findall(r"(?:coverage|status|run_phase)[\"']?\s*(?:==|!=|:|=)\s*[\"']([A-Z_]+)[\"']",content):
            if value not in STATES|PRIORITY_STATES|COVERAGE_STATES|{'NEW','STILL_OPEN','UPDATED','CLOSED','UNKNOWN','OK'}:
                errors.append(f'{path.name}: invalid status {value}')
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
                 'user_job_decisions.json', 'watchlist_additions.json', 'discovery_candidates.json','pipeline_contract.json'):
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
            if stem == 'current_jobs':
                for company in item.get('companies',[]):
                    if company.get('coverage') not in COVERAGE_STATES: errors.append(f'{name}: invalid coverage {company.get("coverage")}')
                    for job in company.get('jobs',[]):
                        if job.get('status') not in {'NEW','STILL_OPEN','UPDATED','CLOSED','UNKNOWN'}: errors.append(f'{name}: invalid vacancy status {job.get("status")}')
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
