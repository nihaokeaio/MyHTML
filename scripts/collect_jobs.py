#!/usr/bin/env python3
"""Conservative public notice collector: no fabricated jobs, no bypassing access controls."""
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import ssl

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

class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'title': self.active = True

    def handle_endtag(self, tag):
        if tag == 'title': self.active = False

    def handle_data(self, data):
        if self.active: self.parts.append(data)

def score(title):
    s = 0
    if any(x in title for x in TECH): s += 40
    if any(x in title for x in REGIONS): s += 20
    if any(x in title for x in ("研究院", "研究所", "事业单位", "国企", "集团")): s += 15
    return s

class CollectionError(RuntimeError):
    pass


def log(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def error_kind(exc):
    if isinstance(exc, HTTPError):
        return "http_" + str(exc.code)
    if exc.__cause__ is not None:
        return error_kind(exc.__cause__)
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "tls_certificate"
    if isinstance(reason, (TimeoutError,)): return "timeout"
    return type(reason).__name__


def fetch_page(source):
    req = Request(source["url"], data=urlencode(source["form"]).encode() if source.get("form") is not None else None, headers={"User-Agent": "JobRadar/0.1 (+personal public recruitment monitor)"})
    last_error = None
    for attempt in range(1, 4):
        try:
            with urlopen(req, timeout=12) as response:
                content = response.read(2_000_001)
                if len(content) > 2_000_000:
                    raise CollectionError("Response exceeds 2 MB limit")
                final_url = response.url
                content_type = response.headers.get_content_type()
                if content_type not in ("text/html", "application/xhtml+xml", "application/json") or (content_type == "application/json" and not source.get("json")):
                    raise CollectionError("Unexpected content type: " + content_type)
                log("http_response", source=source["id"], status=response.status,
                    final_url=final_url, bytes=len(content))
                charset = response.headers.get_content_charset() or "utf-8"
            break
        except Exception as exc:
            last_error = exc
            log("fetch_error", source=source["id"], attempt=attempt,
                kind=error_kind(exc), error=str(exc))
            if (isinstance(exc, CollectionError)
                    or isinstance(exc, HTTPError) and exc.code < 500
                    or isinstance(getattr(exc, "reason", exc), ssl.SSLCertVerificationError)):
                raise
            if attempt < 3:
                time.sleep(attempt * 2)
    else:
        raise RuntimeError(f"All 3 attempts failed: {last_error}") from last_error
    return content.decode(charset, errors="replace"), final_url


def fetch_links(source):
    if source.get("collection_hold"):
        raise CollectionError("Collection held: " + source["collection_hold"])
    if source.get('adapter'):
        from source_adapters import list_links
        links, final_url = list_links(source)
    else:
        html, final_url = fetch_page(source)
        parser = LinkParser()
        parser.feed(html)
        links = parser.links
    if source.get('kind') == 'article':
        title_parser = TitleParser()
        title_parser.feed(html)
        links = [(final_url, ''.join(title_parser.parts).strip())]
    seen = set()
    for link in links:
        href, title = link[:2]
        metadata = link[2] if len(link) > 2 else {}
        url = urljoin(final_url, href)
        if urlsplit(url).scheme not in ("https", "http"): continue
        if not any(word.lower() in title.lower() for word in source.get('keywords', KEYWORDS)): continue
        if source.get("include_url_pattern") and not re.search(source["include_url_pattern"], url): continue
        url = normalize_url(url)
        if url in seen: continue
        seen.add(url)
        yield {"id": stable_id(url), "title": title[:250], "url": normalize_url(url),
               "source": source["name"], "source_id": source["id"], "score": score(title),
               "eligibility": "待核实", "employment": "待核实",
               "deadline": None, "status": "待核实", "listing": metadata}

def main(data_path=None, sources_path=None):
    data_path = Path(data_path) if data_path else DATA
    sources_path = Path(sources_path) if sources_path else SOURCES
    existing = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else {"jobs": []}
    jobs = {j["id"]: j for j in existing.get("jobs", [])}
    sources = json.loads(sources_path.read_text(encoding="utf-8"))["sources"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    failures, successes, new = [], 0, 0
    results = []
    for source in sources:
        if not source.get("enabled", True): continue
        try:
            found = list(fetch_links(source))
            if not found:
                raise CollectionError("No candidate notices: check page structure, JS redirect or access restriction")
            for item in found:
                if item["id"] in jobs:
                    jobs[item["id"]]["last_seen"] = now
                    if "title" in item: jobs[item["id"]]["title"] = item["title"]
                    jobs[item["id"]]["listing"] = item.get("listing", {})
                else:
                    item["first_seen"] = now
                    item["last_seen"] = now
                    jobs[item["id"]] = item
                    new += 1
            successes += 1
            unique_found = len({item["id"] for item in found})
            results.append({"source": source["id"], "status": "ok", "notices": unique_found})
            log("source_complete", **results[-1])
        except Exception as e:
            failure = {"source": source["id"], "error": str(e)[:250], "kind": error_kind(e)}
            failures.append(failure)
            results.append({**failure, "status": "failed", "notices": 0})
            log("source_failed", **failure)
    output = {"run_id": os.environ.get("JOBRADAR_RUN_ID"), "updated_at": now, "sources_ok": successes, "sources_failed": failures,
              "source_results": results,
              "jobs": sorted(jobs.values(), key=lambda j: j.get("first_seen", ""), reverse=True)}
    temporary = data_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, data_path)
    log("collection_complete", status="failed" if failures or not successes else "ok",
        new=new, total=len(jobs), sources_ok=successes, sources_failed=len(failures))
    if failures or not successes:
        raise SystemExit(1)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DATA)); parser.add_argument("--sources", default=str(SOURCES))
    args = parser.parse_args()
    main(args.data, args.sources)
