"""Worldline first-party recruiting official details: strict partial-only contracts."""
import unittest
from unittest.mock import patch

import collector as c
import worldline_collector as w

SID="305176"
LOC=["Italy-Milan ","Italy-Rome ","Netherlands-Utrecht "]
def row(id=SID,title="Business Development Manager",loc=LOC,brand="Worldline"):
    return {"id":id,"unifiedStandardTitle":title,"unifiedUrlTitle":title.replace(" ","-"),
            "sfstd_marketingBrand_obj":[brand],"jobLocationShort":loc,"custJobFamily":["Sales"],"jobContract":["Permanent"]}
def result(id=SID,title="Business Development Manager",loc=LOC,brand="Worldline"):
    return {"response":row(id,title,loc,brand)}

class WorldlineContracts(unittest.TestCase):
    def test_dispatch(self):
        self.assertIs(c.choose({"company":"Worldline"}),w.collect_worldline)
    def test_country_location_precise(self):
        self.assertEqual(w._target_cities(["Romania-Bucharest","Italy-Milan ","Italy-Rome ","Italy-Trento "]),"Milan | Rome")
        self.assertEqual(w._target_cities(["Romania-Bucharest","UK-London","Italy-Remote"]), "")
        self.assertEqual(w._target_cities(["Italy-Milan, United States"]), "")
    def test_canonical_detail_id(self):
        got=w._official_url(row())
        self.assertEqual(got,"https://jobs.worldline.com/job/Business-Development-Manager/305176-en_US")
    def test_invalid_slug_blocks(self):
        with self.assertRaises(c.NotCheckable):w._official_url(row(title="bad",id="NaN"))
        bad=row();bad["unifiedUrlTitle"]="bad/path"
        with self.assertRaises(c.NotCheckable):w._official_url(bad)
    def test_detail_title_and_id_parity(self):
        url=w._official_url(row())
        with patch.object(c,"get_html",return_value=("<title>Business Development Manager Job Details | worldline</title> requisition 305176",url)):
            w._validate_detail(row(),url)
        with patch.object(c,"get_html",return_value=("<title>Other Job Details</title> 305176",url)):
            with self.assertRaises(c.NotCheckable):w._validate_detail(row(),url)
    def test_complete_api_enumerated_but_never_verified(self):
        p0=[result(),result("305260","FCC Controller",["Belgium-Brussels "])]
        p1=[result(),result("304645","Network Security Admin",["Romania-Bucharest "])]
        with patch.object(w,"_homepage_total",return_value=65),\
             patch.object(w,"_api_page",side_effect=[(4,p0),(4,p1)]),\
             patch.object(w,"_validate_detail") as validate:
            got,_=c.collect_company({"company":"Worldline"})
        self.assertEqual(got["coverage"],"PARTIAL")
        self.assertEqual(got["inventory_count"],65)
        self.assertEqual(got["reconciliation"]["api_distinct_ids"],3)
        self.assertEqual([x["source_id"] for x in got["jobs"]],[SID])
        validate.assert_called_once()
    def test_affiliate_excluded(self):
        with patch.object(w,"_homepage_total",return_value=65),\
             patch.object(w,"_api_page",return_value=(1,[result(brand="PAYONE")])),\
             patch.object(w,"_validate_detail") as validate:
            got,_=c.collect_company({"company":"Worldline"})
        self.assertEqual(got["coverage"],"PARTIAL")
        self.assertEqual(got["jobs"],[])
        validate.assert_not_called()
    def test_missing_detail_retains_partial_not_fabricated(self):
        with patch.object(w,"_homepage_total",return_value=65),\
             patch.object(w,"_api_page",return_value=(1,[result()])),\
             patch.object(w,"_validate_detail",side_effect=c.NotCheckable("No official detail")):
            got,_=c.collect_company({"company":"Worldline"})
        self.assertEqual(got["coverage"],"PARTIAL")
        self.assertEqual(got["jobs"],[])
    def test_unstable_publisher_ids_are_not_certified(self):
        p=[result(),result(SID,title="Conflicting other title")]
        with patch.object(w,"_homepage_total",return_value=65),\
             patch.object(w,"_api_page",return_value=(2,p)):
            got,_=c.collect_company({"company":"Worldline"})
        self.assertEqual(got["coverage"],"PARTIAL")
        self.assertEqual(got["jobs"],[])

if __name__=="__main__":unittest.main()
