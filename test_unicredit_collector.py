"""Strict first-party UniCredit Avature global enumeration / Italian City contracts."""
import unittest
from unittest.mock import patch

import collector as c
import unicredit_collector as u

DETAIL="https://careers.unicredit.eu/en_GB/jobsuche/JobDetail/Group-Strategy-Benchmarking-Internship-Opportunity-2026/87236"
NONTARGET="https://careers.unicredit.eu/en_GB/jobsuche/JobDetail/Bank-Role-in-Romania/123456"

def page_html(rows,offset=0,total=None):
    total=len(rows) if total is None else total
    start=offset+1
    end=min(offset+15,total)
    cards=[]
    for id,title,world,url in rows:
        cards.append(
          f'<article class="article article--result">'
          f'<h3 class="article__header__text__title"><a href="{url}">{title}</a></h3>'
          f'<span class="job-info-icon job-info-icon_world">{world}</span>'
          f'<span class="job-info-icon job-info-icon_function">Strategy</span>'
          f'<span class="job-info-icon job-info-icon_work">Full-time</span></article>'
        )
    return (f'<div class="list-controls__text__legend"><span>{start}</span> - <span>{end}</span> of <span>{total}</span> results</div>'
            +''.join(cards))

def field(city):
    return (f'<div class="article__content__view__field ">'
      f'<div class="article__content__view__field__label">City</div>'
      f'<div class="article__content__view__field__value">{city}</div></div>')

def job(id,title,world,url):
    return {"id":str(id),"title":title,"world":world,"url":url,"department":"Strategy","employment":"Full-time"}

class UniCreditContracts(unittest.TestCase):
    def test_dispatch(self):
        self.assertIs(c.choose({"company":"UniCredit"}),u.collect_unicredit)

    def test_first_page_total_and_details(self):
        body=page_html([("87236","Strategy Analyst","Italy",DETAIL)])
        with patch.object(c,"get_html",return_value=(body,u.URL)):
            total,rows=u._page(0)
        self.assertEqual(total,1)
        self.assertEqual(rows[0]["id"],"87236")
        self.assertEqual(rows[0]["world"],"Italy")

    def test_page_counter_fail_closed(self):
        body=page_html([("87236","Strategy Analyst","Italy",DETAIL)],total=2)
        with patch.object(c,"get_html",return_value=(body,u.URL)):
            with self.assertRaises(c.NotCheckable):u._page(0)

    def test_official_detail_identity_must_match(self):
        self.assertTrue(u._official(DETAIL,True,"87236"))
        self.assertFalse(u._official(DETAIL,True,"99999"))
        self.assertFalse(u._official("https://bad.example/en_GB/jobsuche/JobDetail/XYZ/87236",True,"87236"))
        self.assertFalse(u._official(DETAIL+"?auth=x",True,"87236"))

    def test_city_structured_match_does_not_guess_description(self):
        row=job("87236","Strategy Analyst","Italy",DETAIL)
        with patch.object(c,"get_html",return_value=("<p>Working in Milano</p>"+field("TORINO"),DETAIL)):
            places,city=u._city_details(row)
        self.assertEqual((places,city),([],"TORINO"))

    def test_city_multi_values_milan_rome(self):
        row=job("87236","Strategy Analyst","Italy",DETAIL)
        with patch.object(c,"get_html",return_value=(field("BOLOGNA, MILANO, NAPOLI, ROMA, TORINO"),DETAIL)):
            places,city=u._city_details(row)
        self.assertEqual(places,["Milan","Rome"])

    def test_city_not_given_is_partial(self):
        row=job("87236","Strategy Analyst","Italy",DETAIL)
        with patch.object(c,"get_html",return_value=("<div>Milano in job description but City absent</div>",DETAIL)):
            with self.assertRaises(c.NotCheckable):u._city_details(row)

    def test_complete_inventory_and_italy_city_eligible(self):
        it=job("87236","Group Strategy Internship","Italy",DETAIL)
        other=job("123456","Risk Control","Romania",NONTARGET)
        with patch.object(u,"_page",side_effect=[(2,[it,other]),(2,[it,other])]),\
            patch.object(u,"_city_details",return_value=(["Milan"],"MILANO")) as detail,\
            patch.object(u.time,"sleep"):
            result,attempted=c.collect_company({"company":"UniCredit"})
        self.assertTrue(attempted)
        self.assertEqual(result["coverage"],"VERIFIED")
        self.assertEqual(result["inventory_count"],2)
        self.assertEqual(result["jobs"][0]["source_id"],"87236")
        self.assertEqual(result["jobs"][0]["location"],"Milan")
        detail.assert_called_once()

    def test_geo_ambiguous_fails_closed_with_no_fake_verified(self):
        it=job("87236","Strategy Analyst","Italy",DETAIL)
        with patch.object(u,"_page",return_value=(1,[it])),\
             patch.object(u,"_city_details",side_effect=c.NotCheckable("no city")):
            result,_=c.collect_company({"company":"UniCredit"})
        self.assertEqual(result["coverage"],"PARTIAL")
        self.assertEqual(result["jobs"],[])

    def test_snapshot_drift_never_verified(self):
        it=job("87236","Strategy Analyst","Italy",DETAIL)
        changed={**it,"title":"Different job"}
        with patch.object(u,"_page",side_effect=[(1,[it]),(1,[changed])]),\
            patch.object(u,"_city_details",return_value=(["Rome"],"ROMA")):
            result,_=c.collect_company({"company":"UniCredit"})
        self.assertEqual(result["coverage"],"PARTIAL")
        self.assertEqual(result["jobs"][0]["location"],"Rome")

    def test_duplicate_job_ids_fail_closed(self):
        it=job("87236","Strategy Analyst","Italy",DETAIL)
        other=job("87236","Other","Romania",DETAIL)
        with patch.object(u,"_page",side_effect=[(2,[it,other])]):
            result,_=c.collect_company({"company":"UniCredit"})
        self.assertEqual(result["coverage"],"PARTIAL")
        self.assertEqual(result["jobs"],[])


if __name__=="__main__":
    unittest.main()
