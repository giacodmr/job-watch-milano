import json
import unittest
from pathlib import Path

import collector
import job_watch_expansion as expansion

ROOT = Path(__file__).resolve().parent


class ExpansionOverlayTests(unittest.TestCase):
    def test_overlay_is_append_only_and_batches_are_consistent(self):
        overlay = expansion.load_overlay(ROOT)
        expected = {"jw1": 3, "jw2": 5, "jw3": 3, "jw4": 3}
        for batch, count in expected.items():
            base = json.loads((ROOT / f"ats_mapping_{batch}.json").read_text(encoding="utf-8"))
            base_names = {row["company"] for row in base.get("companies", [])}
            additions = overlay["batches"][batch]
            self.assertEqual(len(additions), count)
            self.assertTrue(base_names.isdisjoint({row["company"] for row in additions}))
            merged = expansion.merged_mapping(batch, ROOT, base=base)
            self.assertEqual(
                len(merged["companies"]),
                len(base.get("companies", [])) + count,
            )
            self.assertEqual(
                merged["summary"]["companies_analyzed"],
                len(merged["companies"]),
            )

    def test_every_expansion_source_has_a_collector_path(self):
        for batch in expansion.BATCHES:
            merged = expansion.merged_mapping(batch, ROOT)
            base = json.loads((ROOT / f"ats_mapping_{batch}.json").read_text(encoding="utf-8"))
            base_names = {row["company"] for row in base.get("companies", [])}
            additions = [row for row in merged["companies"] if row["company"] not in base_names]
            for row in additions:
                fn = collector.choose(row)
                self.assertTrue(callable(fn), row["company"])

    def test_batches_manifest_contains_all_collected_expansion_companies(self):
        overlay = expansion.load_overlay(ROOT)
        manifest = json.loads((ROOT / "job_watch_batches.json").read_text(encoding="utf-8"))
        for batch in expansion.BATCHES:
            active = set(manifest["batches"][batch.upper()]["companies"])
            expected = {row["company"] for row in overlay["batches"][batch]}
            self.assertTrue(expected.issubset(active), (batch, sorted(expected - active)))

    def test_telespazio_is_group_covered_not_double_collected(self):
        overlay = expansion.load_overlay(ROOT)
        aliases = {row["company"]: row for row in overlay.get("coverage_aliases", [])}
        self.assertEqual(aliases["Telespazio"]["covered_by"], "Leonardo")
        self.assertEqual(aliases["Telespazio"]["batch"], "jw3")
        expansion_names = {
            row["company"]
            for batch in expansion.BATCHES
            for row in overlay["batches"][batch]
        }
        self.assertNotIn("Telespazio", expansion_names)
        manifest = json.loads((ROOT / "job_watch_batches.json").read_text(encoding="utf-8"))
        self.assertIn("Leonardo", manifest["batches"]["JW3"]["companies"])
        self.assertNotIn("Telespazio", manifest["batches"]["JW3"]["companies"])

    def test_opella_live_cxs_block_is_downgraded_to_partial_probe(self):
        merged = expansion.merged_mapping("jw4", ROOT)
        opella = next(row for row in merged["companies"] if row["company"] == "Opella")
        self.assertEqual(opella["verification"]["level"], "PARTIAL")
        self.assertFalse(opella["verification"]["full_inventory_possible"])
        self.assertEqual(opella["ats"]["inventory_url"], "https://www.opella.com/en/careers")
        self.assertEqual(collector.choose(opella).__name__, "probe_official_inventory")

    def test_south_african_east_london_is_not_uk_london(self):
        matcher = expansion._expanded_location_matcher(lambda location, company_name=None: True)
        self.assertFalse(matcher("ZAF - East London"))
        self.assertFalse(matcher("East London, South Africa"))
        self.assertTrue(matcher("London, England"))
        self.assertTrue(matcher("Milan, Italy"))

    def test_enrichment_reader_sees_overlay_mappings(self):
        base = json.loads((ROOT / "ats_mapping_jw2.json").read_text(encoding="utf-8"))

        def original(name, default=None):
            if Path(name).name == "ats_mapping_jw2.json":
                return base
            return default

        reader = expansion._patched_enrichment_reader(original, ROOT)
        merged = reader("ats_mapping_jw2.json", {})
        by_company = {row["company"]: row for row in merged["companies"]}
        self.assertEqual(by_company["Experian"]["ats"]["tenant"], "Experian")
        self.assertEqual(by_company["Contentsquare"]["ats"]["tenant"], "contentsquare")

    def test_mapping_bug_failures_bypass_old_enrichment_cooldown_once(self):
        payload = {
            "records": {
                "Experian::1": {
                    "status": "FAILED",
                    "company": "Experian",
                    "error": "HTTP 400",
                },
                "Contentsquare::2": {
                    "status": "FAILED",
                    "company": "Contentsquare",
                    "error": "no Lever tenant",
                },
                "Other::3": {
                    "status": "FAILED",
                    "company": "Other",
                    "error": "HTTP 400",
                },
            }
        }

        def original(name, default=None):
            return payload if Path(name).name == "semantic_jd_cache_jw2.json" else default

        reader = expansion._patched_enrichment_reader(original, ROOT)
        cleaned = reader("semantic_jd_cache_jw2.json", {})
        self.assertNotIn("Experian::1", cleaned["records"])
        self.assertNotIn("Contentsquare::2", cleaned["records"])
        self.assertIn("Other::3", cleaned["records"])
        self.assertIn("Experian::1", payload["records"])


if __name__ == "__main__":
    unittest.main()
