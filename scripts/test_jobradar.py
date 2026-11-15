import importlib.util
import unittest
import json
import tempfile
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from email.message import Message
from pathlib import Path

spec = importlib.util.spec_from_file_location("collector", Path(__file__).with_name("collect_jobs.py"))
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

class CollectorTests(unittest.TestCase):
    def test_url_normalization(self):
        self.assertEqual(collector.normalize_url("HTTPS://EXAMPLE.COM/a/#fragment"), "https://example.com/a")
    def test_stable_id(self):
        self.assertEqual(collector.stable_id("https://example.com/a#x"), collector.stable_id("https://example.com/a"))
    def test_score(self):
        self.assertGreater(collector.score("杭州 C++ 软件研发"), collector.score("食堂采购公告"))
    def test_link_parser(self):
        p = collector.LinkParser()
        p.feed('<a href="/notice">公开招聘软件工程师</a>')
        self.assertEqual(p.links, [("/notice", "公开招聘软件工程师")])

class ReliabilityTests(unittest.TestCase):
    def run_collection(self, outcomes, existing=None):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "jobs.json"
            sources = Path(folder) / "sources.json"
            data.write_text(json.dumps({"jobs": existing or []}), encoding="utf-8")
            sources.write_text(json.dumps({"sources": [
                {"id": str(i), "name": str(i), "url": "https://example.com"}
                for i in range(len(outcomes))]}), encoding="utf-8")
            with patch.object(collector, "fetch_links", side_effect=outcomes):
                try:
                    collector.main(data, sources)
                    code = 0
                except SystemExit as exc:
                    code = exc.code
            return code, json.loads(data.read_text(encoding="utf-8"))

    def test_partial_failure_preserves_old_and_new_and_continues(self):
        old = {"id": "old", "first_seen": "2020", "last_seen": "2020"}
        code, result = self.run_collection([OSError("timeout"), [{"id": "new"}]], [old])
        self.assertEqual(code, 1)
        self.assertEqual({j["id"] for j in result["jobs"]}, {"old", "new"})
        self.assertEqual(result["sources_ok"], 1)
        self.assertEqual(len(result["sources_failed"]), 1)

    def test_empty_page_is_failure(self):
        code, result = self.run_collection([[]])
        self.assertEqual(code, 1)
        self.assertEqual(result["sources_ok"], 0)

    def test_duplicate_preserves_first_seen(self):
        code, result = self.run_collection([[{"id": "same"}, {"id": "same"}]],
                                           [{"id": "same", "first_seen": "2020"}])
        self.assertEqual(code, 0)
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["jobs"][0]["first_seen"], "2020")
        self.assertIn("last_seen", result["jobs"][0])

    def test_no_enabled_sources_fails(self):
        self.assertEqual(self.run_collection([])[0], 1)

    def test_403_is_not_retried(self):
        with patch.object(collector, "urlopen", side_effect=HTTPError(
                "https://example.com", 403, "Forbidden", {}, None)) as fetch:
            with self.assertRaises(HTTPError):
                list(collector.fetch_links({"id": "blocked", "url": "https://example.com"}))
            self.assertEqual(fetch.call_count, 1)

    def test_redirect_base_and_article_filter(self):
        response = MagicMock()
        response.url = "https://example.com/news/"
        response.status = 200
        response.headers = Message()
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.read.return_value = '<a href="article.htm">软件招聘</a><a href="index.htm">招聘栏目</a>'.encode()
        with patch.object(collector, "urlopen") as fetch:
            fetch.return_value.__enter__.return_value = response
            items = list(collector.fetch_links({"id": "test", "name": "Test",
                "url": "https://example.com/old", "include_url_pattern": "article[.]htm$"}))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.com/news/article.htm")

    def test_article_watch_uses_page_title_not_related_links(self):
        response = MagicMock()
        response.url = 'https://example.com/position?id=1'
        response.status = 200
        response.headers = Message()
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.read.return_value = '<title>C++开发工程师-社会招聘</title><a href="/other">其他招聘</a>'.encode()
        with patch.object(collector, 'urlopen') as fetch:
            fetch.return_value.__enter__.return_value = response
            items=list(collector.fetch_links({'id':'watch','name':'Official','url':response.url,'kind':'article','keywords':['C++']}))
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['url'],response.url)
        self.assertIn('C++',items[0]['title'])

if __name__ == "__main__":
    unittest.main()
