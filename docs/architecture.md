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
- 分析层：当前提供缠论分型和波浪 ZigZag 候选；后续扩展笔、线段、中枢和人工改浪。
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

`payload` 使用 JSON 字符串保存，支持分型、笔、线段、中枢、浪型、复盘笔记等不同结构。

### `rule_profiles`

分析规则配置表。

字段：`id`、`name`、`analysis_type`、`version`、`params`、`is_default`、`created_at`、`updated_at`。

默认内置 `chan` 和 `wave` 两类规则配置。

## API 端点

完整端点说明见 [api.md](api.md)。

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
- `GET /api/analysis/chan`：缠论分型分析。
- `GET /api/analysis/wave`：波浪 ZigZag 候选波段。
- `GET /api/annotations`：读取标注。
- `POST /api/annotations`：新增标注。
- `PATCH /api/annotations/{id}`：更新标注。
- `DELETE /api/annotations/{id}`：删除标注。
- `GET /api/rule-profiles`：读取规则配置。
- `POST /api/rule-profiles`：新增规则配置。

## UI 架构

工作台采用 Material You / Material Design 3 风格，但图表区域保持专业金融工具的信息密度。

- 左栏：品牌、数据源、导入、证券搜索。
- 中间：顶部当前标的和周期切换，中央 K 线图，底部数据状态。
- 右栏：图层、分析解释、波段候选统计、人工标注、规则配置、数据健康。

图表使用 `lightweight-charts`，控件使用自定义 Material You tokens，后续可替换为完整组件库。

## 扩展路径

- 分钟线：已从 `minline/fzline` 读取 1 分钟和 5 分钟数据；15/30/60 分钟由 5 分钟线按 A 股上午/下午交易时段聚合，并过滤不完整桶。
- 缠论：在分析层增加包含处理、笔、线段、中枢，输出统一 overlay。
- 波浪：当前已有 ZigZag 候选波段；后续增加浪型编号规则、人工浪级修正和多候选路径。
- 回测：基于行情缓存和分析结果建立策略条件、交易模拟和统计报表。
- 桌面封装：保持本地 API + Web UI 架构，后续用 Tauri 包装。
