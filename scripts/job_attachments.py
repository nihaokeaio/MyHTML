"""Read official XLS recruitment plans, preserving merged cells and row provenance."""
import hashlib
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MAX_BYTES = 5_000_000
HEADERS = {
    'name': ('岗位名称',), 'department': ('学院（系）/单位', '招聘单位', '部门'),
    'employment': ('岗位类型',), 'education': ('学历/学位', '学历', '学位'),
    'major': ('专业',), 'age': ('年龄',), 'requirements': ('其他条件',),
    'responsibilities': ('岗位职责描述', '岗位职责'), 'count': ('计划招聘人数', '招聘人数'),
}


def clean(value):
    if isinstance(value, float) and value.is_integer(): return str(int(value))
    return str(value).strip()


def sheet_records(sheet):
    if sheet.nrows > 5000 or sheet.ncols > 100:
        raise ValueError('Worksheet exceeds row/column limits')
    rows = [[clean(v) for v in sheet.row_values(r)] for r in range(sheet.nrows)]
    # Propagate only real Excel merges, never arbitrary blank cells.
    for r0, r1, c0, c1 in sheet.merged_cells:
        for r in range(r0, r1):
            for c in range(c0, c1): rows[r][c] = rows[r0][c0]
    header = next((r for r, values in enumerate(rows[:20])
                   if '岗位名称' in values and '序号' in values), None)
    if header is None: return []
    last_header = header
    if header + 1 < len(rows) and any(x in rows[header + 1] for x in ('年龄', '学历/学位', '其他条件')):
        last_header += 1
    columns = {}
    for c in range(sheet.ncols):
        labels = [re.sub(r'\s+', '', rows[r][c]) for r in range(header, last_header + 1)]
        for field, aliases in HEADERS.items():
            if any(label == alias or label.startswith(alias + '（') or label.startswith(alias + '(')
                   for alias in aliases for label in labels):
                if field in columns and columns[field] != c:
                    raise ValueError('Ambiguous column: ' + field)
                columns[field] = c
    if 'name' not in columns or 'education' not in columns:
        raise ValueError('Missing required position or education column')
    seq = rows[header].index('序号')
    result = []
    for r in range(last_header + 1, len(rows)):
        if not re.fullmatch(r'\d+', rows[r][seq]): continue
        fields = {field: rows[r][c] for field, c in columns.items()}
        if not fields['name']: raise ValueError('Position row without name')
        result.append({'sheet': sheet.name, 'row': r + 1, 'fields': fields})
    return result


def triage(fields):
    education = fields.get('education', '')
    text = '\n'.join(fields.values())
    reasons = []
    verdict = '需要人工核实'
    priority = '普通核实'
    if '博士' in education and not re.search(r'硕士|本科|不限|或|优先', education):
        verdict = '明确不符合'
        reasons.append('本行学历要求为博士，与已知硕士学历不符')
    else:
        if re.search(r'C\+\+|(?<![A-Za-z])Qt(?![A-Za-z])|OpenGL|OCCT|工业软件', text, re.I):
            priority = '优先核实'
            reasons.append('本岗位行出现目标技术栈，需核实具体职责与资格')
        reasons.append('专业、年龄、身份及具体经验尚未全部核实，不判定明确符合')
    return {'verdict': verdict, 'priority': priority, 'reasons': reasons}


def parse_xls(content, url):
    if not content.startswith(bytes.fromhex('D0CF11E0A1B11AE1')):
        raise ValueError('Not an OLE XLS file (possibly HTML access page)')
    import xlrd
    workbook = xlrd.open_workbook(file_contents=content, formatting_info=True, on_demand=True)
    try:
        records = [record for sheet in workbook.sheets() for record in sheet_records(sheet)]
    finally:
        workbook.release_resources()
    if not records: raise ValueError('No supported recruitment plan rows')
    for record in records:
        record['url'] = url
        record['screening'] = triage(record['fields'])
    return records


def process_attachment(attachment, article_url):
    result = dict(attachment)
    title = result['title']
    # Forms contain no authoritative vacancy rows and are not downloaded.
    if re.search(r'报名表|申请表|登记表|简历|履历', title):
        return {**result, 'status': 'skipped', 'reason': '报名材料，不是岗位计划表'}
    if not re.search(r'岗位|计划|需求|职位', title):
        return {**result, 'status': 'skipped', 'reason': '未识别为岗位计划表，需人工查看'}
    try:
        if urlsplit(result['url']).hostname != urlsplit(article_url).hostname:
            raise ValueError('Attachment host differs from official article host')
        if not urlsplit(result['url']).path.lower().endswith('.xls'):
            raise ValueError('Only legacy XLS recruitment plans are supported currently')
        req = Request(result['url'], headers={'User-Agent': 'JobRadar/0.1 (+personal public recruitment monitor)'})
        with urlopen(req, timeout=12) as response:
            if urlsplit(response.url).hostname != urlsplit(article_url).hostname or '/login' in response.url:
                raise ValueError('Attachment redirected to another host or login')
            content = response.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES: raise ValueError('Attachment exceeds 5 MB')
        positions = parse_xls(content, result['url'])
        return {**result, 'status': 'ok', 'sha256': hashlib.sha256(content).hexdigest(), 'positions': positions}
    except Exception as exc:
        return {**result, 'status': 'failed', 'error': str(exc)[:250]}
