# 深度登记 gridlab（多采样率遥测对齐与缺口修复）

- 规模：中型（7 个功能模块 / 6 个页面 + base / 63 条测试）
- 核心规则一：**时钟校正与分钟网格**——真值时间 = 采样时刻 − 设备偏移，偏移按 `[effective_from, effective_to)` 解析；同一传感器同一分钟重复按质量位 good > suspect > bad 择一，仍并列取到达较晚的一条；1 分钟桶为 `[t, t+1min)`，15 分钟窗口右端开。
- 核心规则二：**缺口修复与覆盖度**——应有桶按采样率派生；连续缺席 ≤3 桶按传感器声明策略补齐（hold 取前值、linear 按桶距等分）并标 FILLED，>3 桶记 GAP 不插值；窗口覆盖度 = 实有 / 应有，低于 0.8 标 PARTIAL。
- 使用者与工作流：环境监测站数据组每天接手 36 只传感器的 1 / 5 / 15 分钟混合导出件，设备时钟漂移 2–90 秒，报表按 15 分钟汇总；原先用表格手工对齐、缺口靠猜，现在一次导入即得「可采纳样本 + 1 分钟网格 + 补齐与缺口 + 窗口覆盖 + 四账」。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 采样采信 | 导入自带脏样例，看编码回退、分段、列数与原始行号 | POST /api/samples/import、页面 /samples | `app/modules/m1_intake/service.py` `app/modules/m1_intake/reader.py` `app/modules/m1_intake/decode.py` `app/modules/m1_intake/sniff.py` | `tests/test_m1_samples.py` |
| M2 时基契约 | 查传感器规格、采样率、量程与设备偏移区间 | GET /api/timebase | `app/modules/m2_timebase/contract.py` `app/modules/m2_timebase/coerce.py` `app/modules/m2_timebase/offsets.py` | `tests/test_m2_timebase.py` |
| M3 质量隔离 | 看原因码分布与隔离行，导出隔离 CSV | GET /api/quarantine、GET /api/quarantine.csv、页面 /quality | `app/modules/m3_quality/rules.py` `app/modules/m3_quality/quarantine.py` `app/modules/m3_quality/metrics.py` | `tests/test_m3_quality.py` |
| M4 网格对齐 | 看 1 分钟网格、同分钟去重与 15 分钟窗口覆盖 | GET /api/grid、POST /api/grid、页面 /grid | `app/modules/m4_grid/align.py` `app/modules/m4_grid/bucket.py` `app/modules/m4_grid/windows.py` | `tests/test_m4_grid.py` |
| M5 缺口修复 | 看缺口段、补齐值与补齐校验 | GET /api/gaps、POST /api/gaps/repair、页面 /gaps | `app/modules/m5_gaps/fill.py` `app/modules/m5_gaps/repair.py` `app/modules/m5_gaps/policy.py` | `tests/test_m5_gaps.py` |
| M6 批次与对账 | 查批次清单、四账与差异归因 | GET /api/batches、GET /api/reconcile、页面 /batches | `app/modules/m6_batches/compare.py` `app/modules/m6_batches/history.py` `app/modules/m6_batches/diff.py` `app/modules/m6_batches/service.py` | `tests/test_m6_batches.py` |
| M7 导出 | 导出网格、采纳、隔离 CSV 与运行清单，点单元格看证据 | GET /api/export/grid.csv、GET /api/export/manifest.json、GET /api/export/evidence | `app/modules/m7_export/csv_out.py` `app/modules/m7_export/manifest_out.py` `app/modules/m7_export/evidence.py` | `tests/test_m7_export.py` |

端到端：`tests/test_e2e.py`（自带脏样例 → 采信 → 隔离 → 网格 → 缺口 → 四账 → 导出，含 4xx 失败输入与重跑）。
不变量：`tests/test_invariants.py`（行账守恒、网格守恒、幂等重跑、补齐不回流）。

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-03 | 导出件 CRLF 与 LF 混用，某个单元格里带换行 | `splitlines()` 把一条记录切成两条，列数错位 | 用 `csv` 模块按逻辑记录解析，单元格内换行留在字段里 | `app/modules/m1_intake/reader.py` | `tests/test_m1_samples.py::test_trap_03_crlf_and_quoted_newline` |
| TRAP-05 | 某行少一列、某行多一列 | 静默补空值或错列错位 | 严格列数校验，整行进隔离并给原行号与原值 | `app/modules/m1_intake/reader.py` | `tests/test_m1_samples.py::test_trap_05_column_count_mismatch` |
| TRAP-06 | 数值写成 `1,234.5` 或全角 `４.２` | `float()` 抛错或把全角当字符串 | 全角转半角 + 千分位归一后再 Decimal 化，失败给原因码 | `app/modules/m2_timebase/coerce.py` | `tests/test_m2_timebase.py::test_trap_06_thousands_and_fullwidth` |
| TRAP-07 | 空值写成 `-` / `N/A` / `未知` / 空串 | 被当成 0 参与合计，合计虚低 | 哨兵清单集中定义，三态区分，哨兵行隔离且不进合计 | `app/reasons.py`、`app/modules/m3_quality/rules.py` | `tests/test_m3_quality.py::test_trap_07_sentinel_not_zero` |
| TRAP-11 | 同一时刻写成 `2026-03-01T00:00:20Z` 与 `08:00:20+08:00` | 落进两个分钟桶，重复计入 | 先归一 UTC 再取分钟桶 | `app/modules/m2_timebase/coerce.py` | `tests/test_m2_timebase.py::test_trap_11_timezone_offsets_same_bucket` |
| TRAP-12 | 偏移表两段区间同时覆盖同一时刻 | 取到哪段看字典顺序，时钟被校正错 | 区间左闭右开解析，多于一段即判歧义并隔离该行 | `app/modules/m2_timebase/offsets.py` | `tests/test_m2_timebase.py::test_trap_12_offset_overlap_is_ambiguous` |
| TRAP-13 | 迟到 24 分钟的读数在文件尾部才到 | 水位线一推进就丢弃 | 迟到窗口 15 分钟，迟到仍采纳并标 LATE_ARRIVAL | `app/modules/m3_quality/rules.py` | `tests/test_m3_quality.py::test_trap_13_late_still_applied` |
| TRAP-14 | 同一传感器同一分钟两条不同值 | 后写覆盖，保留哪条取决于文件顺序 | 按质量位择一、并列取到达较晚，另一条进重复表并给出双方行号 | `app/modules/m4_grid/align.py` | `tests/test_m4_grid.py::test_trap_14_duplicate_keeps_better_quality` |
| TRAP-16 | 导出件最后一行在中间被截断 | 半行被当有效数据，凭空多一条采样 | 无结尾换行且列数不足即判尾行截断，整行拒绝 | `app/modules/m1_intake/reader.py` | `tests/test_m1_samples.py::test_trap_16_truncated_tail_rejected` |
| TRAP-18 | 0 字节 / 全空行 / 仅表头 三种空态 | 都返回「导入 0 行」，使用者不知道差在哪 | 三种空态分别给 EMPTY_FILE / ALL_BLANK / HEADER_ONLY 结论 | `app/modules/m1_intake/reader.py`、`app/modules/m1_intake/service.py` | `tests/test_m1_samples.py::test_trap_18_three_empty_states` |
| TRAP-23 | 15 分钟窗口端点 00:15:00 归属哪一侧 | 两端都算，同一采样进两个窗口 | 声明左闭右开 `[start, end)`，端点归右窗口 | `app/modules/m4_grid/windows.py` | `tests/test_m4_grid.py::test_trap_23_window_is_half_open` |

## 对账规则

- 行账：`原始行 = 采纳 + 重复 + 隔离`（空行单列，不进任何一项）
- 网格账：`应有桶 = 实有 + 补齐 + 缺口`，应有桶按采样率与全局区间独立派生
- 数值账：`采纳合计 = 实有合计`（补齐值单独统计，不回流采纳合计）
- 窗口账：`应有窗口 = 落库窗口`，窗口按 15 分钟对齐派生
- 四账在 `GET /api/reconcile`、`/batches` 页面与 `manifest.json` 中同时可见；任一账差额非 0 显示「不平」并给出归因提示。

## 反例与不变量

- 反例（朴素实现会挂）：`tests/test_m4_grid.py::test_trap_14_tie_breaks_on_later_arrival`（按文件顺序取第一条会保留 39.5，正确保留迟到的 39.9）、`tests/test_m2_timebase.py::test_naive_local_bucket_differs`（不校正偏移会把 00:15:20 记成 00:15，正确是 00:15:00 减去 20 秒后的 00:15——写成 00:15:20 再取分钟则落到 00:15，看似相同但偏移 90 秒的 PM-02 会整体错位一分）、`tests/test_m1_samples.py::test_naive_splitlines_would_break_records`、`tests/test_m5_gaps.py::test_naive_fill_all_gaps_would_invent_values`（把 10 桶缺口也插值会凭空造 10 个值）。
- 不变量：`tests/test_invariants.py::test_row_account_conserved`（行账守恒）、`tests/test_invariants.py::test_grid_account_conserved`（网格守恒）、`tests/test_invariants.py::test_rerun_is_idempotent`（幂等重跑行数与合计不变）、`tests/test_invariants.py::test_filled_values_do_not_leak_into_accepted`（补齐不回流）。
- 端到端：`tests/test_e2e.py::test_full_pipeline_to_export`。

## 已知不覆盖

- 只处理单站单批次：多站并行时设备偏移表要各自维护，本期按「一个偏移表覆盖全部传感器」实现。
- 补齐策略只有 hold 与 linear 两种；三次样条、按同站相关传感器回归不在本期范围，声明为其他策略会回落到 hold。
- DST 切换日按「偏移表区间重叠即歧义」处理，不做时区数据库推算；偏移表把切换日拆成两段即可表达，重叠则整行隔离。
- 单位换算只覆盖 %RH、µg/m³、ppm、ppb、m/s、hPa 的写法归一，不做量纲换算（例如不把 ppb 折算成 µg/m³）。
- 15 分钟窗口覆盖度按「桶数」计算，不按采样点数；同一分钟内的多次采样在去重阶段已收敛为一条。
