# API 端点

基础地址：`http://127.0.0.1:8000/api`。

## 健康检查

- `GET /health`
- 返回：`{"status":"ok"}`

## 数据源

- `GET /sources/detect`
  - 探测 CrossOver、Windows 和 macOS 容器候选 `vipdoc` 目录。
- `GET /sources/current`
  - 返回当前配置的数据源；没有配置时返回第一个有效探测结果。
  - 若配置中的 `source_path` 含首尾空白，后端会去空白后再解析；若去空白后为空，按“未配置”处理并回退自动探测。
  - 若配置路径可解析但无日线数据，后端会继续尝试回退自动探测有效候选；只有没有可用探测结果时，才返回该配置路径并标记 `valid=false`。
  - 返回的 `path` 与 `health.path` 都会规范化为绝对路径（展开 `~` 并解析相对段）。
  - 自动探测候选需要同时满足 `exists=true` 且 `valid=true`；若 `path` 为空白字符串，或候选自报有效但实时检查无日线数据，也会被忽略。
- `POST /sources`
  - 请求：`{"path":"/path/to/vipdoc"}`
  - 保存用户指定的通达信数据源。
  - `path` 不能为空白字符串；空值或仅空白字符返回 `400`。
  - `path` 若是非法路径字符串（例如包含 NUL 字符）返回 `400`（`数据源路径无效。`）。
  - 显式传入 `path` 时，后端会去除首尾空白并规范化为绝对路径（展开 `~` 并解析相对段）后再校验与保存。

## 导入

- `POST /imports/daily`
  - 请求：`{"path": null, "markets": ["sh", "sz", "bj"], "limit_files": null}`
  - `path` 为 `null` 时会回退到已保存数据源或自动探测结果；`path` 不能为空白字符串，空值或仅空白字符返回 `400`。
  - `path` 为 `null` 时，数据源选择优先级为：已保存数据源（可解析且包含可导入日线）-> 自动探测有效候选；若已保存数据源无效（例如路径非法或无日线）会继续回退自动探测。
  - 显式传入 `path` 时不会回退自动探测：若该路径无日线数据，直接返回 `400`（`数据源无效：没有找到可导入的日线文件。`）。
  - 显式传入 `path` 时，后端会去除首尾空白并规范化为绝对路径（展开 `~` 并解析相对段）后再校验导入。
  - 使用回退数据源时，后端会把最终 `source_path` 规范化为绝对路径（展开 `~` 并解析相对段）。
  - 自动探测候选里若存在 `exists=false`、`valid=false`、`path` 为空白，或候选自报有效但实时检查无日线数据的记录，会忽略这些记录并继续寻找下一个有效候选。
  - 若 `path` 为 `null` 且本地未配置数据源、自动探测也没有有效候选，返回 `400`。
  - `markets` 会做去空白、小写化和去重，支持值仅 `sh` / `sz` / `bj`；若包含不支持值或清洗后为空返回 `400`。
  - `limit_files` 若传入必须是正整数（`>=1`）；非正数返回 `422`。
  - 解析 `lday/*.day`、`minline/*.lc1`、`fzline/*.lc5` 并写入 DuckDB。
  - 日线导入时按 `symbol + trade_date` 去重；分钟线导入时按 `symbol + interval_minutes + trade_time` 去重。
  - 返回 `files_seen`、`files_imported`、`bars_imported`、`minute_files_seen`、`minute_files_imported`、`minute_bars_imported`、`symbols_imported` 和错误列表。
  - `bars_imported` / `minute_bars_imported` 表示本次导入流程处理到的 K 线条数，不等同于“新写入条数”；重复导入同一数据时，底层仍会按主键去重，缓存总行数不会重复增长。
  - 响应示例：
    ```json
    {
      "source_path": "/data/vipdoc",
      "files_seen": 12,
      "files_imported": 12,
      "bars_imported": 14520,
      "minute_files_seen": 8,
      "minute_files_imported": 6,
      "minute_bars_imported": 38640,
      "symbols_imported": 18,
      "errors": []
    }
    ```
  - 其中 `minute_files_seen` 表示扫描到的分钟文件数量，`minute_files_imported` 表示通过解析并参与写入流程的分钟文件数量。
- `POST /imports/jobs`
  - 请求同 `/imports/daily`，`path` / `markets` / `limit_files` 使用同样的参数校验；无效数据源会在请求阶段直接返回 `400`，通过校验后才返回后台导入任务。
  - `path` 为 `null` 时，数据源选择优先级同 `/imports/daily`：已保存数据源（可解析且包含可导入日线）-> 自动探测有效候选；配置数据源无效时会回退自动探测。
  - 显式传入 `path` 时不会回退自动探测：若该路径无日线数据，直接返回 `400`（`数据源无效：没有找到可导入的日线文件。`）。
  - 显式传入 `path` 时，后端会去除首尾空白并规范化为绝对路径（展开 `~` 并解析相对段）后再校验导入。
  - 使用回退数据源时，任务记录中的 `source_path` 会规范化为绝对路径（展开 `~` 并解析相对段）。
  - 自动探测候选里若存在 `exists=false`、`valid=false`、`path` 为空白，或候选自报有效但实时检查无日线数据的记录，会忽略这些记录并继续寻找下一个有效候选。
  - 创建任务首响应会返回 `minute_files_seen` / `minute_files_imported`（初始为 `0`）；任务进入运行态后，这两个字段会随进度更新。
  - 创建任务首响应会返回 `source_path_exists=true`，表示已确认当前任务源路径存在；后续列表/详情查询会按实时路径状态返回该字段。
- `GET /imports/jobs?limit=20&status=failed`
  - 返回最近导入任务列表（默认 `limit=20`，范围 `1-200`），按最近更新时间倒序。
  - 可选 `status` 参数：`pending` / `queued` / `running` / `succeeded` / `failed`；用于按任务状态过滤，其中 `pending` 等价 `queued + running`。
  - 可选 `source_path_exists` 参数：`true` / `false`；用于按任务源路径当前是否存在进行过滤。
  - 返回项中的 `source_path_exists` 表示任务记录里的 `source_path` 当前在本机是否仍存在；路径为空时为 `null`。
  - 返回项结构与 `GET /imports/jobs/{job_id}` 一致，便于前端在应用重启后恢复任务追踪列表。
  - 后端本地仅保留最近 `200` 条导入任务记录；超出后会按更新时间淘汰最旧记录，防止 `import_jobs` 持续膨胀。
  - 若应用重启后存在遗留的 `queued` / `running` 任务记录，查询时会自动标记为 `failed`，并返回“导入任务已中断，请重新发起导入。”提示，避免前端长期停留在运行态。
- `GET /imports/jobs/{job_id}`
  - 返回导入任务状态和进度，包含日线文件、分钟文件、日线 / 分钟 K 线数量和错误列表。
  - `source_path_exists` 可用于前端在重试前提示“源路径是否已失效”。
  - 任务返回的 `bars_imported` / `minute_bars_imported` 与 `/imports/daily` 口径一致，表示本次处理条数，而不是净新增条数。
  - 成功态响应示例：
    ```json
    {
      "id": "job_20260527_001",
      "status": "succeeded",
      "source_path": "/data/vipdoc",
      "files_seen": 12,
      "files_imported": 12,
      "bars_imported": 14520,
      "minute_files_seen": 8,
      "minute_files_imported": 6,
      "minute_bars_imported": 38640,
      "symbols_imported": 18,
      "errors": []
    }
    ```

## 行情

- `GET /symbols?q=600000&limit=80`
  - 搜索证券索引。
  - 返回证券列表，字段包括 `symbol`、`market`、`code`、`name`、`kind`、首末交易日和 K 线数量。
- `GET /bars?symbol=sh600000&timeframe=D&limit=520`
  - 支持 `1M`、`5M`、`15M`、`30M`、`60M`、`D`、`W`、`M`。
  - `W/M` 由日线聚合生成。
  - `15M/30M/60M` 由 5 分钟线按 A 股 09:30-11:30、13:00-15:00 两段交易时段聚合，只返回完整桶。
  - 返回 K 线列表，字段包括 `symbol`、规范化后的 `timeframe`、`trade_date`、OHLC、`amount` 和 `volume`。
- `GET /chart?symbol=sh600000&timeframe=15m&limit=520&threshold_pct=5`
  - 返回 K 线、缠论分型 / 笔 / 线段 / 中枢、波浪候选和人工标注。
  - `chan` / `wave` 会优先使用当前标的 / 周期下 active 的人工结构；若最新 active 记录无法解析，会继续回退到次新的可解析 active 记录；没有可解析人工结构时回退自动分析结果。
  - `threshold_pct` 控制 ZigZag 波浪候选的浪级阈值，前端当前提供 3%、5%、8% 三档；未传入时使用默认 `wave` 规则配置。
  - `wave` 规则中的 `min_swing_bars` 控制相邻候选 pivot 的最小 K 线间隔；显式传入 `threshold_pct` 时仍沿用默认规则中的 `min_swing_bars`。
- `timeframe` 查询值大小写不敏感，例如 `5m` 会按 `5M` 处理。
- `symbol` 不能为空白字符串；空值或仅空白字符返回 `400`。
- `timeframe` 仅支持 `1M`、`5M`、`15M`、`30M`、`60M`、`D`、`W`、`M`；传入不支持值（如 `2m`）返回 `400`。
- `/bars`、`/chart`、`/analysis/chan`、`/analysis/wave` 和 `/backtests/structure` 共享查询边界：`start_date` / `end_date` 使用 `YYYY-MM-DD`，`before` 支持日线日期或分钟线时间，非法日期返回 `400`；`limit` 最大 2000，分析和回测入口最小 20，`/bars` 和 `/chart` 最小 1。
  - 对分钟周期（`1M/5M/15M/30M/60M`），若 `before` 仅传日期（`YYYY-MM-DD`），会按该日期 `00:00` 处理，因此会排除该日期当天的分钟数据。
- `GET /data/health`
  - 返回本地库数据覆盖、周期可用性和补数建议。

## 分析

- `GET /analysis/chan?symbol=sh000001&timeframe=D&limit=520`
  - 返回简单顶/底分型、基于交替分型生成的笔、基于连续 3 笔生成的线段候选，以及基于 3 笔重叠区间生成的中枢候选。
  - 自动分析使用当前默认 `chan` 规则配置，包括包含处理、成笔最小间隔、线段窗口和中枢窗口等参数。
  - 若当前标的 / 周期存在 active 的 `overlay_type="chan"` 人工缠论结构，接口会优先返回人工结构；若最新 active 记录无法解析，会继续回退到次新的可解析 active 记录；没有可解析人工结构时返回自动分析结果。
  - `fractals` 为分型点列表；`bis` 为笔线段列表，包含起止索引、日期、价格、方向和起止分型类型。
  - `segments` 为线段候选列表，包含起止笔索引、起止 K 线索引、日期、价格、方向和笔数量。
  - `zhongshu` 为中枢候选列表，包含起止笔索引、起止 K 线索引、日期、上下沿、中心价和笔数量。
  - 返回 `algorithm`、`version`、`params`、`generated_at`，用于追踪算法版本、参数和生成时间。
- `GET /analysis/wave?symbol=sh000001&timeframe=D&limit=520&threshold_pct=5`
  - 返回 ZigZag 候选波段。
  - `threshold_pct` 越小越偏细浪，越大越偏大浪；未传入时使用默认 `wave` 规则配置，显式传入时优先使用请求参数。
  - 若当前标的 / 周期存在 active 的 `overlay_type="wave"` 人工浪型，接口会优先返回人工浪型；若最新 active 记录无法解析，会继续回退到次新的可解析 active 记录；没有可解析人工结构时返回自动 ZigZag 候选。
  - `params` 会回显实际使用的 `threshold_pct` 和 `min_swing_bars`。
  - 该接口只提供辅助候选，不输出唯一浪型结论。
  - 返回 `algorithm`、`version`、`params`、`generated_at`，用于追踪算法版本、参数和生成时间。

## 回测

- `GET /backtests/structure?symbol=sh600000&timeframe=D&limit=520&strategy=chan_fractal_reversal&threshold_pct=5&fee_bps=0&slippage_bps=0&position_pct=100&apply_limit_constraints=false&limit_pct=10`
  - 返回研究型结构信号回测结果，当前 MVP 支持 `chan_fractal_reversal`、`chan_bi_reversal`、`chan_zhongshu_breakout` 和 `wave_zigzag_reversal`。
  - `chan_fractal_reversal`：底分型确认后的下一根 K 线收盘价买入，顶分型确认后的下一根 K 线收盘价卖出。
  - `chan_bi_reversal`：向下笔结束后的下一根 K 线收盘价买入，向上笔结束后的下一根 K 线收盘价卖出。
  - `chan_zhongshu_breakout`：中枢形成后，收盘价突破中枢上沿后的下一根 K 线收盘价买入，跌破中枢下沿后的下一根 K 线收盘价卖出。
  - `wave_zigzag_reversal`：ZigZag 低点后的下一根 K 线收盘价买入，ZigZag 高点后的下一根 K 线收盘价卖出；`threshold_pct` 跟随波浪浪级。
  - 自动缠论结构使用当前默认 `chan` 规则配置；自动波浪结构未显式传入 `threshold_pct` 时使用默认 `wave` 规则配置，并始终读取默认 `wave` 规则中的 `min_swing_bars`。
  - 区间结束仍持仓时按最后一根 K 线收盘价退出。
  - 缠论策略存在当前标的 / 周期下 active 的 `overlay_type="chan"` 人工缠论结构时，优先使用人工结构生成信号；若最新 active 记录无法解析，会继续回退到次新的可解析 active 记录。波浪策略存在 active 的 `overlay_type="wave"` 人工浪型时同理；没有可解析人工结构时回退到自动结构。
  - `fee_bps` 为单边手续费基点，`slippage_bps` 为单边滑点基点，`position_pct` 为参与仓位比例；默认保持不计成本、100% 仓位。
  - `apply_limit_constraints=true` 时按前一交易日收盘价近似识别涨跌停：`limit_pct` 为涨跌停幅度百分比，默认 10，允许 0.1-30；支持科学计数法写法（如 `1e1`、`1E1`、`%2B1e1`、`%2B1E1`）；`NaN/Infinity` 等非有限值会被接口拒绝（`422`）；涨停日跳过买入，跌停日跳过卖出；无法在区间末尾卖出的持仓不会强制闭合。
  - `apply_limit_constraints=false` 时不执行涨跌停拦截，`skipped_limit_up_entries` 与 `skipped_limit_down_exits` 固定为 `0`。
  - 无论 `apply_limit_constraints` 是否启用，返回参数都会记录本次使用的 `limit_pct` 和 `limit_rule`，便于回测参数复核与结果对比。
  - 返回 `algorithm=structure-backtest`、`version`、`structure_source`、`manual_annotation_id`、`params`、`generated_at`、`bars_tested`、`trades`、`equity_curve` 和 `summary`。
  - `params` 会记录 `strategy_condition_key`、`strategy_condition`、`structure_counts`、`signal_count`、`entry_signal_count`、`exit_signal_count`、执行价格、成本参数、`apply_limit_constraints`、`limit_pct`、`limit_rule=prev_close_*pct`、跳过成交数量、未闭合持仓和来源算法版本，用于复核回测信号依据。
  - `params.open_position` 在存在未闭合持仓时记录入场日期 / 价格、最新 K 线、持仓 K 线数和未闭合原因；例如 `limit_down_exit_blocked` 表示跌停无法卖出。
  - `equity_curve` 按每笔交易退出点记录 `trade_index`、`trade_date`、`equity`、`equity_return_pct` 和 `drawdown_pct`，用于复核收益曲线与最大回撤。
  - 前端会把 `trades` 渲染为可开关的 K 线图“回测买卖点”图层，买点使用入场日期 / 价格，卖点使用出场日期 / 价格和单笔收益。
  - 前端导出的回测 CSV 会同时写入策略中文名、策略条件、信号中文名、结构来源、来源算法版本、结构用量、候选信号数量、执行参数、独立成本 / 仓位 / 涨跌停参数列和逐笔权益曲线，便于离线复盘；CSV 的 `row_type=closed_trade` 表示闭合交易，`row_type=open_position` 表示未闭合持仓。
  - `summary` 包含交易数、胜率、总收益、平均收益、最大回撤、平均持仓、最短持仓、最长持仓和中位持仓 K 线数量。
  - 该接口不考虑停牌或复杂仓位管理，涨跌停约束仅按前收盘和 `limit_pct` 做研究型近似，用于验证结构信号是否具备后续策略研究价值。

## 标注

- `GET /annotations?symbol=sh000001&timeframe=D`
  - 读取当前标的和周期的人工标注。
- `annotations` 相关接口的 `timeframe` 仅支持 `1M`、`5M`、`15M`、`30M`、`60M`、`D`、`W`、`M`，大小写不敏感（如 `5m`）；不支持值返回 `400`。
- `POST /annotations`
  - 请求：`{"symbol":"sh000001","timeframe":"D","overlay_type":"note","payload":{"note":"...","trade_date":"2026-05-25","price":3150.12}}`
  - 新增标注；`trade_date` 和 `price` 用作 K 线图人工标注 overlay 的锚点。
  - `symbol` 不能为空白字符串；空值或仅空白字符返回 `400`。
  - `overlay_type` 不能为空白字符串；空值或仅空白字符返回 `400`，并会做首尾空白去除。
  - `overlay_type: "chan"` 表示人工缠论结构，payload 可包含 `active`、`chan_algorithm`、`chan_version`、`fractals`、`bis`、`segments` 和 `zhongshu`。当前激活的人工缠论结构会优先于自动缠论结果显示；后端会兼容 `kind=high/low -> top/bottom`、数字字符串 `index/price`，并对 `trade_date` 做首尾空白清理与规范化（支持如 `2026-06-02T09:35:00Z`、`2026-06-02T09:40:00+0800`、`2026-06-02T09:40:00+08`、`2026-06-02T10:00:00-0530`、`2026-06-02T10:00:00-05`）。`+8` / `-5` 这类单数字小时偏移视为非法输入并会被忽略。空白或非法日期（如 `2026-06-31`）分型会被忽略。
  - `overlay_type: "wave"` 表示人工浪型，payload 可包含 `active`、`threshold_pct`、`wave_algorithm`、`wave_version`、`edited_at` 和 `pivots`。当前激活的人工浪型会优先于自动 ZigZag 候选显示；前端改浪会更新同一条人工浪型标注。后端会兼容 `kind=high/low -> top/bottom`、数字字符串 `index/price/wave_no/threshold_pct`，并将 `threshold_pct` 钳制到 `0.1~50`；`NaN/Infinity` 等非有限值会回退到本次请求阈值；`trade_date` 会做首尾空白清理与规范化（支持如 `2026-06-02T09:35:00Z`、`2026-06-02T09:40:00+0800`、`2026-06-02T09:40:00+08`、`2026-06-02T10:00:00-0530`、`2026-06-02T10:00:00-05`）。`+8` / `-5` 这类单数字小时偏移视为非法输入并会被忽略。空白或非法日期（如 `2026-13-01`）浪点会被忽略。
  - 同一标的 / 周期 / `overlay_type` 下，`chan` 和 `wave` 人工覆盖会保持唯一 active 记录；新增或重新激活一条人工结构时，其它同类 active 结构会自动失活。
- `PATCH /annotations/{annotation_id}`
  - 更新标注类型或 payload。
  - 若请求中包含 `overlay_type`，则该字段不能为空白字符串；空值或仅空白字符返回 `400`，并会做首尾空白去除。
  - 标注 payload 可包含 `locked`、`confirmed`、`active`、`trade_date`、`price`、`moved_at`、`edited_at`、算法版本等状态，用于编辑模式、确认、图表定位、普通标注锚点移动、人工浪型启停 / 改浪和复核提示。
- `DELETE /annotations/{annotation_id}`
  - 删除标注。
  - payload 中 `locked: true` 的标注会返回 `409`，需要先解锁再删除。
  - 成功返回 `{"deleted":true}`。

## 复盘笔记

- `GET /review-notes?symbol=sh000001&timeframe=D`
  - 读取当前标的和周期的复盘笔记。
- `review-notes` 相关接口的 `timeframe` 仅支持 `1M`、`5M`、`15M`、`30M`、`60M`、`D`、`W`、`M`，大小写不敏感；不支持值返回 `400`。
  - 底层使用 `annotations.overlay_type = "review_note"` 持久化，因此会跟随用户数据备份一起导出和恢复。
- `POST /review-notes`
  - 请求：`{"symbol":"sh000001","timeframe":"D","title":"复盘笔记","content":"...","tags":["中枢"],"payload":{}}`
  - 新增一条复盘笔记；服务端会补充 `source: "review-panel"`。
  - `symbol` 不能为空白字符串；空值或仅空白字符返回 `400`。
  - 前端保存时会写入当前图表窗口、缠论/波浪算法版本和波浪阈值，用于后续复核。
  - 删除复盘笔记复用 `DELETE /annotations/{annotation_id}`；删除后会从复盘笔记列表和用户数据备份中移除。

## 规则配置

- `GET /rule-profiles`
  - 返回缠论/波浪规则配置。
  - `analysis_type` 仅支持 `chan` / `wave`。
  - 每类分析按 `is_default` 优先选择默认配置；默认 `chan` 配置会参与缠论自动分析和缠论结构回测，默认 `wave` 配置会参与未显式指定浪级的波浪分析、图表和波浪结构回测。
- `GET /rule-profiles?analysis_type=chan`
  - 按分析类型过滤。
- `POST /rule-profiles`
  - 新增规则配置。
  - `analysis_type` 仅支持 `chan` / `wave`；非法值返回 `422`。
  - 当 `is_default=true` 时，会清除同一 `analysis_type` 下其它默认项，并让新配置成为后续自动分析的默认规则。

## 分析方案

- `GET /schemes/analysis?name=本地方案&description=复用参数`
  - 导出分析方案，包含 `schema_version`、`exported_at`、`name`、`description`、`workspace` 和 `rule_profiles`。
  - 后端导出规则配置；前端会在 `workspace` 中补充当前标的上下文、图层开关、默认周期、时间范围、主题、波浪浪级、回测策略、回测成本参数、涨跌停约束开关和 `limit_pct`，并保存当前侧栏面板 `active_panel`、导入任务筛选 `import_job_filter`、手工划线 `manual_lines`（兼容 `manualLines`）、手工划线样式 `manual_line_style`（兼容 `manualLineStyle`）以及日期范围是否手动触碰状态 `date_range_touched`。
  - 不导出 `annotations`、`bars_daily`、`bars_minute`、`symbols`、复盘笔记或用户数据源配置。
- `POST /schemes/analysis`
  - 请求体同 `GET /schemes/analysis` 返回结构。
  - 仅支持 `schema_version: 1`，不支持的版本返回 `400`。
  - `rule_profiles[*].analysis_type` 仅支持 `chan` / `wave`；非法值返回 `422`。
  - `rule_profiles[*].id` 不能为空白字符串；空值或仅空白字符返回 `400`。
  - 若 `rule_profiles` 中出现重复 `id`，后出现的记录会覆盖前一条同 `id` 记录，再参与后续导入流程。
  - 同一 `id` 不能跨 `analysis_type` 复用；若同一个规则 `id` 同时用于 `chan` 和 `wave`，接口返回 `400`。
  - 返回 `rule_profiles_imported`，表示去重覆盖后的实际导入规则数量。
  - 导入时会按 `analysis_type` 替换规则集合：导入 payload 中出现的分析类型会先清空旧规则，再写入新规则。
  - 若某个已导入 `analysis_type` 没有任何 `is_default=true`，后端会自动把该类型里 `updated_at` 最新的一条规则设为默认；若时间并列则按 `id` 倒序稳定选择，避免默认规则缺失导致行为漂移。
  - 当导入规则包含 `is_default=true` 时，仍会清除同一 `analysis_type` 下其它默认项，确保每类分析只有一个默认规则。
  - 前端导入后会应用 `workspace` 中受支持的当前标的、图层、周期、范围、主题、浪级、回测策略和回测参数字段。
  - `workspace.selected_symbol` 为合法标的对象时会恢复当前标的；显式为 `null` 时会清空当前标的和图表；字段缺失或非法时保持当前工作台状态。对象内部日期/数量字段导入时兼容 `first_date` / `last_date` / `bar_count` 与同义 camelCase（`firstDate` / `lastDate` / `barCount`），日期字段会自动去除首尾空白后再校验。
  - `workspace.date_start` / `workspace.date_end` 为合法日期时会恢复日期边界；显式为 `null` 时会清空对应边界；字段缺失或非法时保持当前工作台状态。日期字段会自动去除首尾空白后再校验。若同时给出且出现 `date_start > date_end`，前端会自动纠正为有效区间。
  - `workspace.backtest_options` 导出使用 snake_case（如 `fee_bps`、`position_pct`、`apply_limit_constraints`、`limit_pct`）；前端导入时兼容同义 camelCase 字段（如 `feeBps`、`positionPct`、`applyLimitConstraints`、`limitPct`），且 `apply_limit_constraints` / `applyLimitConstraints` 支持布尔字面量及常见布尔字符串/数字（`true` / `false`、`1` / `0`），便于手工编辑或旧方案迁移。
  - `workspace.layers` 只要包含任一受支持图层字段即可导入；布尔字段兼容布尔字面量及常见布尔字符串/数字（`true` / `false`、`1` / `0`），缺少的新图层字段按当前默认显示，避免旧方案隐藏新增分析结果。工作台图层开关也会持久化到本地 `localStorage` 并在刷新后恢复。
  - `workspace.manual_lines` 导出为 snake_case；导入兼容 `manualLines`。`manual_lines` 显式为 `null` 时会清空当前手工划线，字段缺失或非法时保持当前状态；数组元素支持 `start.trade_date` / `end.trade_date`（兼容 `tradeDate`）和 `created_at`（兼容 `createdAt`）。
  - `workspace.manual_line_style` 导出为 snake_case；导入兼容 `manualLineStyle`。`color` 仅接受 `#rrggbb` 格式，`width` 会归一化到 1-4。snake 字段显式为 `null` 时恢复默认划线样式；snake 字段缺失、非对象、颜色非法或粗细非法时继续尝试同义 camelCase 字段 `manualLineStyle`；两者都缺失或非法时保持当前样式。
  - `workspace.active_panel` 支持 `workbench` / `data` / `layers` / `review` / `learning` / `settings`；`workspace.import_job_filter` 支持 `all` / `pending` / `failed` / `succeeded` / `broken`。导入时兼容同义 camelCase 字段（`activePanel`、`importJobFilter`），并会自动去除首尾空白、按大小写不敏感匹配；字段缺失或非法时保持当前状态。本地 `localStorage` 恢复时也兼容 `active_panel` / `import_job_filter` 键。
  - `workspace.theme` 支持 `light` / `dark`，导入时会自动去除首尾空白并按大小写不敏感匹配；字段缺失或非法时保持当前状态。
  - `workspace.date_range_touched` 支持布尔字面量及常见布尔字符串/数字（`true` / `false`、`1` / `0`），并兼容同义 camelCase 字段 `dateRangeTouched`；字段缺失或非法时保持现有行为（仅当本次导入包含非空且合法的日期边界时，默认视为已手动触碰）。
  - 工作台当前标的、当前周期、日期范围与“是否手动触碰日期范围”状态会持久化到本地 `localStorage` 并在刷新后恢复；若本地值非法则按默认行为回退。日期值恢复时会自动去除首尾空白后再校验。

## 用户数据备份

- `GET /backups/user`
  - 导出用户数据备份，包含 `schema_version`、`exported_at`、本地 `config`、`annotations` 和 `rule_profiles`。
  - 导出时 `config.source_path` 会按便携规则规范化为绝对路径（去空白、展开 `~` 并解析相对段）；未知配置键不会出现在导出结果中。
  - 不导出 `bars_daily`、`bars_minute`、`symbols` 等行情缓存或证券索引；恢复后需要重新导入通达信行情数据。
- `POST /backups/user`
  - 请求体同 `GET /backups/user` 返回结构。
  - 仅支持 `schema_version: 1`，不支持的版本返回 `400`。
  - `annotations[*].id` 不能为空白字符串；空值或仅空白字符返回 `400`。
  - `annotations[*].overlay_type` 不能为空白字符串；空值或仅空白字符返回 `400`。导入时会去除 `overlay_type` 首尾空白后写入本地标注。
  - `annotations[*].symbol` 不能为空白字符串；空值或仅空白字符返回 `400`。
  - `annotations[*].timeframe` 仅支持 `1M`、`5M`、`15M`、`30M`、`60M`、`D`、`W`、`M`；不支持值返回 `400`。
  - `rule_profiles[*].analysis_type` 仅支持 `chan` / `wave`；非法值返回 `422`。
  - `rule_profiles[*].id` 不能为空白字符串；空值或仅空白字符返回 `400`。
  - 若 `annotations` 中出现重复 `id`，后出现的记录会覆盖前一条同 `id` 记录，再写入本地标注。
  - 若 `rule_profiles` 中出现重复 `id`，后出现的记录会覆盖前一条同 `id` 记录，再写入本地规则配置。
  - 同一 `id` 不能跨 `analysis_type` 复用；若同一个规则 `id` 同时用于 `chan` 和 `wave`，接口返回 `400`。
  - 返回 `annotations_imported` / `rule_profiles_imported`，表示去重覆盖后的实际导入数量。
  - 导入时按记录 `id` 覆盖同名标注和规则配置；导入默认规则配置时，会清除同一 `analysis_type` 下其它默认项。
  - 若导入后某个 `analysis_type` 没有默认规则，后端会自动把该类型里 `updated_at` 最新的一条规则设为默认；若时间并列则按 `id` 倒序稳定选择。
  - 如果旧备份中同一标的 / 周期 / 人工结构类型存在多条 active `chan` 或 `wave` 覆盖，导入后只保留更新时间最新的一条 active，其余同类记录会自动失活。
  - 备份内的 `config` 只会把当前支持的便携键写入本地配置文件（目前为 `source_path`）；空 `config` 或未知配置键不会覆盖现有配置。
  - `config.source_path` 会先去除首尾空白并规范化为绝对路径（展开 `~` 并解析相对段）；去空白后为空字符串时忽略该字段，不覆盖现有本地配置。
  - 前端导入后会刷新当前标的图表、人工结构、复盘笔记和回测结果，使恢复的数据立即反映到工作台。
