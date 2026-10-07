"""Permanent-source regression contract; no event-specific production pipeline."""
import copy
import json
import unittest
from pathlib import Path
from urllib.parse import urlparse

import collector
import job_watch_expansion as expansion
import preflight_job_watch as preflight

ROOT = Path(__file__).resolve().parent

# Independent frozen roster from the official LUISS page, checked 2026-10-06.
# Company visits are included as well as the two desk-event days.
EMPLOYERS = """Aurora Growth Capital
B4 Investimenti SGR
BancoPosta Fondi SGR
Blue Ocean Finance
BU Bregal Unternehmerkapital
Clessidra Group
COIMA
Columbus Capital
Fitex Capital
Generali Asset Management SGR
Groupe HLD
Gruppo CDP
Heritage Holdings
KYIP Capital SGR
Marktlink
Mindful Capital Partners
Obloo Ventures
Prelios
PTS
Red Fish Capital Partners
Tages Capital
Tikehau Capital
Visconti Capital
AB InBev Italia
Alfasigma
Ariston Group
Benetton Group
BMW Group Italia
BNP Paribas
Bolton Group
Cisco Italia
Deloitte
Dr.Feel
Ermenegildo Zegna Group
Esselunga
Etro
Fibercop
Giorgio Armani
Grant Thornton
Gruppo AXA Italia
Gruppo Lactalis Italia
Hitachi Rail
Hugo Boss
Intesa Sanpaolo
KIKO Milano
KPMG
Lechler
Lutech Group
MAIRE
Max Mara Fashion Group
NTT DATA
Pirelli
PwC
Snam
TikTok
The Estée Lauder Companies
The Level Group
The Westin Palace, Milan
UniCredit
Bain & Company
Boston Consulting Group (BCG)
McKinsey & Company""".splitlines()
RENAMES = {
    'Cisco Italia': 'Cisco',
    'Deloitte': 'Deloitte / Monitor Deloitte',
    'Ermenegildo Zegna Group': 'Ermenegildo Zegna',
    'Gruppo AXA Italia': 'AXA',
    'MAIRE': 'Maire',
    'PwC': 'PwC / Strategy&',
}
GROUP_ALIASES = {
    'Generali Asset Management SGR': ('Generali', 'JW1'),
    'BancoPosta Fondi SGR': ('Poste Italiane', 'JW1'),
    'The Westin Palace, Milan': ('Marriott International', 'JW4'),
}


class MilanDaysSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / 'job_watch_batches.json').read_text())
        cls.rows = [row for b in expansion.BATCHES
                    for row in expansion.merged_mapping(b, ROOT)['companies']]
        cls.by_name = {row['company']: row for row in cls.rows}
        cls.catalog = [row for filename in ('companies_job_watch_v2.json', 'watchlist_additions.json')
                       for row in json.loads((ROOT / filename).read_text())['companies']]
        cls.universe = {row['company'] for row in cls.catalog}
        cls.universe.update(row['company'] for b in expansion.BATCHES
                            for row in expansion.load_overlay(ROOT)['batches'][b])

    def canonical(self, employer):
        return GROUP_ALIASES.get(employer, (RENAMES.get(employer, employer),))[0]

    def test_entire_roster_has_one_active_canonical_source(self):
        self.assertEqual(len(EMPLOYERS), 62)
        self.assertEqual(len(set(EMPLOYERS)), 62)
        for employer in EMPLOYERS:
            name = self.canonical(employer)
            with self.subTest(employer=employer):
                self.assertIn(name, self.universe)
                self.assertIn(name, self.by_name)
                assignments = [batch for batch, row in self.manifest['batches'].items()
                               if name in row['companies']]
                self.assertEqual(assignments, [self.by_name[name]['batch'].upper()])
                self.assertEqual(sum(row['company'] == name for row in self.rows), 1)

    def test_blackrock_is_excluded_from_all_added_configuration(self):
        names = set(self.universe) | set(self.by_name)
        names.update(self.manifest.get('coverage_aliases', {}))
        names.update(self.manifest.get('company_metadata', {}))
        for batch in self.manifest['batches'].values():
            names.update(batch['companies'])
        self.assertFalse(any('blackrock' in name.casefold() for name in names))

    def test_aliases_share_only_one_parent_collector(self):
        for alias, (parent, batch) in GROUP_ALIASES.items():
            row = self.manifest['coverage_aliases'][alias]
            self.assertEqual((row['covered_by'], row['batch']), (parent, batch))
            self.assertTrue(row['reason'])
            self.assertNotIn(alias, self.universe)
            self.assertNotIn(alias, self.by_name)
            self.assertNotIn(alias, self.manifest['company_metadata'])
            self.assertIn(parent, self.manifest['batches'][batch]['companies'])
        for alias in RENAMES:
            self.assertNotIn(alias, self.by_name)
        self.assertEqual(len(self.catalog), len({r['company'] for r in self.catalog}))

    def test_every_employer_has_metadata_and_valid_dispatch_configuration(self):
        for employer in EMPLOYERS:
            name = self.canonical(employer)
            row = self.by_name[name]
            with self.subTest(company=name):
                self.assertEqual(self.manifest['company_metadata'][name]['network_advantage'], 'HIGH')
                self.assertTrue(callable(collector.choose(row)))
                for field in ('career_site', 'inventory_url'):
                    url = urlparse(row['ats'][field])
                    self.assertIn(url.scheme, ('http', 'https'))
                    self.assertTrue(url.netloc)
                    self.assertNotIn(url.netloc.casefold(), ('www.linkedin.com', 'www.indeed.com', 'www.glassdoor.com'))
                if collector.choose(row) is collector.probe_official_inventory:
                    self.assertEqual(row['verification']['level'], 'PARTIAL')
                    self.assertFalse(row['verification']['full_inventory_possible'])
                    self.assertTrue(row['limitations'])

    def test_network_metadata_does_not_affect_operational_consumers(self):
        for employer in EMPLOYERS:
            row = self.by_name[self.canonical(employer)]
            enriched = copy.deepcopy(row)
            enriched['network_advantage'] = 'HIGH'
            self.assertIs(collector.choose(row), collector.choose(enriched))
        # Metadata remains descriptive: runtime collection, filtering, ranking,
        # review and polling code never reads either manifest metadata field.
        for filename in ('collector.py', 'job_watch.py', 'job_watch_expansion.py',
                         'sync_analysis_state.py', 'harden_job_watch_state.py',
                         'daily_worklist.py', 'enrich_semantic_jds.py', 'certify_job_watch.py'):
            source = (ROOT / filename).read_text()
            self.assertNotIn('network_advantage', source, filename)
            self.assertNotIn('company_metadata', source, filename)

    def test_all_universe_mapping_batch_invariants_pass_preflight(self):
        self.assertEqual(preflight.validate(ROOT), [])
        self.assertEqual(set(self.by_name), self.universe)
        self.assertEqual(set(self.manifest['batches']), {'JW1', 'JW2', 'JW3', 'JW4'})

    def test_metadata_and_alias_guardrails_reject_invalid_configuration(self):
        excluded = {'Excluded fixture'}
        def errors(manifest):
            return preflight.validate_company_metadata(manifest, self.universe, excluded)
        self.assertEqual(errors(self.manifest), [])
        cases = [
            ('metadata unknown', lambda m: m['company_metadata'].update({'Unknown fixture': {'network_advantage': 'HIGH'}})),
            ('metadata value', lambda m: m['company_metadata']['Generali'].update(network_advantage='URGENT')),
            ('alias unknown parent', lambda m: m['coverage_aliases']['BancoPosta Fondi SGR'].update(covered_by='Unknown fixture')),
            ('alias wrong batch', lambda m: m['coverage_aliases']['BancoPosta Fondi SGR'].update(batch='JW4')),
            ('alias duplicate', lambda m: m['coverage_aliases'].update({'Generali': {'covered_by':'Poste Italiane','batch':'JW1','reason':'fixture'}})),
            ('alias exclusion', lambda m: m['coverage_aliases'].update({'Excluded fixture': {'covered_by':'Generali','batch':'JW1','reason':'fixture'}})),
        ]
        for label, mutate in cases:
            with self.subTest(case=label):
                manifest = copy.deepcopy(self.manifest)
                mutate(manifest)
                self.assertTrue(errors(manifest))
        manifest = copy.deepcopy(self.manifest)
        manifest['coverage_aliases']['Telespazio']['covered_by'] = 'Maire'
        self.assertTrue(preflight.validate_company_metadata(manifest, self.universe, excluded,
                        expansion.load_overlay(ROOT)['coverage_aliases']))


if __name__ == '__main__':
    unittest.main()
