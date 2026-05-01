# Cross-Asset & Gold Soros Dashboards

跨资产监控 + 黄金索罗斯反身性框架 · GitHub Actions 自动更新

## Live Demo

**https://xubinqiang2012-glitch.github.io/cross-asset-dashboard/**

## 两个仪表板

| 仪表板 | 内容 | 数据源 |
|---|---|---|
| **Cross-Asset Monitor** | 21 个资产（股票/利率/商品/外汇/加密/波动率）· All Weather 四象限· 8 家机构观点 | Yahoo Finance · Google News · Fed |
| **Gold Soros Framework** | 黄金 6 变量周度追踪 · Boom-Bust 八阶段 · 反身性回路 | Stooq · FRED · WGC |

## 自动更新

GitHub Actions 工作日每 2 小时跑一次（`.github/workflows/update.yml`），周末每 6 小时：

```text
update_assets.py     → assets-data.json
update_commentary.py → commentary-data.json
update_data.py       → gold-data.json
```

变化的 JSON 自动 commit 回仓库，GitHub Pages 立刻反映。

### 可选：FRED API Key

黄金仪表板的"美债 10Y 实际利率 (DFII10)"需要 FRED API key（免费）：

1. 在 https://fred.stlouisfed.org/docs/api/api_key.html 申请（30 秒）
2. 仓库 Settings → Secrets and variables → Actions → New repository secret
3. Name: `FRED_API_KEY`，Value: 粘贴 key

不配置也能用，只是 real_yield 字段会为空。

## 本地开发

```bash
python3 update_assets.py     # 拉资产
python3 update_commentary.py # 拉机构观点
python3 update_data.py       # 拉黄金指标 (FRED_API_KEY=xxx 可选)
python3 -m http.server 8765
# 访问 http://localhost:8765/
```

## 文件清单

```
├── index.html                    入口
├── cross-asset-dashboard.html    主仪表板
├── gold-soros-dashboard.html     黄金索罗斯框架
├── update_assets.py              资产数据拉取（Yahoo Finance）
├── update_commentary.py          机构观点拉取（RSS）
├── update_data.py                黄金 6 变量（Stooq + FRED）
├── assets-data.json              ← 自动生成
├── commentary-data.json          ← 自动生成
├── gold-data.json                ← 自动生成
└── .github/workflows/update.yml  GitHub Actions
```
