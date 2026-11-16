# 定义契约 gridlab

## 采样行

| 列 | 类型 | 单位 | 可空 | 说明 |
|---|---|---|---|---|
| `sensor_id` | 字符串 | — | 否 | 契约表内的传感器编号，区分大小写 |
| `sampled_at` | ISO8601 | — | 否 | 设备时钟记录的绝对时刻，可带 `Z` 或 `+08:00` |
| `offset_seconds` | 整数 | 秒 | 是 | 设备自报的时钟偏移，只作对照；真值以偏移表为准 |
| `value` | 十进制 | 见单位列 | 是 | 允许千分位与全角数字；空值哨兵见下 |
| `unit` | 字符串 | — | 否 | 写法归一后必须等于契约单位 |
| `quality` | 枚举 | — | 是 | `good` / `suspect` / `bad`，缺省按 `good` |
| `ingest_seq` | 整数 | — | 是 | 到达顺序，缺省用原始行号 |

## 数值

- 一切用量走 `Decimal`，落库以字符串保存，最小刻度 `0.001`；对外 JSON 也是字符串，禁止 float 往返。
- 补齐值按 `0.001` 四舍五入（`ROUND_HALF_UP`），锚点值原样保留。
- 覆盖度保留 `0.001`，页面按百分比显示一位小数。

## 时间

- 存储与计算一律 UTC，秒级，格式 `YYYY-MM-DDTHH:MM:SSZ`。
- 页面显示 `+08:00`，导出 CSV 同时给 UTC 与 `+08:00` 两列。
- 分钟桶：`[t, t+1min)`；跨日不特殊处理，`23:59:30` 落到当日 `23:59` 桶。
- 15 分钟窗口：`[w, w+15min)`，右端开；端点 `00:15:00` 属于 `[00:15, 00:30)`。

## 偏移与质量

- 偏移表条目为 `[effective_from, effective_to)`；同一传感器同一时刻命中两段即 `OFFSET_AMBIGUOUS`，该行隔离。
- 无条目时按行内 `offset_seconds`（缺省 0）校正，并标 `OFFSET_ASSUMED`。
- 表内偏移与行内偏移不一致时以表为准，标 `OFFSET_CONFLICT`，不隔离。

## 空值三态

| 写法 | 含义 | 处理 |
|---|---|---|
| 字段缺失 / 空串 | 未采集 | 隔离，原因码 `SENTINEL_VALUE` |
| `-` `--` `N/A` `null` `未知` `空` `无` | 哨兵 | 隔离，原因码 `SENTINEL_VALUE` |
| `0` | 真实零值 | 采纳，进合计 |

哨兵清单只在 `app/config.py` 定义一次。

## 去重键

- 去重键为 `(sensor_id, 分钟桶)`，不是全行哈希：同一分钟内的两次采样代表同一物理时刻，必须收敛为一条。
- 择一顺序：质量位 `good > suspect > bad` → `ingest_seq` 较大者 → 原始行号较大者；全序且与文件顺序无关。
- 未保留的一条进重复表，保留双方行号与数值，供人工复核。

## 空态

| 输入 | 结论码 | 含义 |
|---|---|---|
| 0 字节 | `EMPTY_FILE` | 文件是空的 |
| 只有空行 | `ALL_BLANK` | 没有任何表头与数据 |
| 仅表头 | `HEADER_ONLY` | 声明了列但没有数据行 |

三种空态都会生成批次，四账按 0 对 0 判平，结论码显示在总览页。

## 班次交接（M8）

### 交接状态机

| 状态 | 含义 | 可执行动作 |
|---|---|---|
| `DRAFT` | 已起草，窗口与证据已快照，尚未确认 | 确认；不能腾空间 |
| `CONFIRMED` | 交叉复核通过且已确认，结果可作为发布依据 | 腾空间、回滚 |
| `ROLLED_BACK` | 交接失败已回滚，上一版结果恢复 | 不可复活，需重新起草 |

### 交接表

| 表 | 粒度 | 关键列 | 说明 |
|---|---|---|---|
| `handovers` | 一个班次一行 | `handover_id`、`shift_key`（唯一）、`state`、`previous_id`、`scope_json`、`checks_json` | `shift_key` 由源批次 + 班次日界确定性派生，撞键即复用，保证同班次不重复生成 |
| `handover_windows` | 交接包 × 传感器 × 窗口 | `cross_shift`、`observed`、`retained` | 跨班窗口整窗保留；`retained` 是该窗保留的原始采样数 |
| `handover_evidence` | 跨班窗口内每条原始采样 | `source_row`、`value`、`sample_sha256`、`window_start` | 独立快照，不依赖源批次在线表是否被清理 |
| `handover_events` | 交接事件 | `seq`、`event`、`actor` | `PREPARED / CONFIRMED / RECLAIMED / ROLLED_BACK` 审计轨迹 |

### 跨班与腾空间口径

- 跨班判据：`窗口起点 <= 班末 < 窗口末端`；窗口右端开，末端恰等班末不算跨班。
- 腾空间只删除「班末之外」且「在 `handover_evidence` 中有同传感器同桶快照」的在线采样，以及班末之外的 grid/windows；班内数据与全部交接表保留。
- 交叉复核：每个有 `observed > 0` 的跨班窗口，其 `retained` 必须等于 `observed`；`observed = 0` 的空窗口允许零证据。复核不过则交接停在 `DRAFT`，腾空间判定为 `WAIT_EVIDENCE`。
- 证据快照摘要 `evidence_digest` 是对全部证据行规范 JSON 的 sha256，任一行被改即变。
