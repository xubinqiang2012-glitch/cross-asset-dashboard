#!/usr/bin/env python3
"""
机构观点流 · 自动拉取
======================
从 Google News RSS + 官方 RSS 拉取 8 家机构最新观点，
写入 commentary-data.json 供仪表板加载。

数据源：
- Google News RSS (无需 key)
- Federal Reserve 官方 RSS (speeches + monetary press)

使用：
  python3 update_commentary.py        # 一次拉取
  每日 4 次 (cron / launchd) 自动跑
"""

import json
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

OUTPUT_FILE = Path(__file__).parent / "commentary-data.json"
TIMEOUT = 15
MAX_ITEMS_PER_SOURCE = 5


def gnews(query: str) -> str:
    return (
        f"https://news.google.com/rss/search?"
        f"q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    )


SOURCES = [
    {"id": "bridgewater", "name": "Bridgewater · Dalio",
     "feeds": [gnews('"Ray Dalio" OR Bridgewater Associates macro')]},
    {"id": "blackrock", "name": "BlackRock BII",
     "feeds": [gnews('"BlackRock Investment Institute" OR "BlackRock" outlook macro')]},
    {"id": "goldman", "name": "Goldman Sachs Research",
     "feeds": [gnews('"Goldman Sachs" research macro OR "Top of Mind"')]},
    {"id": "jpm", "name": "JPM · Cembalest",
     "feeds": [gnews('"Michael Cembalest" OR "Eye on the Market" JPMorgan')]},
    {"id": "ms", "name": "Morgan Stanley",
     "feeds": [gnews('"Morgan Stanley" macro outlook OR "Mike Wilson"')]},
    {"id": "pimco", "name": "PIMCO",
     "feeds": [gnews('PIMCO macro outlook OR insights')]},
    {"id": "fed", "name": "Fed · FOMC",
     "feeds": [
         "https://www.federalreserve.gov/feeds/speeches.xml",
         "https://www.federalreserve.gov/feeds/press_monetary.xml",
     ]},
    {"id": "wgc", "name": "World Gold Council",
     "feeds": [gnews('"World Gold Council" OR "central bank gold" purchases')]},
]

UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) Dashboard/1.0",
    "Accept": "application/rss+xml,application/xml,*/*",
}


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA_HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&[a-z]+;", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_feed(xml_bytes: bytes, max_items: int = 5):
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    items = []

    # RSS 2.0
    for item in root.findall(".//item")[:max_items]:
        items.append({
            "title":   clean_text(item.findtext("title") or ""),
            "link":    (item.findtext("link") or "").strip(),
            "pubDate": (item.findtext("pubDate") or "").strip(),
            "summary": clean_text(item.findtext("description") or "")[:240],
            "source":  clean_text(
                (item.find("source").text if item.find("source") is not None else "") or ""
            ),
        })

    # Atom
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//a:entry", ns)[:max_items]:
            link_el = entry.find("a:link", ns)
            items.append({
                "title":   clean_text(entry.findtext("a:title", default="", namespaces=ns)),
                "link":    (link_el.get("href") if link_el is not None else "").strip(),
                "pubDate": (entry.findtext("a:updated", default="", namespaces=ns) or "").strip(),
                "summary": clean_text(entry.findtext("a:summary", default="", namespaces=ns))[:240],
                "source":  "",
            })

    return items


def main():
    print(f"[{datetime.now().isoformat(timespec='seconds')}] 拉取 {len(SOURCES)} 家机构观点...")
    out = {}
    errors = {}
    for src in SOURCES:
        all_items = []
        for url in src["feeds"]:
            try:
                xml = http_get(url)
                items = parse_feed(xml, max_items=MAX_ITEMS_PER_SOURCE)
                all_items.extend(items)
            except Exception as e:
                errors.setdefault(src["id"], []).append(str(e))

        # dedupe by title
        seen, unique = set(), []
        for it in all_items:
            if it["title"] and it["title"] not in seen:
                seen.add(it["title"])
                unique.append(it)
        out[src["id"]] = unique[:MAX_ITEMS_PER_SOURCE]
        flag = "✓" if unique else "✗"
        print(f"  {flag} {src['id']:13s} {src['name']:28s} {len(unique)} 条")

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": out,
        "errors": errors,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n→ 写入 {OUTPUT_FILE}")
    print(f"  {sum(len(v) for v in out.values())} 条 · {len(errors)} 个源出错")
    return 0


if __name__ == "__main__":
    sys.exit(main())
