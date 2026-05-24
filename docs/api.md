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
- `POST /sources`
  - 请求：`{"path":"/path/to/vipdoc"}`
  - 保存用户指定的通达信数据源。

## 导入

- `POST /imports/daily`
  - 请求：`{"path": null, "markets": ["sh", "sz", "bj"], "limit_files": null}`
  - 解析 `lday/*.day`、`minline/*.lc1`、`fzline/*.lc5` 并写入 DuckDB。
  - 导入时按 `symbol + trade_date` 去重。
- `POST /imports/jobs`
  - 请求同 `/imports/daily`，立即返回后台导入任务。
- `GET /imports/jobs/{job_id}`
  - 返回导入任务状态和进度，包含日线文件、分钟文件、K 线数量和错误列表。

## 行情

- `GET /symbols?q=600000&limit=80`
  - 搜索证券索引。
- `GET /bars?symbol=sh600000&timeframe=D&limit=520`
  - 支持 `1M`、`5M`、`15M`、`30M`、`60M`、`D`、`W`、`M`。
  - `W/M` 由日线聚合生成。
  - `15M/30M/60M` 由 5 分钟线按 A 股 09:30-11:30、13:00-15:00 两段交易时段聚合，只返回完整桶。
- `GET /chart?symbol=sh600000&timeframe=15m&limit=520`
  - 返回 K 线、缠论分型、波浪候选和人工标注。
- `GET /data/health`
  - 返回本地库数据覆盖、周期可用性和补数建议。

## 分析

- `GET /analysis/chan?symbol=sh000001&timeframe=D&limit=520`
  - 返回简单顶/底分型。
- `GET /analysis/wave?symbol=sh000001&timeframe=D&limit=520&threshold_pct=5`
  - 返回 ZigZag 候选波段。
  - 该接口只提供辅助候选，不输出唯一浪型结论。

## 标注

- `GET /annotations?symbol=sh000001&timeframe=D`
  - 读取当前标的和周期的人工标注。
- `POST /annotations`
  - 请求：`{"symbol":"sh000001","timeframe":"D","overlay_type":"note","payload":{"note":"..."}}`
  - 新增标注。
- `PATCH /annotations/{id}`
  - 更新标注类型或 payload。
- `DELETE /annotations/{id}`
  - 删除标注。

## 规则配置

- `GET /rule-profiles`
  - 返回缠论/波浪规则配置。
- `GET /rule-profiles?analysis_type=chan`
  - 按分析类型过滤。
- `POST /rule-profiles`
  - 新增规则配置。
