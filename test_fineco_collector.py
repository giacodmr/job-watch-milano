"""Fineco employee careers JSON and Intervieweb first-party link contracts."""
import unittest
from unittest.mock import Mock, patch
import collector as c
import fineco_collector as f

URL="https://finecobank.intervieweb.it/jobs/digital-analytics-madtech-specialist-156616/it/"
def raw(sid="156616",title="Digital Analytics & MadTech Specialist",location="Milano",url=URL):
 return {"id":sid,"title":title,"location":location,"locationLabel":"Sede",
    "url":url,"function":"Marketing","levelOfExperience":"Experienced","published":"19-10-2026 (13:00)"}
def response(rows):
 x=Mock();x.url=f.ENDPOINT;x.json.return_value={"jobs":rows};return x
def normalized():
 return {"156616":{"id":"156616","title":"Digital Analytics & MadTech Specialist","location":"Milano",
      "url":URL,"department":"Marketing","experience":"Experienced","published":"19-10-2026 (13:00)"}}

class FinecoContracts(unittest.TestCase):
 def test_dispatch(self):
  self.assertIs(c.choose({"company":"FinecoBank"}),f.collect_fineco)
 def test_first_party_json_and_exact_url(self):
  with patch.object(c,"get_response",return_value=response([raw()])):
   r=f._public_snapshot()
  self.assertEqual(len(r),1)
  self.assertEqual(r["156616"]["url"],URL)
 def test_duplicate_ids_refused(self):
  with patch.object(c,"get_response",return_value=response([raw(),raw()])):
   with self.assertRaises(c.NotCheckable):f._public_snapshot()
 def test_wrong_ats_host_refused(self):
  with patch.object(c,"get_response",return_value=response([raw(url="https://intervieweb.it/jobs/foo-156616/it/")])):
   with self.assertRaises(c.NotCheckable):f._public_snapshot()
 def test_official_detail_id_mismatch_refused(self):
  with patch.object(c,"get_response",return_value=response([raw(url="https://finecobank.intervieweb.it/jobs/foo-999999/it/")])):
   with self.assertRaises(c.NotCheckable):f._public_snapshot()
 def test_country_only_not_full_geo_certificate(self):
  rr=normalized();rr["156616"]["location"]="Italy"
  with patch.object(f,"_public_snapshot",return_value=rr),patch.object(f,"_detail_page"):
   result,_=c.collect_company({"company":"FinecoBank"})
  self.assertEqual(result["coverage"],"PARTIAL")
 def test_two_full_snapshots_drift_blocks_verified(self):
  with patch.object(f,"_public_snapshot",side_effect=[normalized(),{}]):
   result,_=c.collect_company({"company":"FinecoBank"})
  self.assertEqual(result["coverage"],"PARTIAL")
 def test_verified_when_full_api_snapshot_and_detail_validated(self):
  with patch.object(f,"_public_snapshot",return_value=normalized()),patch.object(f,"_detail_page") as detail:
   result,_=c.collect_company({"company":"FinecoBank"})
  self.assertEqual(result["coverage"],"VERIFIED")
  self.assertEqual(result["inventory_count"],1)
  self.assertEqual(result["jobs"][0]["location"],"Milano")
  self.assertEqual(result["jobs"][0]["canonical_url"],URL)
  detail.assert_called_once()
 def test_no_fabricated_job_if_official_detail_fails(self):
  with patch.object(f,"_public_snapshot",return_value=normalized()),patch.object(f,"_detail_page",side_effect=c.NotCheckable("gone")):
   result,_=c.collect_company({"company":"FinecoBank"})
  self.assertEqual(result["coverage"],"PARTIAL")
  self.assertEqual(result["jobs"],[])
 def test_details_must_have_page_title_and_same_id(self):
  with patch.object(c,"get_html",return_value=("<html><title>Fineco listing</title>"+"x"*130,URL)):
   f._detail_page(normalized()["156616"])
  with patch.object(c,"get_html",return_value=("<html><title>Fineco listing</title>"+"x"*130,"https://finecobank.intervieweb.it/jobs/foo-11111/it/")):
   with self.assertRaises(c.NotCheckable):f._detail_page(normalized()["156616"])

if __name__=="__main__":unittest.main()
