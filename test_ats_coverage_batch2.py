"""Regression contracts for official Nexi Oracle and Revolut ATS recovery."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import collector


NEXI = {"company": "Nexi", "ats": {
    "family": "Oracle Recruiting Cloud / Oracle HCM (Nexi official Candidate Experience CX_1)",
    "inventory_url": "https://fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs",
}}


def oracle_page(total, rows):
    return {"items": [{"TotalJobsCount": total, "requisitionList": rows}]}


class NexiOracle(unittest.TestCase):
    def test_dispatch_uses_existing_official_oracle_adapter(self):
        self.assertIs(collector.choose(NEXI), collector.collect_oracle)
        self.assertEqual(collector.oracle_site_from_inventory(NEXI["ats"]["inventory_url"]), "CX_1")

    def test_oracle_pagination_reconciles_all_ids_before_location_filter(self):
        items = [
            {"Id": "3001", "Title": "Strategy Analyst", "PrimaryLocation": "Milan, Italy"},
            {"Id": "3002", "Title": "Financial Analyst", "PrimaryLocation": "Rome, Italy"},
            {"Id": "3003", "Title": "Backend Developer", "PrimaryLocation": "Paris, France"},
        ]
        pages = [(oracle_page(3, items[:2]), "https://official.example/api"), (oracle_page(3, items[2:]), "https://official.example/api")]
        with patch.object(collector, "oracle_backend_hosts", return_value=["fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com"]),\
             patch.object(collector, "oracle_get_page", side_effect=pages) as get:
            result, attempted = collector.collect_company(NEXI)
        self.assertTrue(attempted)
        self.assertEqual(result["coverage"], "VERIFIED")
        self.assertEqual(result["inventory_count"], 3)
        self.assertEqual({j["source_id"] for j in result["jobs"]}, {"3001", "3002"})
        self.assertEqual(result["jobs"][0]["canonical_url"],
                         "https://fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/3001")
        self.assertEqual(get.call_args_list[1].args[-1], 2)

    def test_incomplete_oracle_returns_partial_not_verified(self):
        pages = [(oracle_page(2, [{"Id":"3001","Title":"Strategy Analyst","PrimaryLocation":"Milan, Italy"}]),"https://official.example/api")]
        with patch.object(collector, "oracle_backend_hosts", return_value=["fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com"]),\
             patch.object(collector, "oracle_get_page", side_effect=pages+[ (oracle_page(2, []),"https://official.example/api") ]*4):
            result, _ = collector.collect_company(NEXI)
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertNotEqual(result["inventory_count"], 2)


if __name__ == "__main__":
    unittest.main()
