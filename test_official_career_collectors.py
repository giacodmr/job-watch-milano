import json
import unittest
from unittest.mock import patch

import collector
import official_career_collectors as official


def company(adapter, host, **ats):
    return {'company': 'Fixture', 'ats': {'official_adapter': adapter,
            'inventory_url': 'https://' + host + '/jobs', **ats}}


def tikjob(sid, city='Milan'):
    return {'id': sid, 'title': 'Business Analyst', 'city_info': {'en_name': city}}


def tikpage(rows, count):
    return {'code': 0, 'data': {'job_post_list': rows, 'count': count}}


def marriott_page(rows, count, city=None, page=1):
    state = {'params': {'filter': {'city': [city]} if city else {}, 'page_number': page},
             'jobs': rows, 'totalJob': count,
             'facets': [{'field': 'city', 'facet_field_keyvalue': [{'original_value': 'Milan'}]}]}
    return 'window.__PRELOAD_STATE__ = ' + json.dumps({'jobSearch': state}) + ';'


def marjob(sid):
    return {'requisitionID': sid, 'title': 'Business Analyst',
            'originalURL': 'business-analyst/job/P1-' + sid,
            'locations': [{'city': 'Milan', 'country': 'Italy'}],
            'applyURL': 'https://ejwl.fa.us2.oraclecloud.com/job/' + sid}


class PublicInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tiktok = company('tiktok', 'lifeattiktok.com')

    def test_tiktok_exhausts_count_and_keeps_standard_city_scope(self):
        with patch.object(collector, 'post_json', side_effect=[
                tikpage([tikjob('11'), tikjob('12', 'Paris')], 3),
                tikpage([tikjob('13', 'London')], 3)]) as request:
            result, _ = collector.collect_company(self.tiktok)
        self.assertEqual(result['coverage'], 'VERIFIED')
        self.assertEqual(result['inventory_count'], 3)
        self.assertEqual([r['source_id'] for r in result['jobs']], ['11', '13'])
        self.assertEqual(request.call_args_list[1].args[1]['offset'], 2)
        self.assertEqual(request.call_args_list[0].kwargs['headers']['website-path'], 'tiktok')

    def test_tiktok_late_failure_retains_valid_observed_job(self):
        with patch.object(collector, 'post_json', side_effect=[tikpage([tikjob('11')], 2), RuntimeError('network')]):
            result, _ = collector.collect_company(self.tiktok)
        self.assertEqual(result['coverage'], 'PARTIAL')
        self.assertEqual(result['jobs'][0]['source_id'], '11')

    def test_tiktok_repeated_id_changed_count_and_truncation_never_certify(self):
        for second in (tikpage([tikjob('11')], 2), tikpage([tikjob('12')], 3), tikpage([], 2)):
            with self.subTest(second=second), patch.object(collector, 'post_json', side_effect=[tikpage([tikjob('11')], 2), second]):
                result, _ = collector.collect_company(self.tiktok)
                self.assertEqual(result['coverage'], 'PARTIAL')
                self.assertEqual(result['jobs'][0]['source_id'], '11')

    def test_tiktok_malformed_record_is_local_and_prevents_verified(self):
        with patch.object(collector, 'post_json', return_value=tikpage([tikjob('11'), tikjob('12', '')], 2)):
            result, _ = collector.collect_company(self.tiktok)
        self.assertEqual(result['coverage'], 'PARTIAL')
        self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(len(result['record_errors']), 1)

    def test_axa_uses_global_total_not_english_facet_count(self):
        row = {'data': {'req_id': '11', 'slug': '11', 'language': 'en-us', 'title': 'Business Analyst',
                       'city': 'London', 'apply_url': 'https://careers-en-axa.icims.com/jobs/11/login'}}
        with patch.object(collector, 'get_json', side_effect=[
                {'count': 1, 'totalCount': 2, 'languageCounts': {'en-us': {'count': 1}, 'it-it': {'count': 1}}, 'jobs': [row]},
                {'count': 1, 'totalCount': 2, 'languageCounts': {'en-us': {'count': 1}, 'it-it': {'count': 1}},
                 'jobs': [{**row, 'data': {**row['data'], 'req_id': '12', 'slug': '12', 'language': 'it-it',
                          'apply_url': 'https://careers-it-axa.icims.com/jobs/12/login'}}]}]) as request:
            result, _ = collector.collect_company(company('axa', 'jobs.axa.com'))
        self.assertEqual(result['coverage'], 'VERIFIED')
        self.assertEqual(result['inventory_count'], 2)
        self.assertEqual(result['api_locale_count'], 1)
        self.assertEqual(len(result['jobs']), 2)
        self.assertEqual(request.call_args_list[1].args[1]['page'], 2)

    def test_axa_inconsistent_language_counts_never_certify(self):
        with patch.object(collector, 'get_json', return_value={'count': 1, 'totalCount': 2,
                          'languageCounts': {'en-us': {'count': 1}}, 'jobs': []}):
            result, _ = collector.collect_company(company('axa', 'jobs.axa.com'))
        self.assertEqual(result['coverage'], 'PARTIAL')

    def test_marriott_reconciles_exact_city_pages(self):
        pages = [marriott_page([], 2), marriott_page([marjob('11')], 2, 'Milan'),
                 marriott_page([marjob('12')], 2, 'Milan', 2)]
        with patch.object(collector, 'get_html', side_effect=[(p, 'https://careers.marriott.com/jobs') for p in pages]) as request:
            result, _ = collector.collect_company(company('marriott', 'careers.marriott.com'))
        self.assertEqual(result['coverage'], 'VERIFIED')
        self.assertEqual(result['city_counts'], {'Milan': 2})
        self.assertEqual(result['inventory_count'], 2)
        self.assertEqual(request.call_args_list[2].args[1], {'filter[city][0]': 'Milan', 'page_number': 2})

    def test_marriott_ignored_page_retains_observed_roles_without_verification(self):
        pages = [marriott_page([], 2), marriott_page([marjob('11')], 2, 'Milan'),
                 marriott_page([marjob('12')], 2, 'Milan', 1)]
        with patch.object(collector, 'get_html', side_effect=[(p, 'https://careers.marriott.com/jobs') for p in pages]):
            result, _ = collector.collect_company(company('marriott', 'careers.marriott.com'))
        self.assertEqual(result['coverage'], 'PARTIAL')
        self.assertEqual([r['source_id'] for r in result['jobs']], ['11'])

    def test_marriott_wrong_vacancy_city_and_changed_count_never_certify(self):
        for last in (marriott_page([marjob('12')], 3, 'Milan', 2),
                     marriott_page([{**marjob('12'), 'locations': [{'city': 'Paris'}]}], 2, 'Milan', 2)):
            pages = [marriott_page([], 2), marriott_page([marjob('11')], 2, 'Milan'), last]
            with self.subTest(last=last), patch.object(collector, 'get_html', side_effect=[(p, 'https://careers.marriott.com/jobs') for p in pages]):
                result, _ = collector.collect_company(company('marriott', 'careers.marriott.com'))
                self.assertEqual(result['coverage'], 'PARTIAL')
                self.assertEqual(len(result['jobs']), 1)


class RenderedInventoryTests(unittest.TestCase):
    def collect(self, layout, source):
        host = official.HTML_HOSTS[layout]
        row = company('rendered', host, rendered_layout=layout)
        with patch.object(collector, 'get_html', return_value=(source, row['ats']['inventory_url'])):
            return collector.collect_company(row)[0]

    def test_rendered_level_uses_card_location_ignoring_css_and_footer(self):
        source = '''<div class="Card__careers--new" id="11"><h3>Business Analyst</h3>
        <a href="/job-description/11/business-analyst"><span class="careers__careers__payoff--new">
        <style>Milano CSS</style>Paris</span></a></div><footer>Milano</footer>
        <div class="Card__careers--new" id="12"><h3>Business Analyst</h3>
        <a href="/job-description/12/business-analyst"><span class="careers__careers__payoff--new">Milan</span></a></div>'''
        result = self.collect('level', source)
        self.assertEqual(result['coverage'], 'PARTIAL')
        self.assertEqual(result['inventory_count'], 2)
        self.assertEqual([j['source_id'] for j in result['jobs']], ['12'])

    def test_missing_local_location_and_official_url_violation_are_isolated(self):
        source = '''<div class="Card__careers--new"><h3>Business Analyst</h3>
        <a href="https://untrusted.example/job-description/11/a"><span class="careers__careers__payoff--new">Milan</span></a></div>
        <div class="Card__careers--new"><h3>Business Analyst</h3><a href="/job-description/12/a">Details</a></div>
        <div class="Card__careers--new"><h3>Business Analyst</h3><a href="/job-description/13/a">
        <span class="careers__careers__payoff--new">Milan</span></a></div><footer>London</footer>'''
        result = self.collect('level', source)
        self.assertEqual(len(result['record_errors']), 2)
        self.assertEqual([j['source_id'] for j in result['jobs']], ['13'])

    def test_all_other_rendered_layouts_use_explicit_vacancy_fields(self):
        fixtures = {
            'lutech': '<tr><td data-href="/careers/details?slug=analyst-11">Analyst</td><td>Junior</td><td>Ibrido</td><td>Milano</td><td>Finance</td></tr>',
            'prelios': '<div class="phoOffer"><h4 class="offTitle">Analyst</h4><div class="profSummRow"><div class="lbl">Città</div><div class="val">Roma</div></div><a class="offLink" href="https://prelios.peoplehr.net/Pages/JobBoard/Job.aspx?v=05b2f0bd-39a4-4556-9c18-33bae3fd2b69">Apply</a></div>',
            'altamira_lactalis': '<tr class="GRID_DAT_ROW_Alter"><td data-title="Titolo"><a href="/jobs/analyst-11.htm">Analyst</a></td><td data-title="Sedi">Milano (MI)</td><td data-title="Funzione">Finance</td></tr>',
            'intervieweb_lechler': '<div class="vacancy__render"><div class="vacancy__title"><a href="/lechler/jobs/analyst-11/en/"><h3>Analyst</h3></a></div><span title="Location"><span class="sr-only">Location</span>London</span></div>',
            'marktlink': '<a href="/vacancies/analyst" title="Analyst"><div class="tags"><span>Milan</span><span>Finance</span><span>Full-time</span></div></a>',
        }
        for layout, source in fixtures.items():
            with self.subTest(layout=layout):
                result = self.collect(layout, source)
                self.assertEqual(result['coverage'], 'PARTIAL')
                self.assertEqual(len(result['jobs']), 1)
                self.assertFalse(result.get('record_errors'))

    def test_dispatch_is_opt_in_and_bound_to_official_host(self):
        row = company('tiktok', 'untrusted.example')
        self.assertIsNone(official.choose_official(row))
        row['ats'].pop('official_adapter')
        row['ats']['inventory_url'] = 'https://lifeattiktok.com/search'
        self.assertIsNone(official.choose_official(row))


if __name__ == '__main__':
    unittest.main()
