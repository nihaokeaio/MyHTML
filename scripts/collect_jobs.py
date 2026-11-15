#!/usr/bin/env python3
"""Conservative public notice collector: no fabricated jobs, no bypassing access controls."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "jobradar" / "jobs.json"
SOURCES = ROOT / "jobradar" / "sources.json"
KEYWORDS = ("招聘", "招录", "公开选聘", "公开招聘")
TECH = ("软件", "计算机", "C++", "Qt", "三维", "研发", "算法", "信息技术", "人工智能", "工程师")
REGIONS = ("杭州", "浙江", "宁波", "嘉兴", "绍兴")

def normalize_url(url):
    p = urlsplit(url.strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", p.query, ""))

def stable_id(url):
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:20]

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.parts = []
    def handle_data(self, data):
        if self.href is not None:
            self.parts.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            title = re.sub(r"\s+", " ", "".join(self.parts)).strip()
            if title:
                self.links.append((self.href, title))
            self.href = None
            self.parts = []

def score(title):
    s = 0
    if any(x in title for x in TECH): s += 40
    if any(x in title for x in REGIONS): s += 20
    if any(x in title for x in ("研究院", "研究所", "事业单位", "国企", "集团")): s += 15
    return s

def fetch_links(source):
    req = Request(source["url"], headers={"User-Agent": "JobRadar/0.1 (+personal public recruitment monitor)"})
    with urlopen(req, timeout=18) as response:
        content = response.read(2_000_000)
        charset = response.headers.get_content_charset() or "utf-8"
    parser = LinkParser()
    parser.feed(content.decode(charset, errors="replace"))
    for href, title in parser.links:
        url = urljoin(source["url"], href)
        if urlsplit(url).scheme not in ("https", "http"): continue
        if not any(word in title for word in KEYWORDS): continue
        yield {"id": stable_id(url), "title": title[:250], "url": normalize_url(url),
               "source": source["name"], "source_id": source["id"], "score": score(title),
               "eligibility": "待核实", "employment": "待核实",
               "deadline": None, "status": "待核实"}

def main():
    existing = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {"jobs": []}
    jobs = {j["id"]: j for j in existing.get("jobs", [])}
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))["sources"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    failures, successes, new = [], 0, 0
    for source in sources:
        if not source.get("enabled", True): continue
        try:
            found = list(fetch_links(source))
            successes += 1
            for item in found:
                if item["id"] in jobs:
                    jobs[item["id"]]["last_seen"] = now
                else:
                    item["first_seen"] = now
                    item["last_seen"] = now
                    jobs[item["id"]] = item
                    new += 1
            print(f'{source["id"]}: {len(found)} candidate notices')
        except Exception as e:
            failures.append({"source": source["id"], "error": str(e)[:250]})
            print(f'{source["id"]}: FAILED: {e}')
    output = {"updated_at": now, "sources_ok": successes, "sources_failed": failures,
              "jobs": sorted(jobs.values(), key=lambda j: j.get("first_seen", ""), reverse=True)}
    DATA.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"new={new} total={len(jobs)} failed={len(failures)}")
    if failures or not successes:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
