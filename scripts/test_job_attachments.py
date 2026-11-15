import unittest
from unittest.mock import patch
import job_attachments as a
import enrich_jobs as e

class Sheet:
    name='计划'
    rows=[['标题','','','',''],['序号','学院（系）/单位','岗位名称','应聘要求',''],['','','','学历/学位','专业'],[1.,'研究院','软件工程师','硕士及以上','计算机'],[2.,'','算法岗','研究生/博士','软件工程'],['','合计','','','']]
    nrows=len(rows);ncols=5
    merged_cells=[(0,1,0,5),(1,3,0,1),(1,3,1,2),(1,3,2,3),(3,5,1,2)]
    def row_values(self,r):return self.rows[r]

class AttachmentTests(unittest.TestCase):
    def test_two_level_header_merge_and_total(self):
        rows=a.sheet_records(Sheet())
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1]['fields']['department'],'研究院')
        self.assertEqual(rows[1]['row'],5)
        self.assertEqual(rows[0]['fields']['education'],'硕士及以上')
    def test_education_exclusion_is_per_role(self):
        self.assertEqual(a.triage({'education':'研究生/博士'})['verdict'],'明确不符合')
        self.assertEqual(a.triage({'education':'硕士及以上','requirements':'博士优先；Qt开发'})['verdict'],'需要人工核实')
        self.assertEqual(a.triage({'education':''})['verdict'],'需要人工核实')
    def test_cad_operator_is_not_software_priority(self):
        self.assertEqual(a.triage({'name':'数控加工工程师','requirements':'熟练CAD/CAM制图'})['priority'],'普通核实')

    def test_application_forms_not_downloaded(self):
        with patch.object(a,'urlopen') as fetch:
            result=a.process_attachment({'url':'https://example.com/form.xls','title':'应聘履历登记表.xls'},'https://example.com/article')
            self.assertEqual(result['status'],'skipped');fetch.assert_not_called()
    def test_foreign_host_and_unsupported_formats_report_failure(self):
        for url in ('https://other.com/plan.xls','https://example.com/plan.pdf'):
            with patch.object(a,'urlopen') as fetch:
                self.assertEqual(a.process_attachment({'url':url,'title':'岗位表'},'https://example.com/a')['status'],'failed')
                fetch.assert_not_called()
    def test_non_xls_html_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Not an OLE'):
            a.parse_xls(b'<html>login</html>','https://example.com/plan.xls')
    def test_body_roles_do_not_inherit_other_degrees(self):
        rows=e.body_positions('招聘','一、研发工程师\n博士学历\n二、软件工程师\n硕士及以上学历\nQt与C++开发','https://example.com/a')
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['screening']['verdict'],'明确不符合')
        self.assertEqual(rows[1]['screening']['priority'],'优先核实')
        self.assertNotIn('博士',rows[1]['fields']['education'])
    def test_source_specific_body_boundary(self):
        p=e.ArticleParser('html');p.feed('<nav>导航</nav><div class="html"><p>实际岗位</p></div><p>页脚</p>')
        self.assertEqual(p.text(),'实际岗位')

    def test_designer_role_is_preserved(self):
        rows=e.body_positions('招聘','一、结构设计师\n本科，机械设计\n二、软件工程师\n硕士，C++','https://example.com/a')
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['fields']['name'],'结构设计师')

if __name__=='__main__':unittest.main()
