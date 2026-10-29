"""Checkout.com official Ashby posting API contract tests (no network)."""
import unittest
from unittest.mock import patch

import collector
import checkout_collector as co

SID="b563a46e-e4b9-4fd1-a7bb-6211f1564523"
SID2="611afa2b-41bb-4897-ba6b-def8364eccf8"


def posting(sid,title="Strategy Analyst",loc="Milan",listed=True):
    return {
        "id":sid,"title":title,"location":loc,"department":"Strategy",
        "jobUrl":f"https://jobs.ashbyhq.com/checkout.com/{sid}",
        "applyUrl":f"https://jobs.ashbyhq.com/checkout.com/{sid}/application",
        "isListed":listed,"publishedAt":"2026-10-29T08:00:00Z",
    }


class CheckoutContracts(unittest.TestCase):
    def test_collector_dispatches(self):
        self.assertIs(collector.choose({"company":"Checkout.com"}),co.collect_checkout)

    def test_first_party_corporate_link_evidences_board_owner(self):
        page='<a href="https://jobs.ashbyhq.com/checkout.com/form/talent-communities">Talent pool</a>'
        with patch.object(collector,"get_html",return_value=(page,co.CORPORATE)):
            self.assertEqual(co._corporate_board_confirmation(),co.CORPORATE)
        with patch.object(collector,"get_html",return_value=("<a href='https://jobs.ashbyhq.com/other/abc'>Other</a>",co.CORPORATE)):
            with self.assertRaises(collector.NotCheckable):co._corporate_board_confirmation()

    def test_public_board_and_location_complete(self):
        data={"apiVersion":"1","jobs":[posting(SID),posting(SID2,loc="London")]}
        with patch.object(collector,"get_json",return_value=data):
            snap=co._snapshot()
        self.assertEqual(set(snap),{SID,SID2})
        self.assertEqual(snap[SID]["location"],"Milan")

    def test_unlisted_not_copied_into_canonical_jobs(self):
        data={SID:{"title":"Strategy Analyst","location":"Milan","department":"Strategy",
               "published_at":None,"job_url":f"https://jobs.ashbyhq.com/checkout.com/{SID}",
               "apply_url":f"https://jobs.ashbyhq.com/checkout.com/{SID}/application","listed":False},
              SID2:{"title":"Strategy Manager","location":"Milan","department":"Strategy",
               "published_at":None,"job_url":f"https://jobs.ashbyhq.com/checkout.com/{SID2}",
               "apply_url":f"https://jobs.ashbyhq.com/checkout.com/{SID2}/application","listed":True}}
        with patch.object(co,"_corporate_board_confirmation",return_value=co.CORPORATE),patch.object(co,"_snapshot",side_effect=[data,data]):
            result,_=collector.collect_company({"company":"Checkout.com"})
        self.assertEqual(result["coverage"],"VERIFIED")
        self.assertEqual(result["inventory_count"],1)
        self.assertEqual([j["source_id"] for j in result["jobs"]],[SID2])

    def test_duplicate_or_missing_location_fails_closed(self):
        for rows in ([posting(SID),posting(SID)], [posting(SID,loc="")]):
            with self.subTest(rows=rows),patch.object(collector,"get_json",return_value={"apiVersion":"1","jobs":rows}):
                with self.assertRaises(collector.NotCheckable):co._snapshot()

    def test_cross_board_url_does_not_certify(self):
        data=posting(SID);data["jobUrl"]=f"https://jobs.ashbyhq.com/another-board/{SID}"
        with patch.object(collector,"get_json",return_value={"apiVersion":"1","jobs":[data]}):
            with self.assertRaises(collector.NotCheckable):co._snapshot()

    def test_snapshot_mismatch_retains_partial(self):
        row={SID:{"title":"Strategy Analyst","location":"Milan","department":"Strategy","published_at":None,
                  "job_url":f"https://jobs.ashbyhq.com/checkout.com/{SID}",
                  "apply_url":f"https://jobs.ashbyhq.com/checkout.com/{SID}/application","listed":True}}
        with patch.object(co,"_corporate_board_confirmation",return_value=co.CORPORATE),\
             patch.object(co,"_snapshot",side_effect=[row,{}]):
            result,_=collector.collect_company({"company":"Checkout.com"})
        self.assertEqual(result["coverage"],"PARTIAL")
        self.assertEqual(result["jobs"],[])

    def test_zero_target_roles_can_be_verified_when_global_board_is_complete(self):
        row={SID:{"title":"Senior Engineer","location":"Shanghai","department":"Engineering","published_at":None,
                  "job_url":f"https://jobs.ashbyhq.com/checkout.com/{SID}",
                  "apply_url":f"https://jobs.ashbyhq.com/checkout.com/{SID}/application","listed":True}}
        with patch.object(co,"_corporate_board_confirmation",return_value=co.CORPORATE),\
             patch.object(co,"_snapshot",side_effect=[row,row]):
            result,_=collector.collect_company({"company":"Checkout.com"})
        self.assertEqual(result["coverage"],"VERIFIED")
        self.assertEqual(result["inventory_count"],1)
        self.assertEqual(result["jobs"],[])


if __name__=="__main__":
    unittest.main()
