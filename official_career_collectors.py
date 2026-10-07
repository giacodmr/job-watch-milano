"""Opt-in adapters for evidenced public employer listings.

Rendered subsets remain PARTIAL. Counted feeds certify only the scope they
actually enumerate; a working page never proves vacancy absence by itself.
"""
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qs, urljoin, urlparse


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def find(self, tag=None, cls=None, prefix=None, **attrs):
        found = []
        for child in self.children:
            if not isinstance(child, Node):
                continue
            classes = child.attrs.get('class', '').split()
            if ((tag is None or child.tag == tag)
                    and (cls is None or cls in classes)
                    and (prefix is None or any(c.startswith(prefix) for c in classes))
                    and all(child.attrs.get(k) == v for k, v in attrs.items())):
                found.append(child)
            found.extend(child.find(tag, cls, prefix, **attrs))
        return found

    def text(self):
        if self.tag in ('script', 'style', 'svg') or 'sr-only' in self.attrs.get('class', '').split():
            return ''
        return ' '.join(' '.join(c.text() if isinstance(c, Node) else c
                                 for c in self.children).split())


class Document(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def first(nodes):
    if not nodes:
        raise ValueError('Required vacancy field absent')
    return nodes[0]


def trusted_url(base, value, hosts=None):
    url = urljoin(base, value or '')
    p = urlparse(url)
    allowed = hosts or {urlparse(base).hostname}
    if not value or p.scheme != 'https' or p.hostname not in allowed or p.username or p.password:
        raise ValueError('Vacancy URL outside the evidenced official source')
    return url


def normalize(company, raw, jobs):
    import collector as c
    try:
        if not all(raw.get(k) for k in ('source_id', 'title', 'location', 'canonical')):
            raise ValueError('Vacancy identifier/title/location/URL absent')
        job = c.compact_job(company['company'], **raw)
        if c.location_matches(job['location'], company['company']):
            jobs[job['source_id']] = job
    except Exception as exc:
        c.normalization_error(company, exc, raw)


HTML_HOSTS = {
    'level': 'www.thelevelgroup.com', 'lutech': 'lutech.group',
    'prelios': 'prelios.com', 'altamira_lactalis': 'jobs.lactalisvaloreitalia.it',
    'intervieweb_lechler': 'zinrec.intervieweb.it', 'marktlink': 'careers.marktlink.com',
}


def rendered_rows(root, layout, base):
    """Use vacancy-local fields, never footer addresses or description cities."""
    if layout == 'level':
        cards = root.find('div', prefix='Card__careers--')
    elif layout == 'lutech':
        cards = [n for n in root.find('tr') if n.find('td') and n.find('td')[0].attrs.get('data-href')]
    elif layout == 'prelios':
        cards = root.find('div', cls='phoOffer')
    elif layout == 'altamira_lactalis':
        cards = root.find('tr', prefix='GRID_DAT_ROW')
    elif layout == 'intervieweb_lechler':
        cards = root.find('div', cls='vacancy__render')
    else:
        cards = [n for n in root.find('a') if n.attrs.get('title') and n.find('div', cls='tags')
                 and urlparse(urljoin(base, n.attrs.get('href', ''))).path.startswith('/vacancies/')]
    for card in cards:
        try:
            department = employment = None
            if layout == 'level':
                title = first(card.find('h3')).text()
                location = first(card.find('span', prefix='careers__careers__payoff--')).text()
                url = trusted_url(base, first(card.find('a')).attrs.get('href'))
                sid = re.fullmatch(r'/job-description/(\d+)/[^/]+/?', urlparse(url).path).group(1)
            elif layout == 'lutech':
                cells = card.find('td')
                title, location, department = cells[0].text(), cells[3].text(), cells[4].text()
                url = trusted_url(base, cells[0].attrs['data-href'])
                sid = re.search(r'-(\d+)$', parse_qs(urlparse(url).query)['slug'][0]).group(1)
            elif layout == 'prelios':
                title = first(card.find('h4', cls='offTitle')).text()
                fields = {first(n.find(cls='lbl')).text(): first(n.find(cls='val')).text()
                          for n in card.find(cls='profSummRow')}
                location, department = fields.get('Città'), fields.get('Dipartimento')
                url = trusted_url(base, first(card.find('a', cls='offLink')).attrs.get('href'), {'prelios.peoplehr.net'})
                sid = parse_qs(urlparse(url).query)['v'][0]
                if not re.fullmatch(r'[0-9a-fA-F-]{36}', sid):
                    raise ValueError('Invalid PeopleHR vacancy identifier')
            elif layout == 'altamira_lactalis':
                fields = {n.attrs.get('data-title', '').strip(): n for n in card.find('td')}
                link = first(fields['Titolo'].find('a'))
                title, location = link.text(), fields['Sedi'].text()
                department = fields['Funzione'].text()
                url = trusted_url(base, link.attrs.get('href'))
                sid = re.search(r'-(\d+)\.htm$', urlparse(url).path).group(1)
            elif layout == 'intervieweb_lechler':
                title_node = first(card.find('div', cls='vacancy__title'))
                title = first(title_node.find('h3')).text()
                location = first(card.find('span', title='Location')).text()
                url = trusted_url(base, first(title_node.find('a')).attrs.get('href'))
                sid = re.search(r'/lechler/jobs/[^/]+-(\d+)/', urlparse(url).path).group(1)
            else:
                title = card.attrs['title']
                tags = first(card.find('div', cls='tags')).find('span')
                location = tags[0].text()
                department = tags[1].text() if len(tags) > 1 else None
                employment = tags[2].text() if len(tags) > 2 else None
                url = trusted_url(base, card.attrs.get('href'))
                sid = urlparse(url).path.rstrip('/').split('/')[-1]
            yield dict(source_id=sid, title=title, location=location, department=department,
                       employment_type=employment, canonical=url, apply_url=url)
        except Exception as exc:
            yield {'error': str(exc)}


def collect_rendered(company):
    import collector as c
    ats = company['ats']
    layout, url = ats['rendered_layout'], ats['inventory_url']
    if urlparse(url).hostname != HTML_HOSTS.get(layout):
        raise c.NotCheckable('Rendered layout and official inventory host disagree')
    source, final = c.get_html(url)
    trusted_url(url, final)
    jobs, seen = {}, set()
    for raw in rendered_rows(Document(source).root, layout, final):
        if 'error' in raw:
            c.normalization_error(company, ValueError(raw['error']), raw)
            continue
        seen.add(raw['source_id'])
        normalize(company, raw, jobs)
    return {'coverage': 'PARTIAL', 'collector': 'official_rendered_vacancies',
            'inventory_count': len(seen), 'jobs': list(jobs.values()), 'source_url': final,
            'reason': 'Observed official vacancies collected; exhaustive count/pagination not certified'}


def positive_count(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('Missing or invalid independent vacancy count')
    return value


def collect_tiktok(company):
    import collector as c
    endpoint = 'https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts'
    headers = {'website-path': 'tiktok', 'Origin': 'https://lifeattiktok.com', 'Accept-Language': 'en-US'}
    jobs, seen, total, offset = {}, set(), None, 0
    for _ in range(c.MAX_PAGES):
        payload = {'keyword': '', 'limit': 100, 'offset': offset,
                   'job_category_id_list': [], 'location_code_list': [],
                   'recruitment_id_list': [], 'subject_id_list': [], 'tag_id_list': []}
        response = c.post_json(endpoint, payload, headers=headers)
        if response.get('code') != 0:
            raise c.NotCheckable('TikTok public search returned an application error')
        data = response['data']
        count = positive_count(data.get('count'))
        if total is not None and count != total:
            raise c.NotCheckable('TikTok count changed during pagination')
        total = count
        rows = data['job_post_list']
        if not isinstance(rows, list) or len(rows) > 100:
            raise c.NotCheckable('Unexpected TikTok page')
        for item in rows:
            sid = str(item.get('id') or '')
            if not re.fullmatch(r'\d+', sid) or sid in seen:
                raise c.NotCheckable('TikTok missing/repeated vacancy identifier')
            seen.add(sid)
            city = item.get('city_info') or {}
            category = item.get('job_category') or {}
            normalize(company, {'source_id': sid, 'title': item.get('title'),
                      'location': city.get('en_name') or city.get('i18n_name'),
                      'department': category.get('en_name'),
                      'canonical': f'https://lifeattiktok.com/search/{sid}'}, jobs)
        if len(seen) == total:
            return {'coverage': 'VERIFIED', 'collector': 'tiktok_public_search',
                    'inventory_count': total, 'jobs': list(jobs.values()), 'source_url': endpoint}
        if not rows or len(seen) > total:
            raise c.NotCheckable('TikTok pagination/count mismatch')
        offset += len(rows)
    raise c.NotCheckable('TikTok pagination safety limit')


def collect_axa(company):
    import collector as c
    endpoint = 'https://jobs.axa.com/api/jobs'
    jobs, seen, count, global_count = {}, set(), None, None
    for page in range(1, c.MAX_PAGES + 1):
        data = c.get_json(endpoint, {'page': page, 'limit': 100, 'internal': 'false'})
        reported, global_reported = positive_count(data.get('count')), positive_count(data.get('totalCount'))
        language_counts = data.get('languageCounts') or {}
        if not language_counts or sum(positive_count(v.get('count')) for v in language_counts.values()) != global_reported:
            raise c.NotCheckable('AXA global total and language counts do not reconcile')
        if count is not None and (count, global_count) != (reported, global_reported):
            raise c.NotCheckable('AXA counts changed during pagination')
        count, global_count = reported, global_reported
        rows = data['jobs']
        if not isinstance(rows, list) or len(rows) > 100:
            raise c.NotCheckable('Unexpected AXA page')
        for item in rows:
            raw = item['data']
            sid = str(raw.get('req_id') or '')
            if not re.fullmatch(r'\d+', sid) or sid in seen:
                raise c.NotCheckable('AXA missing/repeated vacancy identifier')
            seen.add(sid)
            try:
                url = trusted_url(endpoint, f"/jobs/{raw['slug']}?lang={raw['language']}")
                normalize(company, {'source_id': sid, 'title': raw.get('title'),
                          'location': raw.get('city'), 'department': ' | '.join(v['name'] for v in raw.get('categories', [])),
                          'employment_type': raw.get('employment_type'), 'published_at': raw.get('posted_date'),
                          'updated_at': raw.get('update_date'), 'canonical': url,
                          'apply_url': trusted_url(endpoint, raw.get('apply_url'), {
                              'jobs.axa.com', 'candidature-recrutement.axa.fr',
                              *('careers-' + locale + '-axa.icims.com'
                                for locale in ('en', 'de', 'fr', 'es', 'it', 'ja', 'pt', 'tr', 'dei-en'))})}, jobs)
            except Exception as exc:
                c.normalization_error(company, exc, {'source_id': sid})
        if len(seen) == global_count:
            # `count` is the English facet count even though unfiltered pages
            # include every language. totalCount and languageCounts independently
            # describe the returned global inventory, confirmed through its end.
            return {'coverage': 'VERIFIED', 'collector': 'axa_jibe_public_search',
                    'inventory_count': global_count, 'api_locale_count': count,
                    'jobs': list(jobs.values()), 'source_url': endpoint,
                    'reason': None}
        if not rows or len(seen) > global_count:
            raise c.NotCheckable('AXA pagination/count mismatch')
    raise c.NotCheckable('AXA pagination safety limit')


def preload_state(source):
    marker = 'window.__PRELOAD_STATE__ = '
    start = source.find(marker)
    if start < 0:
        raise ValueError('Official Paradox listing state absent')
    return json.JSONDecoder().raw_decode(source[start + len(marker):])[0]['jobSearch']


def collect_marriott(company):
    import collector as c
    url = 'https://careers.marriott.com/jobs'
    source, final = c.get_html(url)
    trusted_url(url, final)
    state = preload_state(source)
    if state.get('params', {}).get('filter'):
        raise c.NotCheckable('Unexpected filter on Marriott discovery inventory')
    city_facet = next(f for f in state['facets'] if f['field'] == 'city')
    cities = sorted({v['original_value'] for v in city_facet['facet_field_keyvalue']
                     if c.location_matches(v['original_value'])})
    if not cities:
        raise c.NotCheckable('Target-city facets absent; no vacancy-absence certification')
    jobs, all_seen, counts = {}, set(), {}
    for city in cities:
        seen, total = set(), None
        for page in range(1, c.MAX_PAGES + 1):
            source, final = c.get_html(url, {'filter[city][0]': city, 'page_number': page})
            trusted_url(url, final)
            state = preload_state(source)
            params = state.get('params') or {}
            if params.get('filter') != {'city': [city]} or params.get('page_number', 1) != page:
                raise c.NotCheckable('Marriott ignored requested city/page')
            count = positive_count(state.get('totalJob'))
            if total is not None and total != count:
                raise c.NotCheckable('Marriott count changed during pagination')
            total = count
            rows = state['jobs']
            if not isinstance(rows, list):
                raise c.NotCheckable('Unexpected Marriott page')
            for raw in rows:
                sid = str(raw.get('requisitionID') or '')
                if not sid or sid in seen:
                    raise c.NotCheckable('Marriott missing/repeated vacancy identifier')
                seen.add(sid)
                all_seen.add(sid)
                locations = raw.get('locations') or []
                if not locations or not any(v.get('city') == city for v in locations):
                    raise c.NotCheckable('Marriott city filter disagrees with vacancy locations')
                try:
                    canonical = trusted_url(url, '/' + raw['originalURL'].lstrip('/'))
                    normalize(company, {'source_id': sid, 'title': raw.get('title'),
                              'location': ' | '.join(', '.join(filter(None, (v.get('city'), v.get('country')))) for v in locations),
                              'employment_type': ' | '.join(raw.get('employmentType') or []),
                              'canonical': canonical, 'apply_url': trusted_url(url, raw.get('applyURL'),
                                {'ejwl.fa.us2.oraclecloud.com', 'careers.marriott.com'})}, jobs)
                except Exception as exc:
                    c.normalization_error(company, exc, {'source_id': sid})
            if len(seen) == total:
                counts[city] = total
                break
            if not rows or len(seen) > total:
                raise c.NotCheckable('Marriott pagination/count mismatch')
        else:
            raise c.NotCheckable('Marriott pagination safety limit')
    return {'coverage': 'VERIFIED', 'collector': 'marriott_paradox_city_inventory',
            'inventory_count': len(all_seen), 'city_counts': counts,
            'jobs': list(jobs.values()), 'source_url': url}


def choose_official(company):
    ats = company.get('ats') or {}
    adapter = ats.get('official_adapter')
    hosts = {'tiktok': 'lifeattiktok.com', 'axa': 'jobs.axa.com', 'marriott': 'careers.marriott.com'}
    if adapter == 'rendered' and ats.get('rendered_layout') in HTML_HOSTS:
        return collect_rendered
    if adapter in hosts and urlparse(ats.get('inventory_url') or '').hostname == hosts[adapter]:
        return {'tiktok': collect_tiktok, 'axa': collect_axa, 'marriott': collect_marriott}[adapter]
    return None
