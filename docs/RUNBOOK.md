# 运行手册 gridlab

## 启动

```bash
docker compose up -d --build
curl -s http://127.0.0.1:18203/api/health
open http://127.0.0.1:18203/
```

首页点「导入样例」即可跑通主流程；批次与四账在 `/batches`。

## 重置批次库

```bash
docker compose down -v --remove-orphans
docker compose up -d --build
```

命名卷 `gridlab-data` 承载 `/app/data/gridlab.db`，删除卷即清空全部批次。

## 容器内测试

```bash
docker compose exec -T app python -m pytest -q
```

## 自带样例

| key | 文件 | 用途 |
|---|---|---|
| `telemetry_raw` | `sample_data/telemetry_raw.csv` | 主脏样例：编码 BOM、换行混用、重复键冲突、越界、哨兵、单位不符、迟到、偏离采样率、契约外传感器 |
| `gap_series` | `sample_data/gap_series.csv` | 2 桶线性补齐与 2 桶边缘缺锚的精确算术 |
| `midnight_edge` | `sample_data/midnight_edge.csv` | 跨日桶与 15 分钟窗口右端开 |
| `offset_overlap` | `sample_data/offset_overlap.csv` | 偏移区间重叠导致整行隔离 |
| `column_count` | `sample_data/column_count.csv` | 少列与多列 |
| `truncated_tail` | `sample_data/truncated_tail.csv` | 尾行截断 |
| `header_only` | `sample_data/header_only.csv` | 仅表头 |
| `blank_rows` | `sample_data/blank_rows.csv` | 全空行 |
| `crlf_quoted` | `sample_data/crlf_quoted.csv` | CRLF、引号内换行、重复表头分段 |
| `gb18030` | `sample_data/telemetry_gb18030.csv` | GB18030 与中文表头 |
| `empty` | `sample_data/empty_sample.csv` | 0 字节 |

偏移表固定用 `device_offsets.csv`；其中 `AM-06` 故意留两段重叠区间。

## 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| POST | `/api/samples/import` | 导入样例，body `{"sample": "...", "offsets": "device_offsets"}` |
| GET | `/api/samples` | 最近批次的采信元信息 |
| GET | `/api/timebase` | 传感器契约与偏移表 |
| GET | `/api/quarantine` | 隔离行与原因分布 |
| GET | `/api/quarantine.csv` | 隔离 CSV |
| GET | `/api/grid` | 网格点摘要 |
| POST | `/api/grid` | 从采纳行重新推导网格并逐点比对 |
| GET | `/api/gaps` | 缺口段与窗口覆盖 |
| POST | `/api/gaps/repair` | 从采纳行重新推导缺口并与落库比对 |
| GET | `/api/batches` | 批次清单 |
| GET | `/api/reconcile` | 四账 |
| GET | `/api/export/grid.csv` | 网格 CSV |
| GET | `/api/export/accepted.csv` | 采纳 CSV |
| GET | `/api/export/quarantine.csv` | 隔离 CSV |
| GET | `/api/export/manifest.json` | 运行清单 |
| GET | `/api/export/evidence` | 单元格证据，参数 `sensor_id` 与 `bucket` |
| POST | `/api/handovers` | 起草班次交接包，body `{"shift_date": "...", "shift_end": "..."}`（`shift_end` 可省，默认 +1 天） |
| GET | `/api/handovers` | 交接包清单 |
| GET | `/api/handovers/{id}` | 单个交接包（范围、窗口、证据、事件） |
| POST | `/api/handovers/{id}/confirm` | 确认交接（DRAFT → CONFIRMED） |
| GET | `/api/handovers/{id}/reclaim` | 腾空间判定：`RECLAIM_NOW` 或 `WAIT_EVIDENCE`（带阻塞原因） |
| POST | `/api/handovers/{id}/reclaim` | 执行腾空间，只清已被证据覆盖的在线数据 |
| POST | `/api/handovers/{id}/rollback` | 交接失败回滚，恢复上一版结果与原始记录 |
| GET | `/api/handovers/{id}/windows` | 交接包窗口（含跨班标记与保留采样数） |
| GET | `/api/handovers/{id}/evidence` | 保留证据快照，可加 `limit` |

## 常见失败

| 现象 | 原因 | 处理 |
|---|---|---|
| 409 `STATE_CONFLICT` | 偏移表被改动后与既有批次冲突 | 改回偏移表，或删除命名卷按新表重跑 |
| 400 `HEADER_MISSING` | 输入列名不在别名表内 | 在 `app/modules/m1_intake/sniff.py` 的别名表补一条 |
| 404 `RUN_NOT_FOUND` | 指定了不存在的批次号 | 省略 `run_id` 参数即取最近批次 |
| 四账「不平」 | 有人改了落库行 | 用 `POST /api/grid` 与 `POST /api/gaps/repair` 重新推导比对，差额在 `/batches` 可见 |
| 400 `SHIFT_BOUND_INVALID` | 班次日界不是合法 ISO8601 | 用 `YYYY-MM-DD` 或 `YYYY-MM-DDTHH:MM:SSZ`，终点必须晚于起点 |
| 400 `SHIFT_WINDOW_EMPTY` | 班次范围内没有任何 15 分钟窗口 | 扩大班次范围或换一个覆盖到数据的日界 |
| 409 `HANDOVER_CHECK_FAILED` | 窗口登记实有桶与保留证据对不上 | 在 `/handovers` 看「交叉复核」的差额行，先补齐证据再确认 |
| 409 `RECLAIM_BLOCKED` | 交接包未确认 / 复核未过 / 四账不平 | 按 `blockers` 逐项处理，判定回到 `RECLAIM_NOW` 再腾空间 |
| 409 `HANDOVER_ROLLED_BACK` | 对已回滚的交接包再次确认 | 回滚包不可复活，按同一班次日界重新起草新交接包（复用快照） |
| 在线数据已被腾出 | 交接包确认后执行了 reclaim | 用 `POST /api/handovers/{id}/rollback`，原始采样从证据快照逐条恢复 |
