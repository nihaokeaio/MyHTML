import importlib.util
import unittest
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

if __name__ == "__main__":
    unittest.main()
