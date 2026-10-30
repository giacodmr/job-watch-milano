"""PayPal first-party Eightfold PCS-X explicit Milan/Rome inventory contracts."""
import unittest
from unittest.mock import patch
import collector as c
import paypal_collector as p

SID="274922258239"
TITLE="Developer/Agency Commercial Lead"
URL=p.ORIGIN+"/careers/job/"+SID
def row(sid=SID,name=TITLE,loc=None):
 return {"id":int(sid),"name":name,"locations":loc or ["Milan, Milano, Italy"],
   "positionUrl":"/careers/job/"+sid,"department":"Sales","displayJobId":"R0137459",
   "postedTs":1790035200,"workLocationOption":"onsite"}
def snap():
 return {SID:{"id":SID,"title":TITLE,"locations":["Milan, Milano, Italy"],"url":URL,
     "department":"Sales","displayJobId":"R0137459","postedTs":1790035200,"workLocationOption":"onsite"}}
class PayPalContracts(unittest.TestCase):
 def test_dispatch(self):
  self.assertIs(c.choose({"company":"PayPal"}),p.collect_paypal)
 def test_public_location_count_one_complete(self):
  with patch.object(c,"get_json",return_value={"data":{"count":1,"positions":[row()]}}),\
       patch.object(p.time,"sleep"):
   x=p._search("Italy")
  self.assertEqual(list(x),[SID])
 def test_location_pagination_not_silent(self):
  with patch.object(c,"get_json",return_value={"data":{"count":2,"positions":[row()]}}):
   with self.assertRaises(c.NotCheckable):p._search("Italy")
 def test_missing_or_mismatched_id_fails(self):
  bad=row();bad["positionUrl"]="/careers/job/987654321"
  with patch.object(c,"get_json",return_value={"data":{"count":1,"positions":[bad]}}):
   with self.assertRaises(c.NotCheckable):p._search("Italy")
 def test_detail_exact_id_name_and_locations(self):
  d={"data":{"id":int(SID),"name":TITLE,"locations":["Milan, Milano, Italy"],"positionUrl":"/careers/job/"+SID,
    "publicUrl":URL,"jobDescription":"Public role description"}}
  with patch.object(c,"get_json",return_value=d):p._detail(snap()[SID])
  d["data"]["name"]="Some other role"
  with patch.object(c,"get_json",return_value=d):
   with self.assertRaises(c.NotCheckable):p._detail(snap()[SID])
 def test_sitemap_italy_id_extraction(self):
  xml='<urlset><url><loc>https://paypal.eightfold.ai/careers/job/274922258239-developer-agency-commercial-lead-milan-milano-italy?domain=paypal.com</loc></url><url><loc>https://paypal.eightfold.ai/careers/job/999999999-other-job-paris-france?domain=paypal.com</loc></url></urlset>'
  with patch.object(c,"get_html",return_value=(xml,p.SITEMAP)):
   ids,count=p._sitemap_italy_ids()
  self.assertEqual(ids,{SID});self.assertEqual(count,2)
 def test_complete_geographic_scope_certified_no_global_claim(self):
  with patch.object(p,"_search",side_effect=[snap(),snap(),{},snap(),snap(),{}]),\
       patch.object(p,"_sitemap_italy_ids",return_value=({SID},317)),\
       patch.object(p,"_detail") as check,\
       patch.object(p.time,"sleep"):
   r,_=c.collect_company({"company":"PayPal"})
  self.assertEqual(r["coverage"],"VERIFIED")
  self.assertEqual(r["inventory_count"],1)
  self.assertEqual(r["jobs"][0]["canonical_url"],URL)
  self.assertEqual(r["reconciliation"]["global_sitemap_jobs_unreconciled"],317)
  self.assertIn("Milan/Rome only",r["reconciliation"]["verified_scope"])
  check.assert_called_once()
 def test_no_false_verified_when_italy_city_mismatch(self):
  with patch.object(p,"_search",side_effect=[snap(),{}, {},snap(),{},{}]),\
       patch.object(p,"_sitemap_italy_ids"):
   r,_=c.collect_company({"company":"PayPal"})
  self.assertEqual(r["coverage"],"PARTIAL")
 def test_no_false_verified_when_sitemap_drift(self):
  with patch.object(p,"_search",side_effect=[snap(),snap(),{},snap(),snap(),{}]),\
       patch.object(p,"_sitemap_italy_ids",return_value=(set(),317)):
   r,_=c.collect_company({"company":"PayPal"})
  self.assertEqual(r["coverage"],"PARTIAL")
 def test_missing_official_detail_partial_not_fabricated(self):
  with patch.object(p,"_search",side_effect=[snap(),snap(),{},snap(),snap(),{}]),\
       patch.object(p,"_sitemap_italy_ids",return_value=({SID},317)),\
       patch.object(p,"_detail",side_effect=c.NotCheckable("invalid")):
   r,_=c.collect_company({"company":"PayPal"})
  self.assertEqual(r["coverage"],"PARTIAL")
  self.assertEqual(r["jobs"],[])

if __name__=="__main__":unittest.main()
