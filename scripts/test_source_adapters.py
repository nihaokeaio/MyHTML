import json
import unittest
from unittest.mock import patch
import source_adapters as a
import enrich_jobs as e

class AdapterTests(unittest.TestCase):
    def test_xidian_public_api_pagination_and_schema(self):
        with patch.object(a,'fetch_page',side_effect=[(json.dumps({'success':True,'data':'<a href="/portal/info/a">工程师</a>','pageCount':2}),'u')]*2) as fetch:
            links,_=a.list_links({'id':'s','url':'https://example.com/portal/list','adapter':'xidian','max_pages':2})
            self.assertEqual(len(links),2);self.assertEqual(fetch.call_count,2)
            self.assertEqual(fetch.call_args.args[0]['form']['page'],2)
        with patch.object(a,'fetch_page',return_value=('{"success":false}','u')):
            with self.assertRaises(a.CollectionError):a.list_links({'id':'s','url':'https://example.com','adapter':'xidian'})
    def test_nimte_public_onclick_is_converted_but_delivery_is_not(self):
        html='<a onclick=\'viewPositionInfo("123",null)\' href="javascript:void(0)">C++工程师</a><a onclick="deliveryPosition(1)">投递</a>'
        with patch.object(a,'fetch_page',return_value=(html,'u')):
            links,_=a.list_links({'id':'s','url':'https://example.com/index','adapter':'nimte_portal'})
        self.assertEqual(len(links),1);self.assertIn('positionInfo?id=123',links[0][0])
    def test_cncico_lists_keep_official_deadline_metadata(self):
        data={'code':0,'data':{'total':1,'list':[{'url':'/content/1','title':'招聘','customs':{'deadline':'2026-12-01 00:00:00'}}]}}
        with patch.object(a,'fetch_page',return_value=(json.dumps(data),'u')):
            links,_=a.list_links({'id':'s','url':'https://example.com','adapter':'cncico'})
        self.assertEqual(links[0][2]['deadline'],'2026-12-01 00:00:00')
    def test_html_table_keeps_role_qualifications_separate(self):
        p=e.ArticleParser('body')
        p.feed('<div class="body"><table><tr><td>岗位名称</td><td>资格条件</td></tr><tr><td>AI工程师</td><td>博士</td></tr><tr><td>C++工程师</td><td>硕士，Qt开发</td></tr></table></div>')
        roles=e.table_positions(p.table_rows,'https://example.com/a')
        self.assertEqual(len(roles),2);self.assertEqual(roles[0]['screening']['verdict'],'明确不符合')
        self.assertEqual(roles[1]['screening']['verdict'],'需要人工核实')
    def test_single_role_deadline_iso(self):
        html='<div class="job-details">软件工程师<p>发布日期：2026-11-06 | 截止日期：2027-11-05</p><p>硕士及以上，C++开发工作经验三年以上。公开招聘，需要现场开发软件系统。</p></div>'
        with patch.object(e,'fetch_page',return_value=(html,'https://example.com/a')):
            result=e.enrich({'id':'x','title':'软件工程师','url':'https://example.com/a'},{'single_position':True,'article_class':'job-details'})
        self.assertEqual(result['deadline'],'2027-11-05');self.assertEqual(len(result['body_positions']),1)

    def test_hold_is_failure_without_network(self):
        import collect_jobs as c
        with patch.object(c,'fetch_page') as fetch:
            with self.assertRaises(c.CollectionError):list(c.fetch_links({'id':'held','collection_hold':'non-JSON response'}))
            fetch.assert_not_called()

if __name__=='__main__':unittest.main()
