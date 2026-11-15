import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import enrich_jobs as e

class DetailTests(unittest.TestCase):
    def test_only_article_excludes_navigation_and_script(self):
        p=e.ArticleParser()
        p.feed('<nav>博士应届</nav><div class="wp_articlecontent"><p>软件<span>开发</span><br>硕士</p><script>伪正文</script><p>经验不限</p></div><footer>博士</footer>')
        self.assertEqual(p.text(), '软件开发\n硕士\n经验不限')

    def test_missing_and_multi_role_do_not_qualify_or_exclude(self):
        a=e.analyze('公开招聘','岗位一：博士；岗位二：硕士，软件工程；附件详见岗位表。','https://example.com/a')
        self.assertEqual(a['screening']['verdict'],'需要人工核实')
        self.assertIsNone(a['deadline'])
        self.assertEqual(a['requirements_evidence']['education'][0]['url'],'https://example.com/a')
        self.assertEqual(a['requirements_evidence']['location'],[])

    def test_publication_and_publicity_dates_are_not_deadlines(self):
        a=e.analyze('拟录用公示','公示期至2026年11月18日。','https://example.com')
        self.assertEqual(a['notice_type'],'录用公示/考察')
        self.assertEqual(a['screening']['verdict'],'明确不符合')
        self.assertIsNone(a['deadline'])

    def test_explicit_deadline_and_attachment(self):
        a=e.analyze('公开招聘','报名时间：即日起至2026年11月30日。','https://example.com/news/a', [('../plan.xlsx','岗位表')])
        self.assertEqual(a['deadline'],'2026-11-30')
        self.assertEqual(a['attachments'][0]['url'],'https://example.com/plan.xlsx')

    def test_ambiguous_deadlines_are_unknown(self):
        a=e.analyze('公开招聘','岗位一报名截止2026年11月1日。\n岗位二报名截止2026年12月1日。','https://example.com')
        self.assertIsNone(a['deadline'])

    def test_login_redirect_fails(self):
        with patch.object(e,'fetch_page',return_value=('<div class="wp_articlecontent">'+'x'*80+'</div>','https://login.example.com/login')):
            with self.assertRaisesRegex(ValueError,'login'):
                e.enrich({'id':'x','title':'招聘','url':'https://example.com/a'})

    def test_partial_failure_preserves_jobs_and_invalidates_stale_verdict(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)/'jobs.json'; sources=Path(folder)/'sources.json'
            data.write_text(json.dumps({'jobs':[{'id':str(i),'source_id':'s','url':'https://example.com/a','screening':{'verdict':'明确符合'}} for i in range(2)],'sources_failed':[{'source':'blocked'}]}),encoding='utf-8')
            sources.write_text(json.dumps({'sources':[{'id':'s','include_url_pattern':'^https://example.com/'}]}),encoding='utf-8')
            with patch.object(e,'enrich',side_effect=[ValueError('blocked'),{'detail':{'status':'ok'},'notice_type':'招聘公告','screening':{'verdict':'需要人工核实'}}]),patch.object(e.time,'sleep'):
                with self.assertRaises(SystemExit):e.main(data,sources)
            result=json.loads(data.read_text(encoding='utf-8'))
            self.assertEqual(len(result['jobs']),2)
            self.assertEqual(result['jobs'][0]['screening']['verdict'],'需要人工核实')
            self.assertEqual(result['jobs'][1]['detail']['status'],'ok')
            self.assertEqual(result['sources_failed'],[{'source':'blocked'}])

    def test_attachment_failure_keeps_body_and_fails_run(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)/'jobs.json'; sources=Path(folder)/'sources.json'
            data.write_text(json.dumps({'jobs':[{'id':'x','source_id':'s','url':'https://example.com/a'}]}),encoding='utf-8')
            sources.write_text(json.dumps({'sources':[{'id':'s','include_url_pattern':'^https://example.com/'}]}),encoding='utf-8')
            detail={'notice_type':'招聘公告','screening':{'verdict':'需要人工核实'},'detail':{'status':'ok'},'attachments':[{'url':'https://example.com/a.xls','status':'failed','error':'bad XLS'}]}
            with patch.object(e,'enrich',return_value=detail),patch.object(e.time,'sleep'):
                with self.assertRaises(SystemExit):e.main(data,sources)
            result=json.loads(data.read_text(encoding='utf-8'))
            self.assertEqual(result['details_summary']['ok'],1)
            self.assertEqual(result['jobs'][0]['detail']['status'],'ok')
            self.assertEqual(len(result['attachment_failures']),1)

    def test_explicit_hyphenated_application_range(self):
        result=e.analyze('招聘公告','报名自2026年9月18日- 2026年10月9日止。','https://example.com')
        self.assertEqual(result['deadline'],'2026-10-09')

    def test_multiple_dates_in_one_line_remain_ambiguous(self):
        result=e.analyze('招聘公告','报名：岗位一报名截止2026年11月1日；岗位二报名截止2026年12月1日。','https://example.com')
        self.assertIsNone(result['deadline'])

    def test_upstream_list_failure_does_not_retry_details(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)/'jobs.json';sources=Path(folder)/'sources.json'
            data.write_text(json.dumps({'updated_at':'now','sources_failed':[{'source':'s','error':'blocked'}],'jobs':[{'id':'x','title':'招聘','source_id':'s','url':'https://example.com/a','body_positions':[{'fields':{'name':'old'}}]}]}),encoding='utf-8')
            sources.write_text(json.dumps({'sources':[{'id':'s','include_url_pattern':'^https://example.com/'}]}),encoding='utf-8')
            with patch.object(e,'enrich') as fetch,patch.object(e.time,'sleep'):
                with self.assertRaises(SystemExit):e.main(data,sources)
                fetch.assert_not_called()
            result=json.loads(data.read_text(encoding='utf-8'))
            self.assertEqual(result['jobs'][0]['body_positions'],[])
            self.assertEqual(result['jobs'][0]['detail']['status'],'failed')

if __name__=='__main__':unittest.main()
