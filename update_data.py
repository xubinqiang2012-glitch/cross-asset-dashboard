#!/usr/bin/env python3
"""
黄金反身性仪表板 · 服务端数据拉取脚本
=====================================
用途：绕过浏览器 CORS 限制，从数据源拉取最新值，写入 gold-data.json，
      仪表板加载时会优先读取此文件。

使用：
  1. 配置 FRED API key (可选 — 用于实际利率)：
     export FRED_API_KEY=your_key_here
  2. 手动跑一次：
     python3 update_data.py
  3. 加 cron 每周自动跑（macOS 周一晚 9 点）：
     crontab -e
     0 21 * * 1 cd /Users/binqiangxu/claude && /usr/bin/python3 update_data.py >> update.log 2>&1

依赖：仅需 Python 3 标准库 (urllib)。
"""

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_FILE = Path(__file__).parent / "gold-data.json"
FRED_API_KEY = os.environ.get("FRED_API_KEY", "").strip()
TIMEOUT = 15

UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) GoldDashboard/1.0",
    "Accept": "*/*",
}


def http_get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA_HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_stooq(symbol: str):
    """Stooq CSV: Symbol,Date,Time,Open,High,Low,Close,Volume"""
    url = f"https://stooq.com/q/l/?s={urllib.parse.quote(symbol)}&f=sd2t2ohlcv&h&e=csv"
    text = http_get(url)
    lines = text.strip().splitlines()
    if len(lines) < 2:
        raise ValueError("空响应")
    fields = lines[1].split(",")
    if len(fields) < 7:
        raise ValueError(f"字段数不足: {fields}")
    close = float(fields[6])
    return {"value": close, "date": fields[1]}


def fetch_fred(series_id: str):
    if not FRED_API_KEY:
        raise RuntimeError("未配置 FRED_API_KEY 环境变量")
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={FRED_API_KEY}"
        f"&file_type=json&sort_order=desc&limit=5"
    )
    data = json.loads(http_get(url))
    obs = data.get("observations", [])
    for o in obs:
        if o.get("value") and o["value"] != ".":
            return {"value": float(o["value"]), "date": o["date"]}
    raise ValueError("近期均无有效数据")


def main():
    results = {}
    errors = {}
    sources = {}

    fetchers = [
        ("gold",       lambda: fetch_stooq("xauusd")),
        ("dxy",        lambda: fetch_stooq("dx.f")),
        ("real_yield", lambda: fetch_fred("DFII10")),
    ]

    for key, fn in fetchers:
        try:
            r = fn()
            results[key] = round(r["value"], 4)
            sources[key] = r["date"]
            print(f"  ✓ {key:12s} = {r['value']:>10.4f}  (源: {r['date']})")
        except Exception as e:
            errors[key] = str(e)
            print(f"  ✗ {key:12s} 失败: {e}", file=sys.stderr)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "values": results,
        "source_dates": sources,
        "errors": errors,
    }

    OUTPUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n→ 写入 {OUTPUT_FILE}")
    print(f"  {len(results)} 个成功 / {len(errors)} 个失败")

    return 0 if results else 1


if __name__ == "__main__":
    print(f"[{datetime.now().isoformat(timespec='seconds')}] 开始拉取...")
    sys.exit(main())
