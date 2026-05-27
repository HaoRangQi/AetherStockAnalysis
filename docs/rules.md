# 规则说明

本文档说明当前 MVP 已落地的分析规则、参数含义和人工优先边界。当前规则用于本地研究和复盘辅助，不输出交易建议，也不代表唯一结构结论。

## 缠论分型 / 笔 / 线段 / 中枢 MVP

- 算法：`chan-fractal`
- 版本：`0.5.0`
- 输出：顶分型 / 底分型点、笔线段、线段候选、中枢候选

当前分型规则先执行 K 线包含关系预处理，再使用 3 根 K 线窗口：

- 当相邻 K 线出现包含关系时，根据前一段走势方向合并高低点。
- 上行合并取较高高点和较高低点；下行合并取较低高点和较低低点。
- 合并后的分型点仍回指产生该极值的原始 K 线 `index` 和 `trade_date`，便于图表定位和回测 next-bar 执行。

- 顶分型：中间 K 线高点同时高于前一根和后一根 K 线高点。
- 底分型：中间 K 线低点同时低于前一根和后一根 K 线低点。

当前接口返回参数：

- `strict_fractal=false`：当前没有启用更严格的分型过滤。
- `include_containment=true`：当前会先做相邻 K 线包含关系处理。
- `window=3`：当前只使用前中后三根 K 线判断分型。
- `min_bars_for_bi=5`：当前笔 MVP 要求相邻有效顶底分型间隔不少于 5 根 K 线。
- `min_bis_for_segment=3`：当前线段 MVP 使用连续 3 笔生成一个候选线段。
- `segment_step_bis=3`：当前候选线段按 3 笔窗口非重叠推进。
- `min_bis_for_zhongshu=3`：当前中枢 MVP 使用连续 3 笔价格区间重叠生成候选。
- `zhongshu_step_bis=1`：当前中枢候选按 1 笔步长滑动扫描。

当前笔规则：

- 从分型序列中保留交替出现的顶 / 底分型。
- 连续同类分型只保留更极端的点：顶分型保留更高点，底分型保留更低点。
- 顶底分型间隔少于 `min_bars_for_bi` 时不生成新笔端点。
- 笔方向由端点分型类型决定：底分型到顶分型为 `up`，顶分型到底分型为 `down`。

当前线段规则：

- 每个线段候选由连续 3 笔组成。
- 线段起点使用窗口第一笔起点，终点使用窗口最后一笔终点。
- 线段方向跟随窗口最后一笔方向。
- 当前按非重叠 3 笔窗口生成候选，避免图表连线回跳。

当前中枢规则：

- 每个中枢候选由连续 3 笔组成。
- 每笔区间取起止价格的低点和高点。
- 三笔区间的重叠部分作为中枢区间：`low=max(三笔低点)`，`high=min(三笔高点)`。
- 当 `low <= high` 时输出中枢候选，并记录 `mid=(low+high)/2`。
- 当前前端以中枢上下沿两条线显示候选区间。

当前边界：

- 尚未实现标准线段破坏、特征序列和中枢扩展 / 合并。
- 分型、笔、线段和中枢结果会随图表加载窗口变化而重新计算。

## 波浪 ZigZag 候选

- 算法：`wave-zigzag`
- 版本：`0.1.0`
- 输出：ZigZag pivot 和 W 编号

当前 ZigZag 规则按反向波动阈值确认候选高低点，并要求相邻候选 pivot 至少间隔 `min_swing_bars` 根 K 线。前端提供三档浪级：

- 细浪：`threshold_pct=3`
- 标准：`threshold_pct=5`
- 大浪：`threshold_pct=8`

阈值越小，候选波段越细；阈值越大，候选波段越粗。`min_swing_bars` 越大，越会过滤短距离来回震荡。该结果只作为波浪理论辅助候选，不判断唯一浪型。

当前边界：

- 不自动推导完整 1-5 / A-B-C 结构。
- 不处理多条候选路径评分。
- 不输出买卖建议。

## 人工优先规则

人工缠论结构通过 `annotations` 表保存：

- `overlay_type="chan"`
- `payload.active != false`
- `payload.fractals`、`payload.bis`、`payload.segments`、`payload.zhongshu` 至少有一项为有效列表

当存在符合条件的人工缠论结构时，前端会使用 `manual-chan` 结果覆盖自动缠论结构显示。若最新 active 人工缠论结构无法解析，后端会继续回退到次新的可解析 active 记录；没有可解析人工结构时才回退自动结构。恢复自动缠论时，前端会把当前人工缠论结构标记为 `active=false`，自动结构重新生效。

同一标的和周期下，后端会保证 `chan` 人工覆盖只有一条 active 记录。保存或重新激活新的人工缠论结构时，旧的 active 人工缠论结构会自动写入 `active=false` 和失活原因，避免图表、回测、备份中出现多个同时生效的缠论覆盖。

人工缠论启用后，前端可对 `payload.fractals` 执行最小人工修正：

- 切换单个分型的 `kind`：`top` 与 `bottom` 互换。
- 删除单个分型，至少保留 2 个分型作为后续派生笔的基础。
- 新增 `top` / `bottom` 人工分型：先在缠论面板选择“添加顶分型”或“添加底分型”，再点击 K 线图选择 `trade_date` 和 `price`；如果同一根 K 线已有人工分型，新点会替换旧点。
- 后端解析人工分型时支持输入兼容：`kind=high/low` 会归一为 `top/bottom`；`index` / `price` 支持数字字符串（如 `"3"`、`"12.5"`），便于导入手工编辑的数据；`trade_date` 支持日线日期和分钟时间戳（如 `2026-06-02`、`2026-06-02T09:35`、`2026-06-02T09:35:00Z`、`2026-06-02T09:35:00+08:00`、`2026-06-02T09:35:00+08`、`2026-06-02T10:00:00-0530`、`2026-06-02T10:00:00-05`），会自动去除首尾空白并规范化；`+8` / `-5` 这类单数字小时偏移视为非法输入并会被忽略；空白或非法日期（如 `2026-06-31`）分型会被忽略。
- 修改分型后会清空旧的 `bis`、`segments` 和 `zhongshu`，避免笔、线段、中枢继续引用已经不一致的分型结构。
- 后端读取只有人工分型的 `overlay_type="chan"` 标注时，会按标注内 `params` 或默认缠论规则重新派生笔、线段和中枢，并在返回参数中标记 `derived_from_manual_fractals=true`。
- 工作台分析面板和复盘报告会显示“人工分型派生”证据，以及当前分型、笔、线段和中枢数量，便于确认图表与回测确实来自人工修正后的结构。
- 每次修正会更新同一条 `overlay_type="chan"` 标注的 `fractals`、`edited_at` 和 `structure_reset_reason`，因此用户数据备份和缠论结构回测人工优先都会读取最新人工分型和派生结构。

人工浪型通过 `annotations` 表保存：

- `overlay_type="wave"`
- `payload.active != false`
- `payload.pivots` 为有效 pivot 列表

当存在符合条件的人工浪型时，前端会使用 `manual-wave` 结果覆盖自动 ZigZag 候选显示。若最新 active 人工浪型无法解析，后端会继续回退到次新的可解析 active 记录；没有可解析人工结构时才回退自动候选。恢复自动候选时，前端会把当前人工浪型标记为 `active=false`，自动候选重新生效。

同一标的和周期下，后端会保证 `wave` 人工覆盖只有一条 active 记录。保存或重新激活新的人工浪型时，旧的 active 人工浪型会自动写入 `active=false` 和失活原因，确保人工优先来源唯一。

人工浪型启用后，前端可对 `payload.pivots` 执行最小改浪：

- 切换单个浪点的 `kind`：`top` 与 `bottom` 互换，`start` 起点不参与切换。
- 删除单个浪点，并按原始 K 线 `index` 重新生成连续 `wave_no`。
- 新增 `top` / `bottom` 人工浪点：先在波浪面板选择“添加高点”或“添加低点”，再点击 K 线图选择 `trade_date` 和 `price`，前端会把该点追加到当前人工浪型并按 K 线 `index` 重新编号。
- 后端解析人工浪点时支持输入兼容：`kind=high/low` 会归一为 `top/bottom`；`index` / `price` / `wave_no` / `threshold_pct` 支持数字字符串（如 `"3"`、`"8.5"`）；`trade_date` 支持日线日期和分钟时间戳（如 `2026-06-02`、`2026-06-02 09:40`、`2026-06-02T09:40:00Z`、`2026-06-02T09:40:00+08:00`、`2026-06-02T09:40:00+08`、`2026-06-02T10:00:00-0530`、`2026-06-02T10:00:00-05`），会自动去除首尾空白并规范化；`+8` / `-5` 这类单数字小时偏移视为非法输入并会被忽略；空白或非法日期（如 `2026-13-01`）浪点会被忽略；`wave_no` 仍要求为正整数，缺失或非法会被视为无效浪点；`threshold_pct` 会被钳制到 `0.1~50`，非有限值（`NaN` / `Infinity`）会回退到本次请求阈值。
- 每次改浪会更新同一条 `overlay_type="wave"` 标注的 `pivots` 和 `edited_at`，因此用户数据备份和回测人工优先都会读取最新人工浪型。

普通人工标注和复盘笔记会记录生成时的算法版本。当前图表分析版本与标注记录版本不一致时，界面会提示“需复核”。普通人工标注可在编辑模式中选择后点击 K 线图移动 `trade_date` / `price` 锚点，也可以按住图表拖拽到目标位置后松开完成定位；锁定标注以及 `chan` / `wave` 结构化覆盖不允许移动普通锚点。

## 导入任务恢复规则

导入任务用于支撑“本地保存 + 可恢复追踪”流程，相关规则如下：

- 任务状态支持 `queued` / `running` / `succeeded` / `failed`；列表查询额外支持 `status=pending`，等价于 `queued + running`，用于筛选“仍在执行中的任务”。
- 列表和详情返回 `source_path_exists`，表示任务记录中的 `source_path` 在当前本机是否仍存在：`true` 为存在，`false` 为失效，`null` 表示任务未记录可检查路径。
- 列表查询支持 `source_path_exists=true|false`，便于直接筛选“路径失效任务”并触发用户修复数据源路径。
- 应用重启后，若本地仍有遗留 `queued` / `running` 记录，后端会在查询阶段自动标记为 `failed`，并写入“导入任务已中断，请重新发起导入。”，避免界面长期停留在运行态。
- 前端重试失败任务时遵循“先校验路径再执行”：
  - 缺少 `source_path`：提示无法直接重试并聚焦路径输入框。
  - `source_path_exists=false`：提示“原任务路径已失效”，引导先更新路径再重试。
  - 路径可用：允许直接复用原路径重试。

## 规则配置和分析方案

`rule_profiles` 保存缠论 / 波浪规则配置，当前默认配置包括：

- `chan`：`strict_fractal=false`、`include_containment=true`、`min_bars_for_bi=5`、`min_bis_for_segment=3`、`min_bis_for_zhongshu=3`
- `wave`：`zigzag_threshold_pct=5.0`、`min_swing_bars=3`

当前默认 `chan` 规则会参与缠论自动分析、图表分析和缠论结构回测，当前默认 `wave` 规则会参与未显式指定浪级的波浪分析、图表分析和波浪结构回测。工作台或接口显式传入 `threshold_pct` 时，用户当前选择优先于默认 `wave` 规则。分析方案导入 / 导出会迁移规则配置和前端工作台偏好，不包含行情缓存、人工标注或复盘笔记；其中回测参数导出使用 `limit_pct` 等 snake_case 字段，导入时兼容 `limitPct` 等同义 camelCase 字段，便于手工编辑或迁移旧方案。`selected_symbol`、`date_start` 和 `date_end` 显式为 `null` 时会清空对应工作台状态，字段缺失或非法时保持当前状态；若同时提供且出现 `date_start > date_end`，导入时会自动纠正为有效区间。旧方案缺少新增图层开关时，导入后会按当前默认显示新增图层，避免兼容导入后看不到新增分析结果。`workspace.layers` 导入兼容布尔字面量及常见布尔字符串/数字（`true` / `false`、`1` / `0`）；工作台图层开关也会持久化到本地 `localStorage` 并在刷新后恢复。工作台当前标的、当前周期、日期范围与“是否手动触碰日期范围”状态也会持久化到本地 `localStorage` 并在刷新后恢复，日期值恢复时也会自动去除首尾空白后再校验。分析方案 `workspace` 还支持导入 / 导出 `date_range_touched`（兼容 `dateRangeTouched`），用于保留该“是否手动触碰日期范围”状态；字段缺失或非法时保持现有行为，仅在本次导入包含非空且合法的日期边界时，默认视为已手动触碰。`workspace.manual_lines` 也支持导入 / 导出（兼容 `manualLines`）：显式传 `null` 时会清空当前手工划线，字段缺失或非法时保持当前状态；数组元素支持 `start.trade_date` / `end.trade_date`（兼容 `tradeDate`）和 `created_at`（兼容 `createdAt`）。`selected_symbol` 对象内部日期/数量字段导入时兼容 `first_date` / `last_date` / `bar_count` 与同义 camelCase（`firstDate` / `lastDate` / `barCount`）。回测参数中的 `apply_limit_constraints` / `applyLimitConstraints` 除布尔字面量外，也兼容常见布尔字符串和数字（`true` / `false`、`1` / `0`）。分析方案 `workspace` 还支持保存和恢复 `active_panel`（`workbench` / `data` / `layers` / `review` / `settings`）与 `import_job_filter`（`all` / `pending` / `failed` / `succeeded` / `broken`），并兼容同义 camelCase 字段 `activePanel` / `importJobFilter`，用于恢复工作台当前操作上下文；这些字段导入时会自动去除首尾空白并按大小写不敏感匹配，字段缺失或非法时保持当前状态。本地 `localStorage` 恢复时也兼容 `active_panel` / `import_job_filter` 键。`workspace.theme` 也支持相同的空白清理和大小写不敏感匹配（`light` / `dark`）。规则配置中的 `analysis_type` 仅支持 `chan` / `wave`；导入规则时会按 `analysis_type` 替换该类型下原有规则，非法值会被接口拒绝（`422`）。备份导入里的标注 `id` 和 `overlay_type` 不能为空白字符串，否则导入返回 `400`；其中 `overlay_type` 会去除首尾空白后写入本地标注。若用户备份导入中的标注列表出现重复 `id`，后出现的标注会覆盖前一条同 `id` 记录再导入。若导入规则列表中出现重复 `id`，后出现的规则会覆盖前一条同 `id` 记录再导入；但同一个规则 `id` 不能跨 `chan` / `wave` 复用，且 `id` 不能为空白字符串，否则导入返回 `400`。备份导入返回 `annotations_imported` / `rule_profiles_imported`，分析方案导入返回 `rule_profiles_imported`，这些计数字段都表示去重覆盖后的实际导入数量。若导入后某类型没有默认规则，后端会自动把该类型里 `updated_at` 最新的一条设为默认；时间并列时按 `id` 倒序稳定选择默认规则。

## 轻量回测证据

结构回测不只返回交易列表，还会在 `params` 中记录本次信号依据：

- `strategy_condition_key` / `strategy_condition`：策略条件标识和中文说明。
- `structure_counts`：本次使用的结构数量。缠论策略包含分型、笔、线段和中枢数量；波浪策略包含浪点、高点和低点数量。
- `signal_count`、`entry_signal_count`、`exit_signal_count`：候选信号总数、买点数量和卖点数量。
- `source_algorithm` / `source_version` / `structure_source`：自动或人工结构来源，以及生成该结构的算法版本。
- `apply_limit_constraints` / `limit_pct` / `limit_rule`：是否启用涨跌停约束、使用的涨跌停幅度，以及 `prev_close_*pct` 形式的前收盘价近似规则；`limit_pct` 支持科学计数法写法（如 `1e1`、`1E1`、`%2B1e1`、`%2B1E1`），`NaN/Infinity` 等非有限值会被接口拒绝（`422`）。
- `equity_curve`：按每笔交易退出点记录净值、累计收益和当前回撤，用于复核 `summary.max_drawdown_pct` 的来源。
- `summary`：除交易数、胜率、收益和最大回撤外，还记录平均持仓、最短持仓、最长持仓和中位持仓 K 线数量。

前端回测面板、K 线图“回测买卖点”图层、复盘报告和回测 CSV 会展示这些字段，便于复核“本次收益来自哪些结构和触发规则”，而不是只看最终收益统计。买卖点图层使用回测交易的 `entry_trade_date` / `entry_price` 和 `exit_trade_date` / `exit_price` 定位，卖点标签会附带单笔收益。工作台可显式启用涨跌停约束，并通过 `limitPct` 保存前端输入；接口使用 `limit_pct`，默认 10，允许 0.1-30，返回 `params.limit_rule=prev_close_*pct`。启用后按前一交易日收盘价和配置幅度近似识别涨跌停，涨停日跳过买入、跌停日跳过卖出，区间末尾仍跌停的持仓不会强制闭合，并会在 `params.open_position` 中记录未闭合持仓的入场、最新 K 线、持仓 K 数和原因；关闭约束时 `skipped_limit_up_entries` 与 `skipped_limit_down_exits` 固定为 `0`。Markdown 复盘报告会记录建议同步导出的截图、CSV 和备份文件；当存在未闭合持仓时，即使没有闭合交易，也会提示可导出 `row_type=open_position` 的 CSV，并在轻量回测摘要中列出未闭合持仓。报告会在人工标注、浪点、交易或复盘笔记被摘要截断时提示剩余数量。CSV 导出会额外写入策略中文名、策略条件、信号中文名、结构来源、来源算法版本、结构用量、信号计数、执行参数、独立成本 / 仓位 / 涨跌停参数列、持仓周期统计和逐笔权益 / 回撤；`row_type=open_position` 的行会记录未闭合持仓，便于离线复盘或本地迁移。
