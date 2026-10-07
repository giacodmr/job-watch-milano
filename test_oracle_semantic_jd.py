"""Real pilot regression: Oracle CE shell must resolve the matching public JD."""
import unittest
from unittest.mock import Mock, patch
import enrich_semantic_jds as enrich

class OracleJDTests(unittest.TestCase):
    def setUp(self):
        self.url = 'https://careers.americanexpress.com/it/sites/CX_1/job/26013626'
        self.rec = {'canonical_url':self.url, 'source_id':'26013626', 'title':'Analyst-Risk Management'}
        self.shell = Mock(text='<base data-apibaseurl="https://egug.fa.us2.oraclecloud.com:443">')
        self.item = {'Id':'26013626', 'Title':self.rec['title'],
            'ExternalDescriptionStr':'<p>Public institutional credit analysis and underwriting duties. </p>'*4,
            'ExternalQualificationsStr':'<p>1-2 years experience preferred. English mandatory.</p>',
            'ExternalResponsibilitiesStr':'<p>Prepare credit risk memorandums.</p>',
            'InternalQualificationsStr':'PRIVATE INTERNAL FIELD MUST NEVER BE READ'}
        self.detail = Mock(url='https://egug.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails')
        self.detail.json.return_value = {'items':[self.item]}
    def test_empty_shell_fetches_full_external_jd_with_identity_check(self):
        with patch.object(enrich.s, 'get', side_effect=[self.shell,self.detail]) as req:
            text, source, method = enrich.fetch_jd(self.rec, {})
        self.assertIn('1-2 years experience preferred',text)
        self.assertIn('Prepare credit risk memorandums',text)
        self.assertNotIn('PRIVATE INTERNAL',text)
        self.assertEqual(method,'oracle_ce_external_detail')
        self.assertIn('recruitingCEJobRequisitionDetails',source)
        self.assertEqual(req.call_args.kwargs['params']['finder'],'ById;Id="26013626",siteNumber=CX_1')
    def test_missing_or_mismatched_official_detail_never_becomes_review(self):
        for field, value in [('Id','different'),('Title','Unrelated job'),('ExternalDescriptionStr','')]:
            item={**self.item,field:value};self.detail.json.return_value={'items':[item]}
            with self.subTest(field=field), patch.object(enrich.s,'get',side_effect=[self.shell,self.detail]), self.assertRaises(enrich.FetchError):
                enrich.fetch_jd(self.rec,{})
        self.detail.json.return_value={'items':[]}
        with patch.object(enrich.s,'get',side_effect=[self.shell,self.detail]), self.assertRaises(enrich.FetchError):
            enrich.fetch_jd(self.rec,{})
    def test_url_id_and_unidentified_backend_fail_closed(self):
        with patch.object(enrich.s,'get') as req, self.assertRaises(enrich.FetchError):
            enrich.fetch_jd({**self.rec,'source_id':'other'}, {})
        req.assert_not_called()
        for raw in ('<html>empty shell</html>', '<base data-apibaseurl="https://unrelated.example">'):
            self.shell.text=raw
            with patch.object(enrich.s,'get',return_value=self.shell) as req, self.assertRaises(enrich.FetchError):
                enrich.fetch_jd(self.rec,{})
            self.assertEqual(req.call_count,1)

if __name__ == '__main__': unittest.main()
