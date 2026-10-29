"""Nexi Oracle country-only cards: first-party, per-ID detail positive-only city proof."""
import unittest
from unittest.mock import Mock,patch
import collector as c
import nexi_collector as nex

HOST="fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com"
SITE="CX_1"
def card(sid="3847",title="Product Manager - ECR (Electronic Cash Register)"):
    return {"Id":sid,"Title":title,"PrimaryLocation":"Italy","PrimaryLocationCountry":"IT","secondaryLocations":[]}
def detail(desc, **updates):
    return {"Id":"3847","Title":"Product Manager - ECR (Electronic Cash Register)",
        "PrimaryLocation":"Italy","PrimaryLocationCountry":"IT",
        "ExternalDescriptionStr":desc,"secondaryLocations":[],"otherWorkLocations":[],**updates}
def response(item):
    x=Mock();x.status_code=200;x.json.return_value={"items":[item]}
    x.raise_for_status.return_value=None
    return x

class NexiOracleCityTests(unittest.TestCase):
    def test_official_role_based_in_milan(self):
        body="<p>In this role based in Milan, you will own ECR products.</p>"
        with patch.object(c,"get_session") as session:
            session.return_value.get.return_value=response(detail(body))
            self.assertEqual(nex.confirmed_target_city(card(),HOST,SITE),"Milan")
            self.assertIn('ById;Id="3847",siteNumber=CX_1',str(session.return_value.get.call_args))
    def test_explicit_roma_sentence(self):
        with patch.object(c,"get_session") as session:
            session.return_value.get.return_value=response(detail("This position is based in Roma."))
            self.assertEqual(nex.confirmed_target_city(card(),HOST,SITE),"Rome")
    def test_corporate_headquarters_not_role_location(self):
        jd="Our offices and headquarters are in Milan, Italy. This role is hybrid in Italy."
        with patch.object(c,"get_session") as session:
            session.return_value.get.return_value=response(detail(jd))
            self.assertIsNone(nex.confirmed_target_city(card(),HOST,SITE))
    def test_description_city_mention_alone_not_valid(self):
        with patch.object(c,"get_session") as session:
            session.return_value.get.return_value=response(detail("Serves merchants in Milano and Roma across Italy"))
            self.assertIsNone(nex.confirmed_target_city(card(),HOST,SITE))
    def test_id_mismatch_fails_closed(self):
        with patch.object(c,"get_session") as session:
            session.return_value.get.return_value=response(detail("In this role based in Milan",Id="other"))
            with self.assertRaises(c.NotCheckable):nex.confirmed_target_city(card(),HOST,SITE)
    def test_title_mismatch_fails_closed(self):
        with patch.object(c,"get_session") as session:
            session.return_value.get.return_value=response(detail("In this role based in Milan",Title="Unrelated job"))
            with self.assertRaises(c.NotCheckable):nex.confirmed_target_city(card(),HOST,SITE)
    def test_host_site_change_fails_closed(self):
        with self.assertRaises(c.NotCheckable):nex.confirmed_target_city(card(),"other.oraclecloud.com",SITE)
        with self.assertRaises(c.NotCheckable):nex.confirmed_target_city(card(),HOST,"CX_2")
    def test_unavailable_or_multi_response_fails_closed(self):
        with patch.object(c,"get_session") as session:
            session.return_value.get.return_value=response(None)
            with self.assertRaises(c.NotCheckable):nex.confirmed_target_city(card(),HOST,SITE)
    def test_global_complete_does_not_certify_ambiguous_italy(self):
        rows=[card(),card("3174","Graduate IT"),{"Id":"7000","Title":"German job","PrimaryLocation":"Berlin"}]
        payload={"items":[{"TotalJobsCount":3,"requisitionList":rows}]}
        company={"company":"Nexi","ats":{"inventory_url":"https://"+HOST+"/hcmUI/CandidateExperience/en/sites/CX_1/jobs"}}
        with patch.object(c,"oracle_backend_hosts",return_value=[HOST]),\
             patch.object(c,"oracle_get_page",return_value=(payload,"https://"+HOST+"/hcmRestApi/resources/latest/recruitingCEJobRequisitions")) ,\
             patch.object(nex,"confirmed_target_city",side_effect=["Milan",None]):
            result,_=c.collect_company(company)
        self.assertEqual(result["coverage"],"PARTIAL")
        self.assertEqual(result["inventory_count"],3)
        self.assertEqual(result["reconciliation"]["country_only_italy_count"],1)
        self.assertEqual([x["source_id"] for x in result["jobs"]],["3847"])
        self.assertEqual(result["jobs"][0]["location"],"Milan")

if __name__=="__main__":unittest.main()
