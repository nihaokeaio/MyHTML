"""Bounded adapters for public list requests present in official page scripts."""
import json
import re
from html import unescape
from urllib.parse import urljoin, urlencode
from collect_jobs import fetch_page, LinkParser, CollectionError


def list_links(source):
    adapter = source['adapter']
    base = source['url']
    links = []
    if adapter == 'xidian':
        # Same read-only POST as /portal/list; no login, applications or private API.
        for page in range(1, source.get('max_pages', 2) + 1):
            text, _ = fetch_page({'id': source['id'], 'url': urljoin(base, '/portal/getpostlist'),
                                  'json': True, 'form': {'page': page, 'rows': 10, 'item1': '', 'item2': '', 'item5': '', 'keyword': ''}})
            data = json.loads(text)
            if data.get('success') is not True or not isinstance(data.get('data'), str):
                raise CollectionError('Official list API did not return a successful HTML list')
            parser = LinkParser(); parser.feed(data['data']); links.extend(parser.links)
            if page >= int(data.get('pageCount', 0)): break
    elif adapter == 'cncico':
        for page in range(1, source.get('max_pages', 2) + 1):
            endpoint = urljoin(base, '/front/content/portalPage') + '?' + urlencode({
                'summary': 'true', 'orderStrs': 'top_level_desc,release_time_desc,id_desc',
                'pageNo': page, 'pageSize': 7, 'channelId': 140})
            text, _ = fetch_page({'id': source['id'], 'url': endpoint, 'json': True})
            data = json.loads(text)
            if data.get('code') != 0 or not isinstance(data.get('data', {}).get('list'), list):
                raise CollectionError('Official list API schema or status changed')
            rows = data['data']['list']
            links.extend((row.get('url') or row.get('dynamicUrl') or '', row['title'], {'deadline': (row.get('customs') or {}).get('deadline'), 'location': (row.get('customs') or {}).get('workLocation'), 'page': page, 'endpoint': endpoint}) for row in rows)
            if page * 7 >= int(data['data'].get('total', 0)): break
    elif adapter == 'nimte_portal':
        html, _ = fetch_page(source)
        class PositionLinks(LinkParser):
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'a':
                    match = re.fullmatch(r'viewPositionInfo\("(\d+)",null\)', attrs.get('onclick', ''))
                    if match:
                        attrs['href'] = '/system/userInfo/positionInfo?' + urlencode({'id': match[1], 'isDelivery': 'null'})
                super().handle_starttag(tag, list(attrs.items()))
        parser = PositionLinks(); parser.feed(html); links = parser.links
    else:
        raise CollectionError('Unsupported public list adapter: ' + adapter)
    return links, base
