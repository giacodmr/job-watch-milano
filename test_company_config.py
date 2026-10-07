"""Permanent invariants for the simplified employer/configuration architecture."""
import json
from pathlib import Path
import unittest

import collector

ROOT = Path(__file__).resolve().parent
BATCHES = ("jw1", "jw2", "jw3", "jw4")


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


class CompanyConfiguration(unittest.TestCase):
    def test_active_registry_routing_and_ats_mapping_are_identical(self):
        registry = {
            row["company"]
            for row in load("companies_job_watch_v2.json")["companies"]
        }
        batches = load("job_watch_batches.json")["batches"]
        routed = set()
        for batch in BATCHES:
            members = batches[batch.upper()]["companies"]
            self.assertEqual(len(members), len(set(members)), batch)
            routed.update(members)
            mapped = [
                row["company"]
                for row in load(f"ats_mapping_{batch}.json")["companies"]
            ]
            self.assertEqual(len(mapped), len(set(mapped)), batch)
            self.assertEqual(set(mapped), set(members), batch)
        self.assertEqual(registry, routed)

    def test_candidates_are_not_claimed_as_active(self):
        active = {
            row["company"]
            for row in load("companies_job_watch_v2.json")["companies"]
        }
        candidates = set(load("company_candidates.json")["records"])
        self.assertFalse(active & candidates)

    def test_historical_operational_layers_do_not_return(self):
        for name in (
            "watchlist_additions.json",
            "discovery_candidates.json",
            "extra_company_watchlist_expansion_20261004.json",
            "ats_mapping_expansion_20261004.json",
            "job_watch_expansion.py",
        ):
            self.assertFalse((ROOT / name).exists(), name)

    def test_group_alias_and_runtime_fixes_are_canonical(self):
        alias = load("job_watch_batches.json")["coverage_aliases"]["Telespazio"]
        self.assertEqual(alias["covered_by"], "Leonardo")
        opella = next(
            row
            for row in load("ats_mapping_jw4.json")["companies"]
            if row["company"] == "Opella"
        )
        self.assertEqual(opella["verification"]["level"], "PARTIAL")
        self.assertIn("opella.com", opella["ats"]["career_site"])
        self.assertFalse(collector.location_matches("East London, South Africa (ZAF)"))


if __name__ == "__main__":
    unittest.main()
