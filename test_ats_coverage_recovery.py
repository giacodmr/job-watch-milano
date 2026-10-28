"""Mollie must be certified from two official inventories, never an ATS subset."""
import unittest
from unittest.mock import patch

import collector


A = "1e73c5ec-31d5-4350-a1a7-ee6f6e769f7e"
B = "9c3e0b6f-ce76-4bd7-9144-cabce7d5b555"
C = "74d50b4c-be6b-4297-8512-3baaf60f3d41"
MOLLIE = {"company": "Mollie", "ats": {
    "inventory_url": "https://jobs.mollie.com/vacancies",
    "family": "Ashby public posting API + Mollie official job listing",
    "tenant": "Mollie",
}}


def board(ids=(A, B), count=None):
    n = len(ids) if count is None else count
    return (
        f'<a href="/vacancies">jobs</a><b>{n}</b><span>Jobs</span>'
        + "".join(f'<a href="/vacancies/{sid}">Role {i}</a>' for i, sid in enumerate(ids))
    ), "https://jobs.mollie.com/vacancies"


def feed(ids=(A, B), locs=("Milan", "Rome")):
    return {"apiVersion": "1", "jobs": [{
        "jobUrl": f"https://jobs.ashbyhq.com/Mollie/{sid}",
        "applyUrl": f"https://jobs.ashbyhq.com/Mollie/{sid}/application",
        "title": "Implementation Manager" if i == 0 else "Product Manager",
        "location": locs[i],
        "isListed": True,
    } for i, sid in enumerate(ids)]}


class MollieParityContract(unittest.TestCase):
    def test_certifies_only_matching_complete_official_inventory(self):
        with patch.object(collector, "get_html", return_value=board()) as html, \
             patch.object(collector, "get_json", return_value=feed()) as api:
            result, attempted = collector.collect_company(MOLLIE)
        self.assertTrue(attempted)
        self.assertEqual(result["coverage"], "VERIFIED")
        self.assertEqual(result["inventory_count"], 2)
        self.assertEqual(result["reconciliation"], {"public_list_count": 2, "ats_list_count": 2})
        self.assertEqual({job["source_id"] for job in result["jobs"]}, {A, B})
        self.assertEqual(result["jobs"][0]["canonical_url"], f"https://jobs.mollie.com/vacancies/{A}")
        self.assertEqual(result["jobs"][0]["location"], "Milan")
        self.assertEqual(html.call_count, 2)
        api.assert_called_once_with(
            "https://api.ashbyhq.com/posting-api/job-board/Mollie", {"includeCompensation": "false"}
        )

    def test_rejects_mismatched_total_even_when_some_offers_visible(self):
        with patch.object(collector, "get_html", return_value=board(count=3)), \
             patch.object(collector, "get_json", return_value=feed()):
            result, _ = collector.collect_company(MOLLIE)
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertIn("count mismatch", result["reason"])
        self.assertEqual(result["jobs"], [])

    def test_rejects_feed_missing_one_public_vacancy(self):
        with patch.object(collector, "get_html", return_value=board()), \
             patch.object(collector, "get_json", return_value=feed(ids=(A,), locs=("Milan",))):
            result, _ = collector.collect_company(MOLLIE)
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertIn("site/Ashby listing mismatch", result["reason"])

    def test_rejects_extra_ats_posting_not_in_company_inventory(self):
        with patch.object(collector, "get_html", return_value=board()), \
             patch.object(collector, "get_json", return_value=feed((A, B, C), ("Milan", "London", "Milan"))):
            result, _ = collector.collect_company(MOLLIE)
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertIn("feed_only=1", result["reason"])

    def test_unlisted_ashby_rows_do_not_count_as_public_jobs(self):
        payload = feed((A, B, C), ("Milan", "London", "Milan"))
        payload["jobs"][-1]["isListed"] = False
        with patch.object(collector, "get_html", return_value=board()), \
             patch.object(collector, "get_json", return_value=payload):
            result, _ = collector.collect_company(MOLLIE)
        self.assertEqual(result["coverage"], "VERIFIED")
        self.assertEqual(len(result["jobs"]), 2)

    def test_rejects_unstable_inventory_between_reads(self):
        with patch.object(collector, "get_html", side_effect=[board(), board((A, C))]), \
             patch.object(collector, "get_json", return_value=feed()):
            result, _ = collector.collect_company(MOLLIE)
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertIn("changed while reconciling", result["reason"])

    def test_rejects_malformed_host_uuid_missing_location_and_duplicate(self):
        cases = []
        invalid_host = feed()
        invalid_host["jobs"][0]["jobUrl"] = "https://untrusted.example/Mollie/" + A
        cases.append(invalid_host)
        invalid_location = feed()
        invalid_location["jobs"][0]["location"] = ""
        cases.append(invalid_location)
        duplicate_id = feed()
        duplicate_id["jobs"][1]["jobUrl"] = duplicate_id["jobs"][0]["jobUrl"]
        cases.append(duplicate_id)
        for payload in cases:
            with self.subTest(payload=payload), \
                 patch.object(collector, "get_html", return_value=board()), \
                 patch.object(collector, "get_json", return_value=payload):
                result, _ = collector.collect_company(MOLLIE)
            self.assertEqual(result["coverage"], "PARTIAL")
            self.assertEqual(result["jobs"], [])

    def test_http_unavailable_is_partial_not_zero_or_verified(self):
        import requests
        with patch.object(collector, "get_html", return_value=board()), \
             patch.object(collector, "get_json", side_effect=requests.HTTPError("403")):
            result, _ = collector.collect_company(MOLLIE)
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertIn("Ashby feed not accessible", result["reason"])
        self.assertEqual(result["inventory_count"], None)

    def test_target_location_filter_after_full_global_parity(self):
        with patch.object(collector, "get_html", return_value=board()), \
             patch.object(collector, "get_json", return_value=feed(locs=("Milan", "Amsterdam"))):
            result, _ = collector.collect_company(MOLLIE)
        self.assertEqual(result["coverage"], "VERIFIED")
        self.assertEqual(result["inventory_count"], 2)
        self.assertEqual([j["source_id"] for j in result["jobs"]], [A])


if __name__ == "__main__":
    unittest.main()
