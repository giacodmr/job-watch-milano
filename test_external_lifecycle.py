#!/usr/bin/env python3
import unittest
from unittest.mock import patch

import reconcile_external_lifecycle as mod


class EuronextInventoryTests(unittest.TestCase):
    def test_exhausts_paginated_current_inventory(self):
        page0 = '<a href="/en/about/careers/job-offers/r25984-italy-site-reliability-engineer">SRE</a><a href="?page=1">2</a>'
        page1 = '<a href="/en/about/careers/job-offers/r28906-italy-senior-index-sales">Sales</a>'
        responses = [
            (page0, "https://www.euronext.com/en/about/careers/open-positions?page=0"),
            (page1, "https://www.euronext.com/en/about/careers/open-positions?page=1"),
        ]
        # Production guard expects a non-trivial inventory. Add deterministic
        # synthetic IDs while still exercising page discovery and normalization.
        page0 += ''.join(f'<a href="/en/about/careers/job-offers/r30{i:03d}-role">R</a>' for i in range(20))
        responses[0] = (page0, responses[0][1])
        with patch.object(mod, "get_html", side_effect=responses):
            ids, pages = mod.official_euronext_inventory("https://www.euronext.com/en/about/careers/open-positions")
        self.assertIn("R25984", ids)
        self.assertIn("R28906", ids)
        self.assertEqual(pages, 2)

    def test_zero_parseable_ids_fails_closed(self):
        with patch.object(
            mod,
            "get_html",
            return_value=("<html>No current jobs</html>", "https://www.euronext.com/en/about/careers/open-positions?page=0"),
        ):
            with self.assertRaises(RuntimeError):
                mod.official_euronext_inventory("https://www.euronext.com/en/about/careers/open-positions")


class LifecycleUpsertTests(unittest.TestCase):
    def setUp(self):
        self.registry = {
            "company": "Euronext",
            "source_id": "R27644",
            "title": "Business Operations Analyst",
            "location": "Milan",
            "canonical_url": "https://hrhub.wd3.myworkdayjobs.com/Euronext_Career_Page/job/Milan/Business-Operations-Analyst_R27644",
        }

    def test_absent_role_can_be_persisted_closed(self):
        company = {"company": "Euronext", "jobs": [], "target_jobs_count": 0}
        self.assertTrue(mod.upsert_lifecycle(company, self.registry, "CLOSED", "https://www.euronext.com/en/about/careers/open-positions", 4))
        self.assertEqual(company["jobs"][0]["status"], "CLOSED")
        self.assertEqual(company["target_jobs_count"], 0)

    def test_external_closed_does_not_override_collector_open(self):
        company = {
            "company": "Euronext",
            "jobs": [{"source_id": "R27644", "status": "STILL_OPEN", "fingerprint": "x"}],
            "target_jobs_count": 1,
        }
        self.assertFalse(mod.upsert_lifecycle(company, self.registry, "CLOSED", "https://www.euronext.com/en/about/careers/open-positions", 4))
        self.assertEqual(company["jobs"][0]["status"], "STILL_OPEN")


if __name__ == "__main__":
    unittest.main()
