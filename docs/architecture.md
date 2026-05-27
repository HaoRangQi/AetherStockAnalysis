# AetherStockAnalysis 架构设计

## 产品定位

AetherStockAnalysis 是一个本地化 A 股技术分析工作台，面向缠论、波浪理论和后续量化复盘。MVP 不做账号、云同步、交易和商业化，只围绕本机通达信数据建立可靠的分析闭环。

## 系统架构

```text
通达信 vipdoc
  -> DataAdapter
  -> Import Service
  -> DuckDB Cache
  -> Analysis Engine
  -> FastAPI
  -> React Workbench
```

核心分层：

- 数据源层：探测 CrossOver、Windows、macOS 容器和用户手动指定目录。
- 导入层：解析通达信 `.day`、`.lc1`、`.lc5` 和证券名称文件，批量写入 DuckDB，并生成证券索引。
- 存储层：日线/分钟行情缓存、证券索引、人工标注、分析规则配置。
- 分析层：当前提供含 K 线包含关系预处理的缠论分型、笔、线段候选、中枢候选和可调阈值的波浪 ZigZag 候选；后续扩展标准线段破坏规则、中枢扩展 / 合并和更完整的人工改浪。
- API 层：稳定暴露数据源、导入、行情、分析、标注、规则配置。
- UI 层：Material You 风格三栏工作台，图表为核心，右侧承载解释和编辑。

## 数据库 Schema

DuckDB 文件位置：`~/.aether_stock_analysis/aether.duckdb`。

### `bars_daily`

日线行情缓存。表本身不设置主键，导入时按 `symbol + trade_date` 去重，避免通达信重复记录或增量覆盖触发约束问题。

字段：`symbol`、`market`、`code`、`trade_date`、`open`、`high`、`low`、`close`、`amount`、`volume`。

索引：`bars_daily_symbol_date_idx(symbol, trade_date)`。

### `symbols`

证券搜索索引，由 `bars_daily` 刷新生成。

字段：`symbol`、`market`、`code`、`name`、`kind`、`first_date`、`last_date`、`bar_count`。

索引：`symbols_symbol_idx(symbol)`。

### `bars_minute`

分钟行情缓存，导入时按 `symbol + interval_minutes + trade_time` 去重，保留通达信 1 分钟和 5 分钟基础数据。

字段：`symbol`、`market`、`code`、`trade_time`、`interval_minutes`、`open`、`high`、`low`、`close`、`amount`、`volume`。

索引：`bars_minute_symbol_interval_time_idx(symbol, interval_minutes, trade_time)`。

### `annotations`

人工标注持久化表。

字段：`id`、`symbol`、`timeframe`、`overlay_type`、`payload`、`created_at`、`updated_at`。

`payload` 使用 JSON 字符串保存，支持分型、笔、线段、中枢、浪型、复盘笔记等不同结构。`overlay_type = "chan"` 且 `active != false` 的记录表示人工缠论结构，会优先于自动缠论结果显示；`overlay_type = "wave"` 且 `active != false` 的记录表示人工浪型，会优先于自动 ZigZag 候选显示。同一标的 / 周期 / 人工结构类型只保留一条 active 记录，新增或重新激活同类人工结构时，旧 active 记录会自动失活。`overlay_type = "review_note"` 表示复盘笔记，只在复盘面板展示，不渲染为 K 线图 marker。

### `rule_profiles`

分析规则配置表。

字段：`id`、`name`、`analysis_type`、`version`、`params`、`is_default`、`created_at`、`updated_at`。

默认内置 `chan` 和 `wave` 两类规则配置。

## API 端点

完整端点说明见 [api.md](api.md)，当前算法和人工优先边界见 [rules.md](rules.md)。

- `GET /api/health`：健康检查。
- `GET /api/sources/detect`：探测通达信数据源。
- `GET /api/sources/current`：当前数据源。
- `POST /api/sources`：保存数据源。
- `POST /api/imports/daily`：同步导入日线和已下载分钟线。
- `POST /api/imports/jobs`：启动后台导入任务。
- `GET /api/imports/jobs/{job_id}`：读取导入任务进度。
- `GET /api/symbols`：证券搜索。
- `GET /api/bars`：读取 1/5/15/30/60 分钟和 D/W/M K 线。
- `GET /api/chart`：读取 K 线及分析/标注结果。
- `GET /api/data/health`：读取数据覆盖和补数建议。
- `GET /api/analysis/chan`：缠论分型 / 笔 / 线段 / 中枢分析。
- `GET /api/analysis/wave`：波浪 ZigZag 候选波段。
- `GET /api/backtests/structure`：结构信号轻量回测。
- `GET /api/annotations`：读取标注。
- `POST /api/annotations`：新增标注。
- `PATCH /api/annotations/{annotation_id}`：更新标注。
- `DELETE /api/annotations/{annotation_id}`：删除标注。
- `GET /api/review-notes`：读取复盘笔记。
- `POST /api/review-notes`：新增复盘笔记。
- `GET /api/rule-profiles`：读取规则配置。
- `POST /api/rule-profiles`：新增规则配置。
- `GET /api/schemes/analysis`：导出分析方案，包含规则配置和前端工作台偏好，不包含行情缓存、标注和复盘笔记；前端工作台偏好包括图层、周期、主题、波浪浪级和回测配置。
- `POST /api/schemes/analysis`：导入分析方案内的规则配置，前端负责应用 `workspace` 偏好。
- `GET /api/backups/user`：导出本地配置、人工标注、复盘笔记和规则配置。
- `POST /api/backups/user`：导入用户数据备份，不恢复行情缓存。

## UI 架构

工作台采用 Material You / Material Design 3 风格，但图表区域保持专业金融工具的信息密度。

- 左栏：品牌、数据源、导入、证券搜索。
- 中间：顶部当前标的和周期切换，中央 K 线图，底部数据状态。
- 右栏：图层、分析解释、波段候选统计、复盘笔记、轻量回测、Markdown 复盘报告导出、K 线 PNG 截图导出、人工标注、规则配置、分析方案、数据健康。图层面板可控制成交量、缠论结构、波浪候选、人工标注和回测买卖点显示；人工标注编辑模式支持普通标注确认、锁定、删除和点击 K 线图移动锚点；结构化缠论 / 波浪覆盖不参与普通锚点移动。

图表使用 `lightweight-charts`，控件使用自定义 Material You tokens，后续可替换为完整组件库。

## 扩展路径

- 分钟线：已从 `minline/fzline` 读取 1 分钟和 5 分钟数据；15/30/60 分钟由 5 分钟线按 A 股上午/下午交易时段聚合，并过滤不完整桶。
- 缠论：在分析层继续增加标准线段破坏规则和中枢扩展 / 合并，输出统一 overlay。
- 波浪：当前已有 ZigZag 候选波段、浪级阈值切换、图表浪号和人工浪型优先显示；后续增加更细的逐点改浪和多候选路径。
- 回测：当前已有 `structure-backtest` MVP，支持分型反转、笔方向反转、中枢突破和波浪 ZigZag 反转四种结构策略，输出交易、收益、回撤、胜率和持仓周期统计；后端会按策略优先使用 active 人工缠论结构或人工浪型，支持手续费、滑点、仓位比例、波浪阈值参数和按前收盘价加可配置 `limit_pct` 近似的涨跌停约束，并返回策略条件、结构用量、候选信号数量和跳过成交数量；前端复盘面板已接入策略选择、核心指标、交易列表、结构来源、成本参数、涨跌停约束开关、涨跌停幅度、K 线图买卖点图层、报告摘要和带结构证据的交易明细 CSV 导出。后续补充停牌和更复杂仓位管理。
- 桌面封装：保持本地 API + Web UI 架构，后续用 Tauri 包装。
