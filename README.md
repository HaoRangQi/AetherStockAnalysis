# AetherStockAnalysis

本地化 A 股技术分析工作台。应用读取通达信本地下载数据，优先支持 CrossOver / Windows 通达信的 `vipdoc` 目录，提供行情导入、K 线查看、缠论分型、人工标注和分析规则配置基础。

详细架构见 [docs/architecture.md](docs/architecture.md)，API 说明见 [docs/api.md](docs/api.md)，数据库 schema 见 [docs/schema.sql](docs/schema.sql)。

## 当前能力

- 自动探测通达信 `vipdoc` 数据目录，包括 macOS CrossOver 路径。
- 手动保存数据源目录。
- 解析 `vipdoc/{sh,sz,bj}/lday/*.day` 日线文件。
- 导入日线到本地 DuckDB 缓存。
- 提供证券搜索、D/W/M K 线查询、缠论分型 API。
- 提供波浪 ZigZag 候选波段 API 和图表辅助线。
- 支持人工标注保存、删除和读取。
- 支持缠论/波浪规则配置表和默认规则。
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
```

## 数据库

DuckDB 文件默认位于：

```text
~/.aether_stock_analysis/aether.duckdb
```

核心表：

- `bars_daily`：日线行情缓存，导入时按 `symbol + trade_date` 去重。
- `symbols`：证券搜索索引。
- `annotations`：人工标注和复盘笔记。
- `rule_profiles`：缠论/波浪规则配置。

## API

- `GET /api/health`
- `GET /api/sources/detect`
- `GET /api/sources/current`
- `POST /api/sources`
- `POST /api/imports/daily`
- `GET /api/symbols`
- `GET /api/bars`
- `GET /api/analysis/chan`
- `GET /api/analysis/wave`
- `GET /api/annotations`
- `POST /api/annotations`
- `PATCH /api/annotations/{id}`
- `DELETE /api/annotations/{id}`
- `GET /api/rule-profiles`
- `POST /api/rule-profiles`

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

分钟线目录会在数据源检测中展示，但解析会在后续版本补齐。

## 当前边界

- 已完成日线导入和 D/W/M 聚合；分钟线解析还未接入。
- 缠论当前只有分型，笔、线段、中枢还在后续阶段。
- 波浪当前是 ZigZag 候选波段，不输出唯一浪型结论。
- 股票名称暂用代码名，后续需要解析通达信证券名称文件。
