"""Fetch public announcement bodies and produce conservative, evidence-based triage.
Only explicitly supported vacancy plans are parsed; missing fields remain unknown.
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from collect_jobs import DATA, SOURCES, fetch_page, log, error_kind

from job_attachments import process_attachment, triage

VERSION = 2
VOID = {'br', 'hr', 'img', 'input', 'meta', 'link', 'wbr', 'source', 'embed', 'area', 'base', 'col', 'param', 'track'}
FIELDS = {
    'employment': r'劳务派遣|事业编制|编外|合同制|劳动合同',
    'location': r'工作地点|工作地址|工作所在地',
    'education': r'学历|学位|硕士|博士|本科',
    'major': r'专业要求|相关专业|计算机|软件工程|专业：|专业:',
    'experience': r'工作经验|工作经历|[一二三四五六七八九十\d]+年.*经验',
    'graduate': r'应届|招聘对象|面向社会|社会招聘',
    'deadline': r'截止日期|截止时间|报名时间|报名截止|报名期限|报名日期|报名自|报名.*截至|报名.*截止',
}
TECH_PATTERN = re.compile(r'C\+\+|(?<![A-Za-z])Qt(?![A-Za-z])|\bOCCT\b|\bOpenGL\b|\bCAD\b|三维|工业软件|软件开发|软件工程|计算机', re.I)


class ArticleParser(HTMLParser):
    """Only read a known article container, never navigation or metadata."""
    def __init__(self, container_class="wp_articlecontent"):
        super().__init__()
        self.container_class = container_class
        self.depth = 0
        self.active = False
        self.parts = []
        self.links = []
        self.link = None
        self.skip = 0
        self.table_rows = []
        self.row = None
        self.cell = None
        self.image_count = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        if not self.active:
            if tag == 'div' and self.container_class in classes:
                self.active = True
                self.depth = 1
            return
        if tag == 'tr': self.row = []
        if tag in ('td', 'th'): self.cell = []
        if tag == 'img': self.image_count += 1
        if tag not in VOID:
            self.depth += 1
        if tag in ('script', 'style'):
            self.skip += 1
        if tag in ('p', 'div', 'br', 'tr', 'li'):
            self.parts.append('\n')
        if tag == 'td': self.parts.append(' | ')
        if tag == 'a': self.link = attrs.get('href')
        if tag == 'img' and attrs.get('alt'): self.parts.append(attrs['alt'])

    def handle_endtag(self, tag):
        if not self.active or tag in VOID: return
        if tag in ('td', 'th') and self.cell is not None:
            if self.row is not None: self.row.append(re.sub(r'\s+', ' ', ''.join(self.cell)).strip())
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.table_rows.append(self.row); self.row = None
        if tag in ('script', 'style'): self.skip = max(0, self.skip - 1)
        if tag in ('p', 'div', 'tr', 'li'): self.parts.append('\n')
        if tag == 'a': self.link = None
        self.depth -= 1
        if self.depth == 0: self.active = False

    def handle_data(self, data):
        if self.active and not self.skip:
            self.parts.append(data)
            if self.cell is not None: self.cell.append(data)
            if self.link: self.links.append((self.link, data.strip()))

    def text(self):
        return '\n'.join(line for raw in ''.join(self.parts).splitlines()
                         if (line := re.sub(r'\s+', ' ', raw).strip()))


def classify(title):
    if re.search(r'拟录用|拟聘|考察|公示', title): return '录用公示/考察'
    if re.search(r'考试|笔试|面试|成绩|资格审查', title): return '考试/流程通知'
    if '校内招聘' in title: return '校内招聘'
    if re.search(r'招聘|招录|选聘', title): return '招聘公告'
    return '待核实'


def analyze(title, text, url, links=()):
    category = classify(title)
    evidence = {}
    lines = text.splitlines()
    for field, pattern in FIELDS.items():
        hits = [line[:500] for line in lines if re.search(pattern, line)]
        evidence[field] = [{'text': line, 'url': url} for line in hits[:5]]
    evidence['technical'] = [{'text': line[:500], 'url': url} for line in lines if TECH_PATTERN.search(line)][:5]
    tech = list(dict.fromkeys(m.group() for m in TECH_PATTERN.finditer(text)))
    # These are announcement-level signals, never proof that a particular role qualifies.
    reasons = []
    verdict = '需要人工核实'
    if category in ('录用公示/考察', '考试/流程通知'):
        verdict = '明确不符合'
        reasons.append('这是招聘流程通知，不是新的岗位报名公告（依据公告标题）')
    elif category == '校内招聘':
        reasons.append('标题标明校内招聘，需确认是否具有校内应聘资格')
    if tech:
        reasons.append('正文出现技术相关词：' + '、'.join(tech) + '；需核对具体岗位')
    else:
        reasons.append('正文未识别到目标技术关键词，不能据此认定岗位不匹配')
    if re.search(r'仅限.*应届|限.*应届|须为.*应届', text):
        reasons.append('正文有应届限制表述，需核对适用岗位；用户应届身份未确认')
    if '博士' in text: reasons.append('正文提到博士；需核对各岗位学历，不能排除整份公告')
    attachments = []
    for href, label in links:
        target = urljoin(url, href)
        if urlsplit(target).scheme not in ('http', 'https'): continue
        if re.search(r'\.(pdf|docx?|xlsx?|zip)(?:[?#]|$)', target, re.I) or '附件' in label:
            item = {'title': label or '附件', 'url': target}
            if item not in attachments: attachments.append(item)
    if attachments or '附件' in text:
        reasons.append('岗位附件尚未解析，学历、专业等条件可能不完整')
    deadline = None
    date_candidates = set()
    for deadline_line in lines:
        if not re.search(FIELDS['deadline'], deadline_line): continue
        # Accept an explicit full date only after a deadline cue. Do not infer years
        # or interpret publication / public-comment dates as application deadlines.
        matches = re.finditer(r'(?:截止|截至|至|[-—~～])[^。；\n\d]{0,15}?(20\d{2})年(\d{1,2})月(\d{1,2})日', deadline_line)
        for match in matches:
            try:
                date_candidates.add(datetime(*map(int, match.groups())).date().isoformat())
            except ValueError:
                pass
    for line in lines:
        if re.search(r'截止日期|截止时间', line):
            for match in re.finditer(r'(?:截止日期|截止时间)\s*[：:]?\s*(20\d{2})-(\d{2})-(\d{2})', line):
                try: date_candidates.add(datetime(*map(int, match.groups())).date().isoformat())
                except ValueError: pass
    if len(date_candidates) == 1 and category == '招聘公告':
        deadline = date_candidates.pop()
    missing = [field for field in FIELDS if not evidence[field]]
    return {'notice_type': category, 'screening': {
        'verdict': verdict, 'reasons': reasons,
        'unknown_fields': missing,
        'scope': '公告级初筛；尚未逐岗位核实，不输出明确符合'},
        'requirements_evidence': evidence, 'technical_keywords': tech,
        'attachments': attachments, 'deadline': deadline}


def body_positions(title, text, url):
    headings = list(re.finditer(r'(?m)^[一二三四五六七八九十]+、([^\n]+)', text))
    records = []
    for i, heading in enumerate(headings):
        name = heading.group(1).strip()
        if not re.search(r'工程师|设计师|助理|技术|研发', name): continue
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[heading.end():end].strip()
        fields = {'name': name, 'requirements': body[:6000]}
        # Explicit degree lines remain original evidence, never inherited from other roles.
        degree = next((line for line in body.splitlines() if re.search(r'硕士|博士|本科', line)), '')
        fields['education'] = degree
        records.append({'url': url, 'section': heading.group(0), 'fields': fields, 'screening': triage(fields)})
    if not records and 'C++' in title and '社会招聘' in title:
        fields = {'name': title, 'requirements': text[:6000]}
        records.append({'url': url, 'section': '官方职位详情', 'fields': fields, 'screening': triage(fields)})
    return records


def table_positions(rows, url):
    headers = None
    result = []
    aliases = {'岗位名称': 'name', '资格条件': 'requirements', '任职要求': 'requirements', '工作地点': 'location', '学历': 'education', '部门名称': 'department', '单位名称': 'employer', '招聘类型': 'recruitment_type'}
    for index, row in enumerate(rows):
        if '岗位名称' in row and any(x in row for x in ('资格条件', '任职要求')):
            headers = {i: aliases[v] for i, v in enumerate(row) if v in aliases}
            continue
        if not headers: continue
        if len(row) <= max(headers): continue  # No guessing through unsupported merged rows.
        fields = {key: row[i] for i, key in headers.items()}
        if not fields.get('name'): continue
        if not fields.get('education'):
            fields['education'] = next((part for part in re.split(r'[。；]', fields.get('requirements', '')) if re.search(r'硕士|博士|本科', part)), '')
        result.append({'url': url, 'section': '正文岗位表第 ' + str(index + 1) + ' 行', 'fields': fields, 'screening': triage(fields)})
    return result


def enrich(item, source=None):
    html, final_url = fetch_page({'id': item['id'], 'url': item['url']})
    if urlsplit(final_url).hostname != urlsplit(item['url']).hostname or '/login' in urlsplit(final_url).path:
        raise ValueError('Redirected outside official article host or to login; authentication not attempted')
    parser = ArticleParser((source or {}).get("article_class", "wp_articlecontent"))
    parser.feed(html)
    text = parser.text()
    if len(text) < 40:
        raise ValueError('No usable article body in known container; possible layout change or access restriction')
    result = analyze(item['title'], text, final_url, parser.links)
    result['attachments'] = [process_attachment(a, final_url) for a in result['attachments']]
    result['body_positions'] = body_positions(item['title'], text, final_url)
    table_roles = table_positions(parser.table_rows, final_url)
    if table_roles: result['body_positions'] = table_roles
    if (source or {}).get('single_position'):
        fields = {'name': item['title'], 'requirements': text[:6000],
                  'education': next((line for line in text.splitlines() if re.search(r'硕士|博士|本科', line)), '')}
        result['body_positions'] = [{'url': final_url, 'section': '官方单岗位详情', 'fields': fields, 'screening': triage(fields)}]
        result['notice_type'] = '招聘公告'
        # Single-position pages can use job names without 招聘 in their titles.
        if result['deadline'] is None:
            result['deadline'] = analyze('招聘公告', text, final_url)['deadline']
    result['conditions_status'] = 'parsed_roles' if result['body_positions'] else 'images_require_review' if parser.image_count else 'body_evidence_only'
    if any(a.get('status') == 'ok' for a in result['attachments']):
        result['screening']['reasons'] = [r for r in result['screening']['reasons'] if not r.startswith('岗位附件尚未解析')]
        result['screening']['reasons'].append('已解析支持的岗位表，逐行结果见附件；仍需核实公告时效和其他资格')
    listed_deadline = item.get('listing', {}).get('deadline')
    if listed_deadline and re.fullmatch(r'20\d{2}-\d{2}-\d{2}(?: 00:00:00)?', listed_deadline):
        value = listed_deadline[:10]
        datetime.strptime(value, '%Y-%m-%d')
        result['requirements_evidence']['deadline'].append({'text': '官网列表截止时间：' + listed_deadline, 'url': (source or {}).get('url', final_url)})
        if result['deadline'] is None: result['deadline'] = value
        elif result['deadline'] != value:
            result['deadline_conflict'] = {'body': result['deadline'], 'list': value}
            result['deadline'] = min(result['deadline'], value)  # conservative display; do not assert open
    result['detail'] = {'run_id': os.environ.get('JOBRADAR_RUN_ID'), 'status': 'ok', 'url': final_url, 'characters': len(text),
                        'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                        'rule_version': VERSION}
    return result


def main(data_path=DATA, sources_path=SOURCES):
    data_path = Path(data_path)
    data = json.loads(data_path.read_text(encoding='utf-8'))
    sources = {s['id']: s for s in json.loads(Path(sources_path).read_text(encoding='utf-8'))['sources']}
    ok, failures = 0, []
    attachment_failures = []
    for item in data['jobs']:
        try:
            source = sources[item['source_id']]
            if not source.get('enabled', True): continue
            pattern = source.get('include_url_pattern')
            if not pattern or not re.search(pattern, item['url']):
                raise ValueError('Detail URL is outside configured official article pattern')
            failed_sources = {f['source'] for f in data.get('sources_failed', [])}
            if source['id'] in failed_sources:
                raise ValueError('Source list failed this batch; detail not re-requested, previous evidence is stale')
            if item.get('last_seen') != data.get('updated_at') and data.get('run_id'):
                raise ValueError('Not observed in this batch list window; detail not re-requested')
            item.update(enrich(item, source))
            attachment_failures.extend({'id': item['id'], 'url': a['url'], 'error': a['error']}
                                       for a in item.get('attachments', []) if a.get('status') == 'failed')
            ok += 1
            log('detail_complete', id=item['id'], notice_type=item['notice_type'], verdict=item['screening']['verdict'])
        except Exception as exc:
            # Never display old positive conclusions as a freshly verified result.
            item['body_positions'] = []
            item['attachments'] = [{k: a[k] for k in ('url', 'title') if k in a} for a in item.get('attachments', [])]
            item['notice_type'] = classify(item.get('title', ''))
            item['detail'] = {'status': 'failed', 'error': str(exc)[:250],
                              'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
            item['screening'] = {'verdict': '需要人工核实', 'reasons': ['本次正文获取失败，旧证据可能过时'], 'unknown_fields': list(FIELDS)}
            failures.append({'id': item['id'], 'error': str(exc)[:250], 'kind': error_kind(exc)})
            log('detail_failed', **failures[-1])
        time.sleep(0.5)
    data['attachment_failures'] = attachment_failures
    data['details_summary'] = {'ok': ok, 'failed': failures,
                               'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    temporary = data_path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, data_path)
    log('enrichment_complete', ok=ok, failed=len(failures), attachments_failed=len(attachment_failures))
    if failures or attachment_failures or not ok: raise SystemExit(1)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DATA)); parser.add_argument("--sources", default=str(SOURCES))
    args = parser.parse_args()
    main(args.data, args.sources)
