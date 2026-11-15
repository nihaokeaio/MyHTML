"""Compare observed, evidence-backed positions; never infer closure from missing pages."""
import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collect_jobs import ROOT, log

REGIONS = re.compile(r'浙江|杭州|宁波|温州|嘉兴|湖州|绍兴|金华|衢州|舟山|台州|丽水')

TECH = re.compile(r'C\+\+|(?<![A-Za-z])Qt(?![A-Za-z])|OCCT|OpenGL|工业软件|三维可视化|三维.*开发|CAD.*(?:开发|研发)|(?:开发|研发).*CAD', re.I)


def atomic_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, path)


def positions(data, fresh=False):
    result = {}
    for job in data.get('jobs', []):
        if job.get('detail', {}).get('status') != 'ok': continue
        if fresh and (job.get('last_seen') != data.get('updated_at') or
                      data.get('run_id') and job.get('detail', {}).get('run_id') != data['run_id']): continue
        rows = job.get('body_positions', []) + [r for a in job.get('attachments', []) if a.get('status') == 'ok' for r in a.get('positions', [])]
        for row in rows:
            fields = row.get('fields', {})
            name = fields.get('name', '').strip()
            if not name: continue
            # Row numbers can move when tables are edited. Use semantic identity instead.
            identity = '\n'.join((job['id'], name, fields.get('department', ''), fields.get('employment', '')))
            key = hashlib.sha256(identity.encode()).hexdigest()[:24]
            candidate = {'id': key, 'notice_id': job['id'], 'title': name, 'source': job['source'],
                         'source_id': job['source_id'], 'official_url': job['url'],
                         'evidence_url': row.get('url', job['url']), 'evidence_section': row.get('section') or {'sheet': row.get('sheet'), 'row': row.get('row')},
                         'deadline': job.get('deadline'), 'notice_type': job.get('notice_type'),
                         'fields': fields, 'verdict': row.get('screening', {}).get('verdict', '需要人工核实')}
            if key in result and result[key]['fields'] != fields:
                # Conflicting duplicate identities cannot be reliably compared as one role.
                result[key]['ambiguous'] = True
            else: result[key] = candidate
    return result


def hide_reason(position, today):
    if position.get('ambiguous'): return '同名岗位条件冲突，需人工核实'
    if position.get('notice_type') in ('录用公示/考察', '考试/流程通知', '校内招聘'): return '非本轮社会招聘目标'
    if position.get('deadline') and position['deadline'] < today: return '明确过期'
    if position.get('verdict') == '明确不符合': return '不符合已知硬性要求'
    if re.search(r'校园招聘|应届毕业生', position['title'] + position['fields'].get('recruitment_type', '')): return '本轮只关注社会招聘'
    location = position['fields'].get('location', '')
    if location and not REGIONS.search(location) and re.search(r'北京|上海|江苏|南京|广东|深圳|广州|武汉|成都|西安|合肥|济南', location): return '明确工作地点不在浙江'
    if not TECH.search('\n'.join(position['fields'].values())): return '无目标技术方向的岗位证据'
    return None


def canonical(value):
    if value is None: return None
    # Whitespace / HTML layout changes are not substantive requirement changes.
    return re.sub(r'\s+', ' ', str(value)).strip()


def public_item(position, old=None):
    item = {k: position[k] for k in ('id', 'notice_id', 'title', 'source', 'official_url', 'evidence_url', 'evidence_section', 'deadline')}
    fields = position['fields']; text = '\n'.join(fields.values())
    item['match_reasons'] = ['岗位原文出现：' + '、'.join(dict.fromkeys(m.group() for m in TECH.finditer(text)))]
    item['confirmed_obstacles'] = []
    item['confirmed_limitations'] = ['用工方式为劳务派遣'] if '劳务派遣' in text else []
    item['unverified_conditions'] = ['工作地点是否在杭州及浙江', '专业是否符合', '具体领域经验是否满足', '年龄及其他身份要求', '实际雇佣主体与单位属性']
    if not position['deadline']: item['unverified_conditions'].append('当前是否仍接受报名及截止时间')
    if not fields.get('education'): item['unverified_conditions'].append('学历要求')
    if '劳务派遣' in text: item['unverified_conditions'].append('是否接受劳务派遣')
    item['evidence'] = [{'field': k, 'text': v, 'url': item['evidence_url']} for k, v in fields.items() if k != 'name' and v]
    item['changes'] = []
    if old:
        for key in sorted(set(old.get('fields', {})) | set(fields)):
            before = old.get('fields', {}).get(key); after = fields.get(key)
            if canonical(before) != canonical(after): item['changes'].append({'field': key, 'before': before, 'after': after})
        if old.get('deadline') != position['deadline']:
            item['changes'].append({'field': 'deadline', 'before': old.get('deadline'), 'after': position['deadline'], 'kind': 'deadline_confirmed' if old.get('deadline') is None else 'deadline_changed' if position['deadline'] else 'deadline_unknown'})
    return item


def build_summary(previous, current, observed=None, stage_codes=None, today=None):
    today = today or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    baseline = positions(previous)
    baseline.update(observed or {})
    now_positions = positions(current, fresh=True)
    added, changed, deadlines, hidden, suppressed = [], [], [], [], []
    for key, position in now_positions.items():
        old = baseline.get(key)
        reason = hide_reason(position, today)
        if reason:
            hidden.append({'id': key, 'title': position['title'], 'reason': reason})
            if old and not hide_reason(old, today):
                item = public_item(position, old)
                if item['changes']:
                    item['hidden_reason'] = reason; suppressed.append(item)
            continue
        old = baseline.get(key)
        item = public_item(position, old)
        if old is None:
            item['discovery_note'] = '首次采集或首次成功解析；不代表今天发布'
            added.append(item)
        elif item['changes'] or hide_reason(old, today):
            if hide_reason(old, today): item['changes'].append({'field': 'screening', 'before': hide_reason(old, today), 'after': '重点候选（仍待核实）'})
            changed.append(item)
            if any(c.get('kind') == 'deadline_changed' for c in item['changes']): deadlines.append(item['id'])
    # Preserve last successfully observed conditions across a failed batch; never re-notify
    # an old role as new just because the immediately preceding run could not read it.
    baseline.update(now_positions)
    codes = stage_codes or {}
    failures = current.get('sources_failed', [])
    detail_failures = current.get('details_summary', {}).get('failed', [])
    attachments = current.get('attachment_failures', [])
    health = 'partial_failure' if failures or detail_failures or attachments or any(codes.values()) or current.get('sources_ok', 0) < 1 or current.get('details_summary', {}).get('ok', 0) < 1 else 'ok'
    summary = {'schema_version': 1, 'run_id': current.get('run_id'), 'updated_at': current.get('updated_at'),
               'previous_run_at': previous.get('updated_at'), 'comparison_date': today,
               'status': health, 'stage_exit_codes': codes,
               'message': '本次无新增重点候选' if not added else f'本次新增 {len(added)} 个重点候选（待核实）',
               'change_message': f'结构化证据变化 {len(changed)} 个，已知截止时间变化 {len(deadlines)} 个（首次提取期限另列）',
               'new_positions': added, 'changed_positions': changed, 'deadline_changed_ids': deadlines,
               'hidden_positions': hidden, 'suppressed_changes': suppressed,
               'health': {'sources_ok': current.get('sources_ok', 0), 'sources_failed': failures,
                          'details_failed': detail_failures, 'attachments_failed': attachments},
               'limitations': ['只比较本次列表发现且正文成功的岗位；缺席不代表岗位关闭。',
                              '未知条件不当作满足；摘要候选不代表已确认可以投递。',
                              '栏目按配置限页，未宣称覆盖全站。', '结构化证据变化可能包含首次提取或解析改善，不能据此声称官方修订。']}
    return summary, baseline


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--previous', required=True); parser.add_argument('--current', default=str(ROOT/'jobradar/jobs.json'))
    parser.add_argument('--output', default=str(ROOT/'jobradar/daily-summary.json'))
    args = parser.parse_args()
    before = json.loads(Path(args.previous).read_text(encoding='utf-8'))
    after = json.loads(Path(args.current).read_text(encoding='utf-8'))
    summary, _ = build_summary(before, after)
    atomic_json(args.output, summary)
    log('summary_complete', new=len(summary['new_positions']), changed=len(summary['changed_positions']), status=summary['status'])
