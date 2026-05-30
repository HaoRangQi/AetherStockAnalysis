# 测试策略与验证报告

本文档记录 AetherStockAnalysis 的测试范围、可执行测试入口、最近一次完整验证结果，以及当前仍需关注的高优先级风险。

## 测试对象

AetherStockAnalysis 是本地化 A 股技术分析研究工作台，关键链路如下：

```text
通达信 vipdoc
  -> FastAPI 数据源探测 / 导入任务
  -> DuckDB 行情缓存 / 标注 / 规则配置
  -> 缠论、波浪和结构回测分析
  -> React 工作台、学习教程页、复盘和导出
```

核心领域对象包括：

- 数据源：通达信 `vipdoc` 路径、日线文件、分钟线文件、证券名称缓存。
- 行情缓存：`bars_daily`、`bars_minute`、`symbols`。
- 分析结构：缠论分型 / 笔 / 线段 / 中枢，波浪 ZigZag 候选。
- 用户数据：人工标注、复盘笔记、规则配置、分析方案、用户备份。
- 工作台状态：当前标的、周期、时间范围、图层、回测参数、当前面板、手工划线。
- 学习教程：静态教育内容，不参与算法输出、回测信号或 API schema。

## 测试计划

| 类型 | 覆盖重点 | 当前入口 |
| --- | --- | --- |
| 单元测试 | `.day` / `.lc1` / `.lc5` 解析、分型与 ZigZag 规则、参数边界 | `cd backend && .venv/bin/python -m pytest tests/test_analysis.py tests/test_tdx.py` |
| API 集成测试 | 数据源、导入任务、K 线、分析、回测、标注、复盘、备份、方案 | `cd backend && .venv/bin/python -m pytest tests/test_api.py` |
| 安全测试 | CORS 白名单、路径空白/非法输入、schema 版本、跨类型 ID 冲突、非有限数值 | PyTest + guard |
| UI 静态守护 | 工作台草稿、手工划线、默认标的、学习教程独立页面 | `./scripts/check_*_guard.sh` |
| 构建与静态检查 | TypeScript、ESLint、Vite production build、diff 空白检查 | `./scripts/verify_local.sh` |
| 手动验收 | 本地服务可达、数据源检测、学习页无 K 线图、窄屏不遮挡 | 浏览器检查 |

## 重点用例

| 优先级 | 模块 | 场景 |
| --- | --- | --- |
| P0 | 数据源检测 | 未配置路径时自动探测有效 `vipdoc`；配置路径非法时回退探测候选。 |
| P0 | 导入任务 | 后台任务状态从 queued/running 到 succeeded/failed，重启后中断任务标记失败。 |
| P0 | 行情查询 | D/W/M 与 1/5/15/30/60 分钟周期参数校验，缺失数据返回稳定空结果。 |
| P0 | 分析结构 | 自动结构与人工结构优先级，最新人工结构损坏时回退次新可解析记录。 |
| P0 | 回测 | 涨跌停约束开关、`limit_pct` 边界、NaN/Infinity 拒绝、交易明细证据。 |
| P0 | 备份 / 方案 | 不导出行情缓存；重复 ID 去重；跨 `chan` / `wave` ID 冲突拒绝且不污染现有数据。 |
| P0 | 学习教程 | 独立页面显示 7 个教程条目，不渲染 K 线 canvas，不新增算法接口。 |
| P1 | 本地状态 | `active_panel`、`import_job_filter`、图层、日期范围、手工划线与样式恢复。 |
| P1 | UI 响应式 | 右栏 320px 与移动宽度下内容不遮挡、不截断关键教程内容。 |
| P1 | 安全 | CORS 拒绝非本地可信 Origin；路径输入不会产生越权写入。 |
| P2 | 性能 | 大批量本地通达信数据导入耗时、DuckDB 查询延迟、前端 bundle 大小。 |

## 可执行测试代码

本轮新增：

- `backend/tests/test_api.py::test_cors_rejects_untrusted_origins`
  - 断言非可信 Origin 的 CORS 预检返回 `400`。
  - 断言响应不会回显 `access-control-allow-origin`。
- `scripts/check_learning_page_guard.sh`
  - 守护“学习教程”仍是独立页面。
  - 守护 7 个静态教程条目、教育用途提示、移动布局关键样式和文档说明。
- `scripts/verify_local.sh`
  - 将 learning page guard 接入一键验证。

## 最近验证结果

验证日期：2026-05-30

| 命令 | 结果 |
| --- | --- |
| `curl -sS http://127.0.0.1:8000/api/health` | 返回 `{"status":"ok"}` |
| `curl -sS http://127.0.0.1:8000/api/sources/detect` | 能检测到本机 CrossOver 通达信 `vipdoc` |
| `cd backend && .venv/bin/python -m pytest tests/test_api.py -k cors` | `2 passed` |
| `./scripts/check_learning_page_guard.sh` | passed |
| `cd frontend && npm run lint` | passed |
| `cd frontend && npm run build` | passed，存在 Vite chunk 大小警告 |
| `./scripts/verify_local.sh` | `234 passed`，lint/build/guard/diff check 全部通过 |

`./scripts/verify_local.sh` 当前执行顺序：

```text
scope guard
docs guard
workspace draft guard
limit_pct guard
line drawing guard
default symbol guard
scheme manual lines guard
learning page guard
backend pytest
frontend lint
frontend build
git diff --check
```

## 手动验收记录

本轮浏览器验收覆盖：

- 后端 `127.0.0.1:8000` 和前端 `127.0.0.1:5173` 均已启动。
- 原先页面提示 `数据源检测失败。Failed to fetch`，根因是后端服务未启动；启动后错误消失。
- 工作台能加载 K 线、分析信息和本机通达信数据源状态。
- 窄屏下学习教程入口可点击。
- 进入学习教程页后：
  - `main` class 为 `app-shell learning-page-active`。
  - 页面显示顶背离、底背离、顶分型、底分型、M 头、头肩顶、头肩底。
  - 教育用途提示可见，包含“不构成交易建议”。
  - `canvasCount=0`，即教程页没有渲染 K 线图。

## 静态审查结论

| 风险 | 级别 | 说明 |
| --- | --- | --- |
| 前端缺少真正 E2E 测试框架 | 高 | 目前前端依赖 lint/build、静态 guard 和手动浏览器验收；还不能自动点击完整用户流程。 |
| `frontend/src/App.tsx` 体积过大 | 高 | 单文件承载工作台状态、方案导入、教程、复盘、导出等大量职责，后续改动容易产生响应式或状态回归。 |
| Vite 主 chunk 超过 500 kB | 中 | 构建通过，但主包约 535 kB，后续功能继续叠加会影响首屏加载。 |
| 本地应用无认证 | 中 | 当前定位为本机研究工具，默认无登录权限模型；若未来开放局域网访问，需要重新评估认证和 CORS。 |
| 性能测试仍偏手动 | 中 | 大规模导入和长周期查询已有真实数据验证，但缺少稳定的性能基线脚本。 |

## 建议改进

- 引入 Playwright 或 Vitest，至少自动覆盖：数据源页、工作台默认加载、学习教程页、方案导入导出、复盘导出。
- 拆分 `App.tsx`：优先拆出学习教程、侧栏面板、方案导入导出解析、工作台持久化 hook。
- 为导入任务增加性能基线脚本，记录文件数、耗时、导入行数和 DuckDB 查询延迟。
- 对前端 build 做 code splitting，优先拆图表和学习页。
- 保持 `./scripts/verify_local.sh` 作为合并前最低门槛；涉及 UI 入口时追加浏览器验收或 E2E。
