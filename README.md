# gridlab 多采样率遥测对齐与缺口修复

环境监测站的采样流按 1 / 5 / 15 分钟三种采样率混在一起，设备时钟漂移 2–90 秒，
报表按 15 分钟汇总。本服务把原始采样采信、校正到 UTC、按 1 分钟网格对齐、
按声明策略修复小缺口、算 15 分钟窗口覆盖度，并给出可复核的四账与导出。

## 功能模块

| 模块 | 动作 | 入口 |
|---|---|---|
| M1 采样采信 | 导入自带脏样例，逐行诊断编码、分段、列数与原始行号 | `POST /api/samples/import`、页面 `/samples` |
| M2 时基契约 | 查传感器规格、采样率、量程与设备偏移区间 | `GET /api/timebase` |
| M3 质量隔离 | 看原因码分布与隔离行，导出隔离 CSV | `GET /api/quarantine`、页面 `/quality` |
| M4 网格对齐 | 1 分钟网格、同分钟去重、15 分钟窗口覆盖 | `GET /api/grid`、`POST /api/grid`、页面 `/grid` |
| M5 缺口修复 | 缺口段、补齐值、窗口覆盖 | `GET /api/gaps`、`POST /api/gaps/repair`、页面 `/gaps` |
| M6 批次与对账 | 批次清单、四账、差异归因 | `GET /api/batches`、`GET /api/reconcile`、页面 `/batches` |
| M7 导出 | 网格 / 采纳 / 隔离 CSV、运行清单、单元格证据 | `GET /api/export/*` |
| M8 班次交接 | 交接包范围、跨班窗口、保留证据、腾空间判定、确认与回滚 | `POST /api/handovers`、页面 `/handovers` |

## 核心规则

- 真值时间 = 采样时刻 − 设备偏移；偏移表按 `[effective_from, effective_to)` 解析，命中两段即判歧义并隔离。
- 同一传感器同一分钟重复：先按质量位 `good > suspect > bad` 择一，并列取 `ingest_seq` 较大者，再并列取原始行号较大者。
- 1 分钟桶为 `[t, t+1min)`，15 分钟窗口右端开；端点 `00:15:00` 归右窗口。
- 缺口 ≤3 桶按传感器声明策略补齐（`hold` 取前值、`linear` 按桶距等分）并标 `FILLED`；>3 桶记 `GAP` 不插值；`linear` 缺后继锚点记 `EDGE_NO_ANCHOR`。
- 窗口覆盖度 = 实有桶数 / 应有桶数（应有按采样率派生），低于 `0.8` 标 `PARTIAL`。
- 迟到 = 桶早于「已见最大桶 − 15 分钟」，仍采纳，只标 `LATE_ARRIVAL`。
- 跨班窗口：窗口起点不晚于班末且末端越过班末（`start <= 班末 < end`），整窗带进交接包；右端开，末端恰等班末不跨班。
- 交接证据：跨班窗口内每条原始采样独立快照（输入 sha256 + 原始行号 + 原值），快照整体再算 sha256；在线数据腾出后仍可凭快照追回。
- 腾空间判定：仅当交接包已 `CONFIRMED`、交叉复核通过且源批次四账平时才 `RECLAIM_NOW`，否则 `WAIT_EVIDENCE` 并给阻塞原因；只清已被证据覆盖的在线数据。
- 交接状态机 `DRAFT → CONFIRMED → ROLLED_BACK`；同班次同窗口重复交接撞 `shift_key` 唯一约束，复用不重复生成；回滚恢复上一版已确认结果并从快照恢复原始记录。

## 定义与已知不覆盖

字段、单位、精度、空值三态、去重键与空态结论见 `docs/DATA-DICTIONARY.md`；
陷阱登记、反例与不覆盖清单见 `docs/DEPTH.md`。

## 启动

```bash
docker compose up -d --build
curl -s http://127.0.0.1:18203/api/health
```

浏览器打开 `http://127.0.0.1:18203/`，点「导入样例」。

## 演示步骤

1. 首页选「主样例（脏）」与「设备偏移表」，点「导入样例」。
2. `/samples` 看编码回退、分段、列映射与偏移区间。
3. `/quality` 看 7 类原因码与隔离行，点「隔离 CSV」下载。
4. `/grid` 看 110 个网格点的实有 / 补齐 / 缺口分布，点任意单元格看证据。
5. `/gaps` 看缺口段与 14 个窗口的覆盖度。
6. `/batches` 看四账与四个导出文件。
7. `/handovers` 填班次日界（如 `2026-03-01T00:00:00Z` 起、`2026-03-01T00:15:00Z` 止）生成交接包，看跨班窗口与保留证据；确认后才能腾空间，回滚可恢复旧版结果与原始记录。

## 测试

```bash
docker compose exec -T app python -m pytest -q
```

## 目录

```
app/main.py config.py errors.py reasons.py manifest.py store.py web.py
app/modules/m1_intake … m8_handover
app/templates  base.html + 7 页
app/static     theme.css layout.css components.css app.js table.js grid.js handover.js
docs/          DEPTH.md DATA-DICTIONARY.md RUNBOOK.md
sample_data/   11 个自带样例 + 1 个偏移表
tests/         每模块 1 个测试文件 + e2e + invariants
```
