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
        overlay = expansion.load_overlay(ROOT)
        for batch in expansion.BATCHES:
            for row in overlay["batches"][batch]:
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


if __name__ == "__main__":
    unittest.main()
