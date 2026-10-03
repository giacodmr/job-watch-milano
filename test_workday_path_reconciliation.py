#!/usr/bin/env python3
import unittest
from unittest.mock import patch

import reconcile_workday_target_paths as mod
from reconcile_workday_target_paths import official_listing_candidate, safe_path_location, upsert_recovered


class WorkdayPathLocationTests(unittest.TestCase):
    def test_milan_exact(self):
        self.assertEqual(safe_path_location("/job/Milan/Business-Operations-Analyst_R27644"), "Milan")

    def test_milan_italy(self):
        self.assertEqual(safe_path_location("/job/Milan-Italy/Role_R1"), "Milan Italy")

    def test_london_england(self):
        self.assertEqual(safe_path_location("/job/London-England-Angel-Lane/Role_R1"), "London England Angel Lane")

    def test_reject_london_kentucky(self):
        self.assertIsNone(safe_path_location("/job/London-KY/Role_R1"))

    def test_reject_generic_country(self):
        self.assertIsNone(safe_path_location("/job/Italy/Role_R1"))


class OfficialListingFallbackTests(unittest.TestCase):
    def setUp(self):
        self.mapped = {
            "ats": {
                "inventory_url": "https://hrhub.wd3.myworkdayjobs.com/Euronext_Career_Page",
                "career_site": "https://www.euronext.com/en/about/careers",
            }
        }
        self.registry = {
            "records": {
                "Euronext::R27644": {
                    "company": "Euronext",
                    "source_id": "R27644",
                    "title": "Business Operations Analyst",
                    "location": "Milan",
                    "canonical_url": "https://hrhub.wd3.myworkdayjobs.com/Euronext_Career_Page/job/Milan/Business-Operations-Analyst_R27644",
                    "official_listing_url": "https://www.euronext.com/it/about/careers/vacancies/98",
                    "validation_method": "official_corporate_listing_contains_workday_link",
                }
            }
        }
        self.html = '''
            <h3>Business Operations Analyst</h3>
            <a href="https://hrhub.wd3.myworkdayjobs.com/Euronext_Career_Page/job/Milan/Business-Operations-Analyst_R27644/apply">Apply Now</a>
        '''

    def test_live_official_listing_builds_candidate(self):
        with patch.object(mod, "read_json", return_value=self.registry), patch.object(
            mod,
            "get_html",
            return_value=(self.html, "https://www.euronext.com/it/about/careers/vacancies/98"),
        ):
            job = official_listing_candidate("Euronext", "R27644", self.mapped)
        self.assertEqual(job["source_id"], "R27644")
        self.assertEqual(job["title"], "Business Operations Analyst")
        self.assertEqual(job["reconciliation_source"], "official_corporate_listing")
        self.assertTrue(job["fingerprint"])

    def test_missing_exact_workday_link_fails_closed(self):
        html = "<h3>Business Operations Analyst</h3>"
        with patch.object(mod, "read_json", return_value=self.registry), patch.object(
            mod,
            "get_html",
            return_value=(html, "https://www.euronext.com/it/about/careers/vacancies/98"),
        ):
            with self.assertRaises(RuntimeError):
                official_listing_candidate("Euronext", "R27644", self.mapped)

    def test_wrong_workday_host_fails_closed(self):
        bad = {
            "records": {
                "Euronext::R27644": dict(
                    self.registry["records"]["Euronext::R27644"],
                    canonical_url="https://example.com/Euronext_Career_Page/job/Milan/Business-Operations-Analyst_R27644",
                )
            }
        }
        with patch.object(mod, "read_json", return_value=bad):
            with self.assertRaises(RuntimeError):
                official_listing_candidate("Euronext", "R27644", self.mapped)

    def test_wrong_corporate_host_fails_closed(self):
        bad = {
            "records": {
                "Euronext::R27644": dict(
                    self.registry["records"]["Euronext::R27644"],
                    official_listing_url="https://example.com/jobs",
                )
            }
        }
        with patch.object(mod, "read_json", return_value=bad):
            with self.assertRaises(RuntimeError):
                official_listing_candidate("Euronext", "R27644", self.mapped)

    def test_persisted_decision_recovery_is_not_marked_new(self):
        jobs = []
        candidate = {
            "source_id": "R27644",
            "canonical_url": "https://hrhub.wd3.myworkdayjobs.com/Euronext_Career_Page/job/Milan/Business-Operations-Analyst_R27644",
            "fingerprint": "abc",
        }
        self.assertTrue(upsert_recovered(jobs, candidate, persisted_decision=True))
        self.assertEqual(jobs[0]["status"], "STILL_OPEN")


if __name__ == "__main__":
    unittest.main()
