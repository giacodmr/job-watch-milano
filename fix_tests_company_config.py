#!/usr/bin/env python3
from pathlib import Path


def replace_count(path, old, new, expected):
    p=Path(path);text=p.read_text(encoding='utf-8');count=text.count(old)
    if count != expected:
        raise RuntimeError(f'{path}: expected {expected} matches, found {count}')
    p.write_text(text.replace(old,new),encoding='utf-8')

# Full-pipeline fixtures now need the new global candidate staging object.
replace_count(
    'test_pipeline_resilience.py',
    "        self.put('watchlist_additions.json',{'companies':[]})\n        self.put('discovery_candidates.json',{'records':{}})\n",
    "        self.put('company_candidates.json',{'records':{},'promoted_history':{},'monitored_reviews':[]})\n",
    1,
)
replace_count(
    'test_daily_pipeline.py',
    "            put('watchlist_additions.json',{'companies':[]})\n            put('discovery_candidates.json',{'records':{}})\n",
    "            put('company_candidates.json',{'records':{},'promoted_history':{},'monitored_reviews':[]})\n",
    1,
)

# The production worklist deliberately advances to the next historical tranche
# once every role in the previous assignment has a valid decision. Test that
# contract instead of the obsolete expectation that the worklist becomes empty.
replace_count(
    'test_daily_pipeline.py',
    "        self.assertEqual(daily_worklist.build_worklist()['records'],[])\n\n    def test_lifecycle_notice_is_not_repeated_after_reporting(self):",
    "        next_work=daily_worklist.build_worklist();self.assertEqual(len(next_work['records']),1);self.assertEqual(next_work['records'][0]['job_key'],'Test::1');self.assertEqual(next_work['backlog_assignment'],['Test::1'])\n\n    def test_lifecycle_notice_is_not_repeated_after_reporting(self):",
    1,
)
print('Updated test fixtures for canonical company configuration.')
