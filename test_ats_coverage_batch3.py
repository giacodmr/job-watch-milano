"""Contracts for Dojo first-party Astro + Greenhouse corporate listings."""
import json
from unittest import TestCase, main
from unittest.mock import patch

import collector
import dojo_collector as dojo

D1="4997424101"
D2="4986354101"


def gh(sid,title,city):
    return {"id":int(sid),"title":title,
            "absolute_url":f"https://www.dojo.careers/jobs/{sid}/?gh_jid={sid}",
            "location":{"name":city},"updated_at":"2026-10-21T09:02:44-04:00",
            "departments":[{"name":"Business Strategy"}]}

def wrapped(item):
    if isinstance(item,dict):
        return [0,{key:wrapped(value) for key,value in item.items()}]
    if isinstance(item,list):
        return [1,[wrapped(value) for value in item]]
    return [0,item]

def first_party(items,limit=10,has_more=False):
    payload={"jobs":wrapped([{"id":str(x["id"]),"title":x["title"],
        "absolute_url":x["absolute_url"],"location":"UK "+x["location"]["name"],
        "updated_at":x["updated_at"],"department":"Business Strategy"} for x in items]),
        "initialBatchSize":wrapped(limit),"initialPageOffset":wrapped(0),
        "hasMoreJobs":wrapped(has_more),"filterOptions":wrapped({})}
    return f'<html><astro-island component-url="https://assets.dojo.tech/releases/p/client/_astro/Jobs.abc.js" props=\x27{json.dumps(payload)}\x27></astro-island></html>'


class DojoATS(TestCase):
    def test_dispatch_is_first_party_adapter(self):
        self.assertIs(collector.choose({"company":"Dojo"}),dojo.collect_dojo)

    def test_decodes_astro_jobs(self):
        items=[gh(D1,"Brand Designer","London")]
        with patch.object(collector,"get_html",return_value=(first_party(items,limit=10,has_more=False),dojo.BOARD)):
            jobs,limit,more=dojo._corporate_snapshot()
        self.assertEqual((len(jobs),limit,more),(1,10,False))
        self.assertEqual(jobs[0]["id"],D1)

    def test_full_greenhouse_publisher_proves_count(self):
        items=[gh(D1,"Brand Designer","London"),gh(D2,"Account Manager","Madrid")]
        with patch.object(collector,"get_json",return_value={"jobs":items,"meta":{"total":2}}):
            parsed,total=dojo._greenhouse_snapshot()
        self.assertEqual(total,2)
        self.assertEqual(len(parsed),2)

    def test_undercount_and_duplicate_fail_closed(self):
        items=[gh(D1,"Brand Designer","London")]
        for board in ({"jobs":items,"meta":{"total":2}},
                      {"jobs":items*2,"meta":{"total":2}}):
            with self.subTest(board=board),patch.object(collector,"get_json",return_value=board):
                with self.assertRaises(collector.NotCheckable):
                    dojo._greenhouse_snapshot()

    def test_cross_site_urls_must_match_gh_id(self):
        for url in ("https://bad.example/jobs/4997424101/?gh_jid=4997424101",
                    "https://www.dojo.careers/jobs/4997424101/?gh_jid=1234567890",
                    "https://www.dojo.careers/jobs/1234567890/?gh_jid=1234567890",
                    "http://www.dojo.careers/jobs/4997424101/"):
            self.assertFalse(dojo._id_in_url(url,D1))
        self.assertTrue(dojo._id_in_url(gh(D1,"Brand Designer","London")["absolute_url"],D1))

    def test_initial_first_party_must_match_official_publisher_order(self):
        a=gh(D1,"Brand Designer","London")
        b=gh(D2,"Account Manager","Madrid")
        dojo._check_first_batch([{"id":D1,"title":a["title"],"url":a["absolute_url"]}],1,True,[a,b],2)
        with self.assertRaises(collector.NotCheckable):
            dojo._check_first_batch([{"id":D2,"title":a["title"],"url":a["absolute_url"]}],1,True,[a,b],2)

    def test_official_detail_requires_exact_title(self):
        row=gh(D1,"Brand Designer","London")
        with patch.object(collector,"get_html",return_value=("<h1>Brand Designer</h1>",row["absolute_url"])):
            self.assertEqual(dojo._verify_official_detail(row),row["absolute_url"])
        with patch.object(collector,"get_html",return_value=("<h1>Other role</h1>",row["absolute_url"])):
            with self.assertRaises(collector.NotCheckable):
                dojo._verify_official_detail(row)

    def test_real_collector_demands_two_complete_snapshots(self):
        a=gh(D1,"Brand Designer","Milan")
        b=gh(D2,"Account Manager","Madrid")
        first=[{"id":D1,"title":a["title"],"url":a["absolute_url"]}]
        with patch.object(dojo,"_corporate_snapshot",side_effect=[(first,1,True),(first,1,True)]),\
             patch.object(dojo,"_greenhouse_snapshot",side_effect=[([a,b],2),([a,b],2)]),\
             patch.object(dojo,"_verify_official_detail",return_value=a["absolute_url"]) as detail,\
             patch.object(dojo.time,"sleep"):
            result,attempted=collector.collect_company({"company":"Dojo"})
        self.assertTrue(attempted)
        self.assertEqual(result["coverage"],"VERIFIED")
        self.assertEqual(result["inventory_count"],2)
        self.assertEqual(len(result["jobs"]),1)
        self.assertEqual(result["jobs"][0]["source_id"],D1)
        self.assertEqual(detail.call_count,2)

    def test_drift_keeps_partial_instead_of_faking_certification(self):
        a=gh(D1,"Brand Designer","London")
        b=gh(D2,"Account Manager","Madrid")
        first=[{"id":D1,"title":a["title"],"url":a["absolute_url"]}]
        with patch.object(dojo,"_corporate_snapshot",side_effect=[(first,1,True),(first,1,True)]),\
             patch.object(dojo,"_greenhouse_snapshot",side_effect=[([a,b],2),([a],1)]),\
             patch.object(dojo,"_verify_official_detail",return_value=a["absolute_url"]),\
             patch.object(dojo.time,"sleep"):
            result,_=collector.collect_company({"company":"Dojo"})
        self.assertEqual(result["coverage"],"PARTIAL")
        self.assertNotEqual(result["collector"],"dojo_corporate_first_party_astro_greenhouse_id_parity_v1")


if __name__=="__main__":
    main()
