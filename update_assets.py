#!/usr/bin/env python3
"""
跨资产监控仪表板 · 服务端数据拉取
==================================
拉取所有大类资产历史，计算 1D/1W/1M/YTD 变化，写入 assets-data.json。

数据源：Yahoo Finance v8 Chart API（免费、无需 key、含完整 OHLC 历史）

使用：
  python3 update_assets.py            # 一次性拉取
  crontab -e                          # 每日早 7:30 自动跑
  30 7 * * * cd /Users/binqiangxu/claude && /usr/bin/python3 update_assets.py >> assets.log 2>&1
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_FILE = Path(__file__).parent / "assets-data.json"
TIMEOUT = 20
FRED_API_KEY = os.environ.get("FRED_API_KEY", "").strip()

# Yahoo Finance ticker mapping
ASSETS = [
    # Equities
    {"id": "spx",    "name": "S&P 500",       "ysym": "^GSPC",      "cls": "equity"},
    {"id": "ndx",    "name": "Nasdaq 100",    "ysym": "^NDX",       "cls": "equity"},
    {"id": "rty",    "name": "Russell 2000",  "ysym": "^RUT",       "cls": "equity"},
    {"id": "sx5e",   "name": "Euro Stoxx 50", "ysym": "^STOXX50E",  "cls": "equity"},
    {"id": "nky",    "name": "Nikkei 225",    "ysym": "^N225",      "cls": "equity"},
    {"id": "hsi",    "name": "Hang Seng",     "ysym": "^HSI",       "cls": "equity"},
    {"id": "hstech", "name": "HS Tech",       "ysym": "3033.HK",    "cls": "equity"},
    {"id": "shc",    "name": "Shanghai Comp", "ysym": "000001.SS",  "cls": "equity"},
    # Rates (yields in % · JGB ETF as proxy for Japan)
    {"id": "us10y",  "name": "US 10Y Yield",  "ysym": "^TNX",       "cls": "rates"},
    {"id": "us5y",   "name": "US 5Y Yield",   "ysym": "^FVX",       "cls": "rates"},
    {"id": "us30y",  "name": "US 30Y Yield",  "ysym": "^TYX",       "cls": "rates"},
    {"id": "jgb",    "name": "JGB ETF",       "ysym": "2510.T",     "cls": "rates"},
    {"id": "jgb_yield", "name": "JGB 10Y Yield (M)", "src": "fred",
     "fred_id": "IRLTLT01JPM156N", "cls": "rates", "cadence": "monthly", "unit": "%"},
    # Commodities
    {"id": "gold",   "name": "Gold",          "ysym": "GC=F",       "cls": "commodity"},
    {"id": "silver", "name": "Silver",        "ysym": "SI=F",       "cls": "commodity"},
    {"id": "oil",    "name": "WTI Crude",     "ysym": "CL=F",       "cls": "commodity"},
    {"id": "copper", "name": "Copper",        "ysym": "HG=F",       "cls": "commodity"},
    # FX
    {"id": "dxy",    "name": "Dollar Index",  "ysym": "DX-Y.NYB",   "cls": "fx"},
    {"id": "eur",    "name": "EUR/USD",       "ysym": "EURUSD=X",   "cls": "fx"},
    {"id": "jpy",    "name": "USD/JPY",       "ysym": "JPY=X",      "cls": "fx"},
    {"id": "cny",    "name": "USD/CNY",       "ysym": "CNY=X",      "cls": "fx"},
    # Crypto
    {"id": "btc",    "name": "Bitcoin",       "ysym": "BTC-USD",    "cls": "crypto"},
    {"id": "eth",    "name": "Ethereum",      "ysym": "ETH-USD",    "cls": "crypto"},
    # Vol
    {"id": "vix",    "name": "VIX",           "ysym": "^VIX",       "cls": "vol"},
]

UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15",
    "Accept": "application/json,text/plain,*/*",
}


def http_get(url: str, retries: int = 3) -> bytes:
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA_HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 403 or e.code == 429:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s backoff
                continue
            raise
        except Exception as e:
            last_err = e
            time.sleep(1)
    raise last_err


def fetch_yahoo_history(symbol: str, range_str: str = "1y"):
    """Returns list of {date, close} from Yahoo Finance v8 chart API."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(symbol)}?range={range_str}&interval=1d"
    )
    data = json.loads(http_get(url).decode("utf-8"))
    chart = data.get("chart", {})
    err = chart.get("error")
    if err:
        raise ValueError(err.get("description", str(err)))
    result = chart.get("result")
    if not result:
        raise ValueError("无 result 数据")
    r = result[0]
    timestamps = r.get("timestamp", []) or []
    quote = (r.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close", []) or []
    out = []
    for ts, c in zip(timestamps, closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
        out.append({"date": d, "close": float(c)})
    if not out:
        raise ValueError("无有效收盘价")
    # Override last close with realtime if available
    meta = r.get("meta", {})
    rt = meta.get("regularMarketPrice")
    if rt is not None and out:
        # Update last day's close with real-time price
        out[-1]["close"] = float(rt)
    return out


def fetch_fred_monthly(series_id: str, months: int = 36):
    """从 FRED 拉月度序列。返回 [{date, close}, ...] (按日期升序)。"""
    if not FRED_API_KEY:
        raise RuntimeError("未配置 FRED_API_KEY 环境变量")
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={FRED_API_KEY}"
        f"&file_type=json&sort_order=desc&limit={months}"
    )
    data = json.loads(http_get(url).decode("utf-8"))
    obs = data.get("observations", [])
    out = []
    for o in reversed(obs):  # reverse to ascending
        if o.get("value") and o["value"] != ".":
            out.append({"date": o["date"], "close": float(o["value"])})
    if not out:
        raise ValueError("FRED 无有效观测值")
    return out


def compute_changes_monthly(history):
    """月度数据用专用变化口径：MoM / 3M / 6M / YoY。"""
    if not history:
        return None
    sorted_h = sorted(history, key=lambda x: x["date"])
    today_p = sorted_h[-1]["close"]

    def offset_months(n):
        idx = len(sorted_h) - 1 - n
        return sorted_h[idx]["close"] if idx >= 0 else None

    def calc(prev):
        return (today_p - prev) / prev if prev else None

    # YTD: 取上一年 12 月数据 (or 当年 1 月)
    year = sorted_h[-1]["date"][:4]
    ytd_base = next(
        (x["close"] for x in sorted_h if x["date"].startswith(year)), None
    )

    return {
        "price": round(today_p, 6),
        "changes": {
            "mom":  calc(offset_months(1)),
            "3m":   calc(offset_months(3)),
            "6m":   calc(offset_months(6)),
            "yoy":  calc(offset_months(12)),
            "ytd":  calc(ytd_base),
        },
        "history": [round(x["close"], 6) for x in sorted_h[-24:]],
        "last_date": sorted_h[-1]["date"],
        "cadence": "monthly",
    }


def compute_changes(history):
    if not history:
        return None
    sorted_h = sorted(history, key=lambda x: x["date"])
    today_p = sorted_h[-1]["close"]

    def offset(n):
        idx = len(sorted_h) - 1 - n
        return sorted_h[idx]["close"] if idx >= 0 else None

    def calc(prev):
        return (today_p - prev) / prev if prev else None

    year = sorted_h[-1]["date"][:4]
    ytd = next((x["close"] for x in sorted_h if x["date"].startswith(year)), None)

    return {
        "price": round(today_p, 6),
        "changes": {
            "1d":  calc(offset(1)),
            "1w":  calc(offset(5)),
            "1m":  calc(offset(21)),
            "ytd": calc(ytd),
        },
        "history": [round(x["close"], 6) for x in sorted_h[-90:]],
        "last_date": sorted_h[-1]["date"],
    }


def compute_regime(results):
    """
    从 1M 市场动量自动判定宏观四象限。
      增长信号: 铜 + 小盘股 + 标普 (Dr. Copper / 周期类)
      通胀信号: 油 + 黄金 + 白银
    """
    def chg(asset_id, period="1m"):
        v = (results.get(asset_id, {}) or {}).get("changes", {}) or {}
        return v.get(period) or 0

    growth_score = (
        chg("copper") * 1.0 +
        chg("rty")    * 0.6 +
        chg("spx")    * 0.4 -
        chg("us10y")  * 0.2  # 长端利率上行常伴随增长走弱预期
    )
    inflation_score = (
        chg("oil")    * 1.0 +
        chg("gold")   * 0.5 +
        chg("silver") * 0.3 +
        chg("copper") * 0.2
    )

    growth_up = growth_score > 0.005     # 1M 加权 > 0.5%
    inflation_up = inflation_score > 0.010  # 1M 加权 > 1%

    if growth_up and inflation_up:        regime = "q1"
    elif growth_up and not inflation_up:  regime = "q2"
    elif not growth_up and not inflation_up: regime = "q3"
    else:                                 regime = "q4"

    regime_names = {
        "q1": "Q1 增长↑通胀↑ (再通胀)",
        "q2": "Q2 增长↑通胀↓ (金发姑娘)",
        "q3": "Q3 增长↓通胀↓ (通缩衰退)",
        "q4": "Q4 增长↓通胀↑ (滞胀)",
    }

    return {
        "regime": regime,
        "regime_name": regime_names[regime],
        "growth_score": round(growth_score, 4),
        "inflation_score": round(inflation_score, 4),
        "method": "1M 加权动量 · copper+小盘+SPX (增长) / 油+金+银 (通胀)",
    }


def main():
    print(f"[{datetime.now().isoformat(timespec='seconds')}] 开始拉取 {len(ASSETS)} 个资产 (Yahoo Finance)...")
    results = {}
    errors = {}
    for a in ASSETS:
        try:
            src = a.get("src", "yahoo")
            if src == "fred":
                h = fetch_fred_monthly(a["fred_id"], months=36)
                r = compute_changes_monthly(h)
                # for monthly assets, log MoM not 1d
                mom = r["changes"]["mom"] or 0
                yoy = r["changes"]["yoy"] or 0
                print(f"  ✓ {a['id']:10s} {a['name']:22s} {r['price']:>10.4f}{a.get('unit','')}  "
                      f"MoM {(mom*100):>+6.2f}%  YoY {(yoy*100):>+6.2f}%  ({r['last_date']})")
            else:
                h = fetch_yahoo_history(a["ysym"], "1y")
                r = compute_changes(h)
                ch1d = r["changes"]["1d"] or 0
                print(f"  ✓ {a['id']:10s} {a['name']:22s} {r['price']:>10.4f}  "
                      f"1D {(ch1d*100):>+6.2f}%  ({r['last_date']})")
                time.sleep(0.4)  # gentle to Yahoo
            results[a["id"]] = r
        except Exception as e:
            errors[a["id"]] = str(e)
            print(f"  ✗ {a['id']:10s} {a.get('name','?'):22s} 失败: {e}", file=sys.stderr)

    regime = compute_regime(results) if results else None
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "assets": results,
        "regime": regime,
        "errors": errors,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n→ 写入 {OUTPUT_FILE}")
    print(f"  成功 {len(results)} / 失败 {len(errors)}")
    if regime:
        print(f"  宏观判定: {regime['regime_name']}  "
              f"growth={regime['growth_score']:+.4f}  inflation={regime['inflation_score']:+.4f}")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
