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

    def test_country_only_italian_oracle_rows_do_not_fake_full_milan_coverage(self):
        rows=[
            {"Id":"1101","Title":"Product Manager - ECR","PrimaryLocation":"Italy","PrimaryLocationCountry":"Italy","secondaryLocations":[]},
            {"Id":"1102","Title":"Commercial Analyst","PrimaryLocation":"Milan, Italy","PrimaryLocationCountry":"Italy","secondaryLocations":[]},
        ]
        with patch.object(collector,"oracle_backend_hosts",return_value=["fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com"]),\
             patch.object(collector,"oracle_get_page",return_value=(oracle_page(2,rows),"https://official.example/api")):
            result,_=collector.collect_company(NEXI)
        self.assertEqual(result["coverage"],"PARTIAL")
        self.assertEqual(result["inventory_count"],2)
        self.assertEqual(result["reconciliation"]["country_only_italy_count"],1)
        self.assertEqual(result["reconciliation"]["country_only_sample_ids"],["1101"])
        self.assertEqual([j["source_id"] for j in result["jobs"]],["1102"])

    def test_incomplete_oracle_returns_partial_not_verified(self):
        pages = [(oracle_page(2, [{"Id":"3001","Title":"Strategy Analyst","PrimaryLocation":"Milan, Italy"}]),"https://official.example/api")]
        with patch.object(collector, "oracle_backend_hosts", return_value=["fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com"]),\
             patch.object(collector, "oracle_get_page", side_effect=pages+[ (oracle_page(2, []),"https://official.example/api") ]*4):
            result, _ = collector.collect_company(NEXI)
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertNotEqual(result["inventory_count"], 2)


class RevolutNextData(unittest.TestCase):
    @staticmethod
    def row(sid, name, location):
        return {"id": sid, "text": name, "locations": location, "team": "Operations"}

    @staticmethod
    def html(rows, count=None, total=None):
        import html as html_module
        payload={"props":{"pageProps":{"positions":rows,"widgetData":{
            "careers-teams-widget":{"total":len(rows) if total is None else total}}}}}
        label=len(rows) if count is None else count
        return f'<h1>We have {label} open positions</h1><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'

    def test_contract_counts_ids_and_locations_global_before_filter(self):
        import revolut_collector as rc
        rows=[
            self.row("cfb550df-3acc-4f7d-b6d0-faaf2090ad08","Credit Manager (Policy)",[
                {"name":"London","country":"United Kingdom","type":"office"},
                {"name":"UK - Remote","country":"United Kingdom","type":"remote"}]),
            self.row("531a667a-805b-47c8-8749-cc0e536ed122","Credit Manager (Policy)",[
                {"name":"Sao Paulo","country":"Brazil","type":"office"}]),
        ]
        with patch.object(collector,"get_html",return_value=(self.html(rows),rc.BOARD)):
            jobs,total=rc._board_snapshot()
        self.assertEqual(total,2)
        self.assertEqual(len(jobs),2)
        self.assertIn("London, United Kingdom",jobs[rows[0]["id"]]["location"])

    def test_rejects_mismatched_visible_and_widget_counts(self):
        import revolut_collector as rc
        rows=[self.row("cfb550df-3acc-4f7d-b6d0-faaf2090ad08","Credit Manager",[
            {"name":"London","country":"United Kingdom","type":"office"}])]
        for wrong in ({"count":2},{"total":2}):
            with self.subTest(wrong=wrong),patch.object(collector,"get_html",return_value=(self.html(rows,**wrong),rc.BOARD)):
                with self.assertRaises(collector.NotCheckable):
                    rc._board_snapshot()

    def test_duplicate_uuid_invalidates_full_inventory(self):
        import revolut_collector as rc
        row=self.row("cfb550df-3acc-4f7d-b6d0-faaf2090ad08","Credit Manager",[
            {"name":"London","country":"United Kingdom","type":"office"}])
        with patch.object(collector,"get_html",return_value=(self.html([row,row]),rc.BOARD)):
            with self.assertRaises(collector.NotCheckable):
                rc._board_snapshot()

    def test_detail_route_requires_same_official_uuid(self):
        import revolut_collector as rc
        sid="cfb550df-3acc-4f7d-b6d0-faaf2090ad08"
        for detail in (
            {"id":sid,"text":"Credit Manager"},
            {"id":"531a667a-805b-47c8-8749-cc0e536ed122","text":"Credit Manager"},
        ):
            page={"props":{"pageProps":{"position":detail}}}
            url=f"https://www.revolut.com/careers/position/{sid}/"
            with patch.object(collector,"get_html",return_value=(f'<script id="__NEXT_DATA__">{json.dumps(page)}</script>',url)):
                if detail["id"]==sid:self.assertEqual(rc._validate_detail(sid,"Credit Manager"),url)
                else:
                    with self.assertRaises(collector.NotCheckable):
                        rc._validate_detail(sid,"Credit Manager")

    def test_collect_returns_verified_only_after_stable_second_snapshot(self):
        import revolut_collector as rc
        sid="cfb550df-3acc-4f7d-b6d0-faaf2090ad08"
        observed={sid:{"title":"Credit Manager","location":"London, United Kingdom","team":"Credit"}}
        with patch.object(rc,"_board_snapshot",side_effect=[(observed,1),(observed,1)]),\
             patch.object(rc,"_validate_detail",return_value=f"https://www.revolut.com/careers/position/{sid}/"),\
             patch.object(rc.time,"sleep"):
            result,_=collector.collect_company({"company":"Revolut"})
        self.assertEqual(result["coverage"],"VERIFIED")
        self.assertEqual(result["inventory_count"],1)
        self.assertEqual([j["source_id"] for j in result["jobs"]],[sid])

    def test_volatile_board_remains_partial_and_retains_validated_jobs(self):
        import revolut_collector as rc
        sid="cfb550df-3acc-4f7d-b6d0-faaf2090ad08"
        observed={sid:{"title":"Credit Manager","location":"London, United Kingdom","team":"Credit"}}
        with patch.object(rc,"_board_snapshot",side_effect=[(observed,1),({},0)]),\
             patch.object(rc,"_validate_detail",return_value=f"https://www.revolut.com/careers/position/{sid}/"),\
             patch.object(rc.time,"sleep"):
            result,_=collector.collect_company({"company":"Revolut"})
        self.assertEqual(result["coverage"],"PARTIAL")
        self.assertEqual(len(result["jobs"]),1)
        self.assertIn("changed during collection",result["reason"])


if __name__ == "__main__":
    unittest.main()
