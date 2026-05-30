# AetherStockAnalysis

本地化 A 股技术分析研究工作台。应用读取通达信本地下载数据，优先支持 CrossOver / Windows 通达信的 `vipdoc` 目录，提供多周期 K 线、缠论 / 波浪结构分析、人工修正、本地复盘保存和轻量结构回测。

详细架构见 [docs/architecture.md](docs/architecture.md)，API 说明见 [docs/api.md](docs/api.md)，规则说明见 [docs/rules.md](docs/rules.md)，测试策略与验证报告见 [docs/testing.md](docs/testing.md)，数据库 schema 见 [docs/schema.sql](docs/schema.sql)。

## 当前能力

- 自动探测通达信 `vipdoc` 数据目录，包括 macOS CrossOver 路径。
- 手动保存数据源目录。
- 解析 `vipdoc/{sh,sz,bj}/lday/*.day` 日线文件、`minline/*.lc1` 1 分钟线和 `fzline/*.lc5` 5 分钟线。
- 导入行情到本地 DuckDB 缓存，支持后台导入任务和进度查询。
- 提供证券搜索、D/W/M K 线查询、1/5 分钟查询、15/30/60 分钟聚合、缠论分型 / 笔 / 线段 / 中枢结构分析 API。
- 提供波浪 ZigZag 候选波段 API、浪级阈值切换、图表浪号和人工浪型优先显示。
- 支持人工标注保存、删除、读取，以及点击或拖拽图表移动锚点；锁定标注禁止删除和移动。
- 支持按标的和周期保存 / 删除复盘笔记，记录当前图表窗口、算法版本和标签。
- 支持分析方案导入和导出，范围包含规则配置、图层开关、默认周期、时间范围、波浪浪级、回测参数（含涨跌停约束开关和涨跌停幅度）、当前侧栏面板、导入任务筛选和手工划线，不包含行情缓存、人工标注和复盘笔记。
- 支持本地导出 Markdown 复盘报告和 K 线 PNG 截图，汇总当前标的、周期、窗口、算法版本、人工浪型、标注和复盘笔记。
- 支持缠论/波浪规则配置表和默认规则。
- 支持用户数据备份导出和导入，范围包含本地配置、人工标注、复盘笔记、规则配置，不包含行情缓存。
- 提供研究型结构信号回测 API 和工作台面板，当前支持分型反转 / 笔方向反转 / 中枢突破 / 波浪反转策略切换，人工缠论或人工浪型优先，支持手续费 / 滑点 / 仓位参数、可选涨跌停约束和涨跌停幅度、策略条件解释、K 线图买卖点图层、复盘报告摘要和带结构证据的交易明细 CSV 导出。
- 解析通达信 `T0002/hq_cache/*.tnf` 证券名称文件。
- React + Material You 风格工作台。

## 架构概览

```text
通达信 vipdoc
  -> backend/app/tdx.py         # 数据源探测和 .day 解析
  -> backend/app/storage.py     # DuckDB 缓存、标注、规则配置
  -> backend/app/analysis.py    # 分析算法
  -> backend/app/main.py        # FastAPI API
  -> frontend/src/App.tsx       # Material You 工作台
  -> frontend/src/KLineChart.tsx# K 线图
```

## 文件结构

```text
backend/
  app/
    analysis.py    # 分析算法入口
    config.py      # 本地配置和数据库路径
    main.py        # FastAPI 路由
    schemas.py     # API schema
    storage.py     # DuckDB schema、查询、导入、标注
    tdx.py         # 通达信数据适配器
  tests/           # 后端单元和 API 测试
frontend/
  src/
    api.ts         # 前端 API client
    App.tsx        # 工作台 UI
    KLineChart.tsx # lightweight-charts 图表
    styles.css     # Material You tokens 和布局
docs/
  architecture.md  # 架构、schema、API、UI 说明
  api.md           # API 端点说明
  rules.md         # 缠论 / 波浪规则说明
  schema.sql       # DuckDB schema
```

## 数据库

DuckDB 文件默认位于：

```text
~/.aether_stock_analysis/aether.duckdb
```

核心表：

- `bars_daily`：日线行情缓存，导入时按 `symbol + trade_date` 去重。
- `bars_minute`：1 分钟和 5 分钟行情缓存，导入时按 `symbol + interval_minutes + trade_time` 去重；15/30/60 分钟由 5 分钟线聚合。
- `symbols`：证券搜索索引。
- `annotations`：人工标注和复盘笔记。
- `rule_profiles`：缠论/波浪规则配置。

## API

- `GET /api/health`
- `GET /api/sources/detect`
- `GET /api/sources/current`
- `POST /api/sources`
- `POST /api/imports/daily`
- `POST /api/imports/jobs`
- `GET /api/imports/jobs`
- `GET /api/imports/jobs/{job_id}`
- `GET /api/symbols`
- `GET /api/bars`
- `GET /api/chart`
- `GET /api/data/health`
- `GET /api/analysis/chan`
- `GET /api/analysis/wave`
- `GET /api/backtests/structure`
- `GET /api/annotations`
- `POST /api/annotations`
- `PATCH /api/annotations/{annotation_id}`
- `DELETE /api/annotations/{annotation_id}`
- `GET /api/review-notes`
- `POST /api/review-notes`
- `GET /api/rule-profiles`
- `POST /api/rule-profiles`
- `GET /api/schemes/analysis`
- `POST /api/schemes/analysis`
- `GET /api/backups/user`
- `POST /api/backups/user`

关键行为说明：

- `POST /api/sources`、`POST /api/imports/daily`、`POST /api/imports/jobs` 的显式 `path` 会先去除首尾空白，再规范化为绝对路径（展开 `~` 并解析相对段）后参与校验和执行；空白路径返回 `400`。
- `GET /api/sources/current` 在 `source_path` 未配置、配置路径非法，或配置路径可解析但无日线数据时，会继续回退自动探测候选；只有没有可用候选时才返回无效状态或保留当前无效配置路径。
- `POST /api/imports/daily` 和 `POST /api/imports/jobs` 在 `path=null` 时会按“已保存数据源（可解析且含日线）-> 自动探测有效候选”的顺序选择数据源；配置源无效时会自动回退探测结果。
- 显式传入 `path` 时不会回退自动探测；若该路径无日线数据，接口直接返回 `400`（`数据源无效：没有找到可导入的日线文件。`）。
- 自动探测候选要求同时满足 `exists=true`、`valid=true`、`path` 非空白，且实时检查后仍包含可导入日线数据。
- 导入返回的 `bars_imported` / `minute_bars_imported` 表示本次处理到的 K 线条数，而不是净新增条数；底层写入按主键去重，重复导入不会让缓存总行数重复增长。`POST /api/imports/daily`、`POST /api/imports/jobs` 及 `GET /api/imports/jobs/{job_id}` 会返回 `minute_files_seen` / `minute_files_imported`，用于区分“扫描到的分钟文件数量”和“实际导入的分钟文件数量”。
- `POST /api/imports/jobs` 创建任务的首响应会返回 `minute_files_seen=0`、`minute_files_imported=0`；任务进入运行态后，这两个字段会随轮询进度更新。
- `POST /api/imports/jobs` 创建任务的首响应会返回 `source_path_exists=true`；`GET /api/imports/jobs` 和 `GET /api/imports/jobs/{job_id}` 会按实时路径状态返回 `source_path_exists`，便于前端提示“源路径是否已失效”。
- `GET /api/imports/jobs` 支持 `status` 过滤：`pending` / `queued` / `running` / `succeeded` / `failed`，其中 `pending` 等价 `queued + running`；也支持 `source_path_exists=true|false` 过滤。
- `GET /api/imports/jobs` 会按更新时间倒序返回最近任务（默认 `limit=20`，范围 `1-200`）；本地最多保留最近 `200` 条任务，超出会淘汰最旧记录。
- 应用重启后若存在遗留的 `queued` / `running` 任务记录，查询任务列表时会自动标记为 `failed` 并提示“导入任务已中断，请重新发起导入。”，避免界面长期停留在运行态。
- `GET /api/chart`、`GET /api/analysis/chan`、`GET /api/analysis/wave` 和 `GET /api/backtests/structure` 读取人工缠论/浪型时，会按“最新到最旧”选择第一条可解析的 active 记录；若最新 active 记录损坏（例如分型/浪点 `trade_date` 非法），会自动回退到次新的可解析记录。
- 人工缠论 / 浪型的 `trade_date` 解析支持日线和分钟时间戳，并兼容 `Z/z`、`+08:00`、`+0800`、`+08`、`-0530`、`-05` 等时区写法；`+8` / `-5` 这类单数字小时偏移视为非法输入并会被忽略。后端会做首尾空白清理和规范化，空白或非法日期点会被忽略。
- `GET /api/backtests/structure` 支持回测参数 `apply_limit_constraints` 与 `limit_pct`（默认 10，范围 0.1-30）；`limit_pct` 支持常规小数和科学计数法写法（如 `12.5`、`1e1`、`1E1`、`%2B1e1`、`%2B1E1`），`NaN/Infinity` 等非有限值会被接口拒绝（`422`）。无论是否启用涨跌停约束，返回参数都会回显本次使用的 `limit_pct` 与 `params.limit_rule=prev_close_*pct`，用于标记按前收盘价近似识别的涨跌停约束规则并便于参数复核（例如 `limit_pct=12.5` 对应 `limit_rule=prev_close_12.5pct`）；当 `apply_limit_constraints=false` 时，`skipped_limit_up_entries` 与 `skipped_limit_down_exits` 固定为 `0`。

用户数据备份只覆盖可迁移的用户数据：本地配置、人工标注、复盘笔记和规则配置。`bars_daily`、`bars_minute`、`symbols` 等由通达信文件导入生成的行情缓存不会进入备份文件，恢复后需要重新导入行情。`GET /api/backups/user` 只导出便携配置键（当前仅 `source_path`）；导出时会将 `source_path` 去除首尾空白并规范化为绝对路径（展开 `~` 并解析相对段），若去空白后为空则不导出该键。备份导入要求 `annotations.id` 和 `annotations.overlay_type` 不能为空白字符串，且会去除 `overlay_type` 首尾空白后写入本地标注；若备份文件中出现重复 `annotations.id`，后出现的记录会覆盖前一条同 `id` 标注再导入。`rule_profiles` 允许同 `analysis_type` 内重复 `id`（后者覆盖前者），但不允许同一 `id` 同时用于 `chan` 和 `wave`，且 `id` 不能为空白字符串，否则导入返回 `400`。备份导入返回的 `annotations_imported` / `rule_profiles_imported` 为去重覆盖后的实际导入数量。

分析方案用于本地复用和迁移参数，不包含行情缓存、证券索引、人工标注或复盘笔记；方案文件包含 `name`、`description`、规则配置和前端补充的 `workspace` 字段，`workspace` 会保存当前标的、图层、周期、浪级偏好、回测配置、当前侧栏面板（`active_panel`）、导入任务筛选（`import_job_filter`）、手工划线（`manual_lines`，兼容 `manualLines`）和手工划线样式（`manual_line_style`，兼容 `manualLineStyle`）。`manual_line_style.color` 仅接受 `#rrggbb` 颜色，`manual_line_style.width` 会归一化到 1-4；snake 字段缺失或非法时会继续尝试同义 `manualLineStyle`。方案导出使用 `limit_pct` 等 snake_case 回测字段，导入时兼容 `limitPct` 等同义 camelCase 字段，`active_panel` / `import_job_filter` 也兼容 `activePanel` / `importJobFilter`，便于手工编辑或迁移旧方案；`selected_symbol`、`date_start` 和 `date_end` 显式为 `null` 时会清空对应工作台状态，字段缺失或非法时保持当前状态，若 `date_start > date_end` 则会自动纠正为有效区间。日期字段导入时也会自动去除首尾空白后再校验格式。旧方案缺少新增图层开关时按当前默认图层显示。`workspace.layers` 导入兼容布尔字面量及常见布尔字符串/数字（`true` / `false`、`1` / `0`）；工作台图层开关也会持久化到本地 `localStorage` 并在刷新后恢复。工作台当前标的、当前周期、日期范围与“是否手动触碰日期范围”状态也会持久化到本地 `localStorage` 并在刷新后恢复，日期值恢复时也会自动去除首尾空白后再校验；分析方案还会导出并恢复 `date_range_touched`（兼容 `dateRangeTouched`），用于保留该“是否手动触碰日期范围”状态，字段缺失或非法时仅在导入了非空且合法的日期边界时默认视为已手动触碰。本地 `localStorage` 恢复当前侧栏面板和导入筛选时也兼容 `active_panel` / `import_job_filter` 键。`workspace.theme`、`workspace.active_panel` 和 `workspace.import_job_filter` 在导入时会自动去除首尾空白并按大小写不敏感匹配合法值。`selected_symbol` 对象内部日期/数量字段导入时兼容 `first_date` / `last_date` / `bar_count` 与同义 camelCase（`firstDate` / `lastDate` / `barCount`），其日期字段同样会自动去除首尾空白后再校验。回测参数中的 `apply_limit_constraints` / `applyLimitConstraints` 除布尔字面量外，也兼容常见布尔字符串和数字（`true` / `false`、`1` / `0`）。规则配置中的 `analysis_type` 仅支持 `chan` / `wave`；导入规则时会按 `analysis_type` 替换该类型下原有规则，非法值会被接口拒绝（`422`）。若导入规则列表中出现重复 `id`，后出现的规则会覆盖前一条同 `id` 记录再导入；但同一 `id` 不能跨 `chan` / `wave` 复用，且 `id` 不能为空白字符串，否则接口返回 `400`。分析方案导入返回 `rule_profiles_imported`，表示去重覆盖后的实际导入规则数量。若导入后某类型没有默认规则，后端会自动把该类型里 `updated_at` 最新的一条设为默认；时间并列时按 `id` 倒序稳定选择默认规则。

## 启动

后端：

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

默认前端会访问 `http://127.0.0.1:8000/api`。

## 测试和构建

目标轮次执行（固定入口检查 + 一键验证）：

```bash
./scripts/run_goal_round.sh
```

如需在同一轮追加本地 smoke：

```bash
./scripts/run_goal_round.sh --with-smoke
```

也可使用 `make` 快捷命令：

```bash
make entry        # 固定入口检查
make scope-guard  # 交付范围守护（禁止非本地交付口径回流）
make docs-guard   # 文档治理守护（文档入口与关键段落一致性）
make draft-guard  # 人工修正草稿本地保存守护检查
make limit-guard  # 回测涨跌停比例 limit_pct 链路守护检查
make line-guard   # 手工划线链路守护检查
make default-symbol-guard # 默认标的与初始时间窗守护检查
make scheme-manual-lines-guard # 分析方案 manual_lines / manual_line_style 链路守护检查
make learning-page-guard # 学习教程独立页面守护检查
make verify       # scope-guard + docs-guard + draft-guard + limit-guard + line-guard + default-symbol-guard + scheme-manual-lines-guard + learning-page-guard + pytest + lint + build + diff --check
make smoke        # 本地 smoke
make round        # 入口检查 + 一键验证
make round-smoke  # 入口检查 + 一键验证 + smoke
```

目标入口检查（active goal 每轮开头）：

```bash
./scripts/check_goal_entry.sh
```

一键验证（推荐）：

```bash
./scripts/verify_local.sh
```

会依次执行：`scope-guard`、`docs guard`、`workspace draft guard`、`limit_pct guard`、`line drawing guard`、`default symbol guard`、`scheme manual lines guard`、`learning page guard`、`backend pytest`、`frontend lint`、`frontend build`、`git diff --check`。
其中 `docs guard` 会检查核心文档是否齐全、README 文档入口链接是否存在，以及关键能力段落（回测 / 标注 / 规则）是否仍保留。
其中 `workspace draft guard` 会检查人工修正草稿本地保存链路的关键保障（scope 切换 flush、页面退出 flush、新旧草稿键兼容入口）是否仍存在。
`limit_pct guard` 会检查“回测涨跌停比例可配置化”链路是否仍完整（后端参数、前端请求、结果回显规则和文档入口）。
`line drawing guard` 会检查“手工划线”关键链路是否仍完整（划线模式交互、锚点容错、自动吸附、状态写入、图层渲染与样式入口）。
`default symbol guard` 会检查“默认展示标的与初始时间窗”关键链路是否仍完整（上证指数优先选择、默认时间窗与标的可见区间对齐）。
`scheme manual lines guard` 会检查“分析方案导入/导出手工划线与划线样式”链路是否仍完整（`manual_lines` / `manual_line_style` 导出、`manualLines` / `manualLineStyle` 兼容导入、状态恢复与文档入口）。
`learning page guard` 会检查“学习教程”是否仍是独立页面，并保留 7 个静态教程条目、教育用途提示和不参与算法输出的文档说明。

本地 smoke（后端健康 + 前端可达）：

```bash
./scripts/smoke_local.sh
```

后端：

```bash
cd backend
. .venv/bin/activate
python -m pytest
```

前端：

```bash
cd frontend
npm run build
```

## 通达信数据

已验证的 macOS CrossOver 候选路径：

```text
~/Library/Application Support/CrossOver/Bottles/*/drive_c/new_tdx/vipdoc
```

日线目录：

```text
vipdoc/sh/lday
vipdoc/sz/lday
vipdoc/bj/lday
```

分钟线目录：

```text
vipdoc/sh/minline/*.lc1
vipdoc/sz/minline/*.lc1
vipdoc/bj/minline/*.lc1
vipdoc/sh/fzline/*.lc5
vipdoc/sz/fzline/*.lc5
vipdoc/bj/fzline/*.lc5
```

通达信下载或更新数据后，需要重新导入，本地库和图表才会使用新文件。数据健康面板会区分“源目录已有分钟文件”和“数据库已经导入分钟 K 线”。
数据源检测只统计可导入行情文件和证券名称缓存，大小与最近更新时间不包含通达信其它缓存目录。

## 当前边界

- 已完成日线、1 分钟、5 分钟导入；15/30/60 分钟由 5 分钟聚合。
- 15/30/60 分钟按 A 股 09:30-11:30、13:00-15:00 两段交易时段分桶，只输出完整聚合桶；缺失 5 分钟线或午休/盘后异常时间不会生成聚合 K 线。
- 缠论当前提供包含关系预处理、分型、笔、线段候选和中枢候选，标准线段破坏规则还在后续阶段。
- 波浪当前是 ZigZag 候选波段，可保存当前候选为人工浪型并优先显示，但不输出唯一结论。
- 后台导入任务状态会持久化到本地 DuckDB（`import_jobs`），应用重启后仍可按任务 ID 查询历史状态。
