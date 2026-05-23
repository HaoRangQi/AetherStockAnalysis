import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  CandlestickChart,
  CheckCircle2,
  Database,
  Download,
  Layers3,
  Moon,
  PenLine,
  RefreshCw,
  Search,
  Settings,
  Sun,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import {
  AnnotationRecord,
  BarRecord,
  ChanAnalysis,
  DataSourceCandidate,
  ImportResult,
  RuleProfile,
  SymbolRecord,
  WaveAnalysis,
  createAnnotation,
  deleteAnnotation,
  detectSources,
  getChartData,
  getCurrentSource,
  getRuleProfiles,
  importDaily,
  saveSource,
  searchSymbols,
} from "./api";
import { KLineChart } from "./KLineChart";

type Panel = "workbench" | "data" | "layers" | "settings";
type Theme = "light" | "dark";

const timeframes = [
  { value: "1m", label: "1 分钟" },
  { value: "5m", label: "5 分钟" },
  { value: "15m", label: "15 分钟" },
  { value: "30m", label: "30 分钟" },
  { value: "60m", label: "60 分钟" },
  { value: "D", label: "日线" },
  { value: "W", label: "周线" },
  { value: "M", label: "月线" },
];

const minuteFrames = new Set(["1m", "5m", "15m", "30m", "60m"]);

const navItems = [
  { panel: "workbench" as const, label: "行情工作台", icon: CandlestickChart },
  { panel: "data" as const, label: "数据源", icon: Database },
  { panel: "layers" as const, label: "分析图层", icon: Layers3 },
  { panel: "settings" as const, label: "设置", icon: Settings },
];

export function App() {
  const [source, setSource] = useState<DataSourceCandidate | null>(null);
  const [candidates, setCandidates] = useState<DataSourceCandidate[]>([]);
  const [manualPath, setManualPath] = useState("");
  const [symbols, setSymbols] = useState<SymbolRecord[]>([]);
  const [query, setQuery] = useState("000001");
  const [selectedSymbol, setSelectedSymbol] = useState<SymbolRecord | null>(null);
  const [defaultTimeframe, setDefaultTimeframe] = useState(() => localStorage.getItem("defaultTimeframe") || "D");
  const [defaultRangeMonths, setDefaultRangeMonths] = useState(() => readDefaultRangeMonths());
  const [timeframe, setTimeframe] = useState(defaultTimeframe);
  const [dateStart, setDateStart] = useState(() =>
    initialDateStart(defaultTimeframe, defaultRangeMonths, toDateInputValue(new Date())),
  );
  const [dateEnd, setDateEnd] = useState(() => toDateInputValue(new Date()));
  const [dateRangeTouched, setDateRangeTouched] = useState(false);
  const [bars, setBars] = useState<BarRecord[]>([]);
  const [analysis, setAnalysis] = useState<ChanAnalysis | null>(null);
  const [waveAnalysis, setWaveAnalysis] = useState<WaveAnalysis | null>(null);
  const [annotations, setAnnotations] = useState<AnnotationRecord[]>([]);
  const [ruleProfiles, setRuleProfiles] = useState<RuleProfile[]>([]);
  const [annotationDraft, setAnnotationDraft] = useState("");
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [status, setStatus] = useState("正在检测数据源");
  const [chartStatus, setChartStatus] = useState("等待选择标的");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activePanel, setActivePanel] = useState<Panel>("workbench");
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("theme") === "dark" ? "dark" : "light"));
  const [layers, setLayers] = useState({
    volume: true,
    fractals: true,
    wave: true,
  });

  const selectedTimeframe = timeframes.find((item) => item.value === timeframe) ?? timeframes[5];
  const selectedName = selectedSymbol ? displayName(selectedSymbol) : "等待导入数据";
  const selectedCode = selectedSymbol ? selectedSymbol.symbol.toUpperCase() : "";
  const minuteFrameSelected = minuteFrames.has(timeframe);

  const selectSymbol = useCallback(
    (symbol: SymbolRecord) => {
      setSelectedSymbol(symbol);
      if (dateRangeTouched) {
        return;
      }
      const end = symbol.last_date ?? toDateInputValue(new Date());
      setDateEnd(end);
      setDateStart(minuteFrames.has(timeframe) ? shiftDay(end, -7) : shiftMonth(end, -defaultRangeMonths));
    },
    [dateRangeTouched, defaultRangeMonths, timeframe],
  );

  useEffect(() => {
    void refreshSources();
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem("defaultTimeframe", defaultTimeframe);
  }, [defaultTimeframe]);

  useEffect(() => {
    localStorage.setItem("defaultRangeMonths", String(defaultRangeMonths));
  }, [defaultRangeMonths]);

  useEffect(() => {
    const timeout = window.setTimeout(async () => {
      try {
        const result = await searchSymbols(query);
        setSymbols(result);
        if (!selectedSymbol && result.length > 0) {
          selectSymbol(result[0]);
        }
      } catch {
        setSymbols([]);
      }
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [query, selectedSymbol, selectSymbol]);

  useEffect(() => {
    if (!selectedSymbol) {
      return;
    }
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (cancelled) {
        return;
      }
      setError(null);
      const range = { startDate: dateStart || undefined, endDate: dateEnd || undefined, limit: 520 };
      try {
        setChartStatus("正在加载图表");
        const result = await getChartData(selectedSymbol.symbol, timeframe, range);
        if (!cancelled) {
          setBars(result.bars);
          setAnalysis(result.chan);
          setWaveAnalysis(result.wave);
          setAnnotations(result.annotations);
          setChartStatus(
            result.bars.length > 0
              ? `已加载 ${result.bars.length.toLocaleString()} 根 K 线`
              : minuteFrames.has(timeframe)
                ? "当前级别暂无本地分钟线数据"
                : "当前范围暂无 K 线数据",
          );
        }
      } catch (err) {
        if (!cancelled) {
          setBars([]);
          setAnalysis(null);
          setWaveAnalysis(null);
          setAnnotations([]);
          setChartStatus("K 线加载失败");
          setError(formatError(err));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedSymbol, timeframe, dateStart, dateEnd]);

  useEffect(() => {
    void loadRuleProfiles();
  }, []);

  const healthItems = useMemo(() => {
    if (!source) {
      return [];
    }
    return [
      ["日线文件", source.daily_files.toLocaleString()],
      ["1 分钟文件", source.minute1_files.toLocaleString()],
      ["5 分钟文件", source.minute5_files.toLocaleString()],
      ["市场", source.markets.join(" / ") || "-"],
    ];
  }, [source]);

  async function refreshSources() {
    setBusy(true);
    setError(null);
    try {
      const [current, detected] = await Promise.all([getCurrentSource(), detectSources()]);
      setCandidates(detected);
      setSource(current.health);
      setManualPath(current.path ?? detected.find((item) => item.valid)?.path ?? "");
      setStatus(current.valid ? "已连接通达信数据源" : "未配置数据源");
    } catch (err) {
      setError(formatError(err));
      setStatus("数据源检测失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveSource(path: string) {
    setBusy(true);
    setError(null);
    try {
      const result = await saveSource(path);
      setSource(result.health);
      setManualPath(result.path ?? path);
      setStatus("数据源已保存");
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleImport() {
    setBusy(true);
    setError(null);
    setStatus("正在导入行情数据");
    try {
      const result = await importDaily(manualPath);
      setImportResult(result);
      setStatus(`导入完成：${result.symbols_imported.toLocaleString()} 个标的`);
      const found = await searchSymbols(query);
      setSymbols(found);
      if (found.length > 0) {
        selectSymbol(found[0]);
      }
    } catch (err) {
      setError(formatError(err));
      setStatus("导入失败");
    } finally {
      setBusy(false);
    }
  }

  async function loadRuleProfiles() {
    try {
      setRuleProfiles(await getRuleProfiles());
    } catch (err) {
      setRuleProfiles([]);
      setError(formatError(err));
    }
  }

  async function handleCreateAnnotation() {
    if (!selectedSymbol || !annotationDraft.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await createAnnotation(selectedSymbol.symbol, timeframe, "note", {
        note: annotationDraft.trim(),
        source: "workbench",
        bar_count: bars.length,
      });
      setAnnotations((current) => [created, ...current]);
      setAnnotationDraft("");
      setStatus("标注已保存");
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  function applyDefaultRange(months = defaultRangeMonths) {
    const end = selectedSymbol?.last_date ?? toDateInputValue(new Date());
    setDateEnd(end);
    setDateStart(shiftMonth(end, -months));
    setDateRangeTouched(false);
  }

  function applyIntradayRange() {
    const end = selectedSymbol?.last_date ?? toDateInputValue(new Date());
    setDateEnd(end);
    setDateStart(shiftDay(end, -7));
    setDateRangeTouched(false);
  }

  function handleTimeframeChange(nextFrame: string) {
    setTimeframe(nextFrame);
    if (dateRangeTouched) {
      return;
    }
    if (minuteFrames.has(nextFrame)) {
      applyIntradayRange();
      return;
    }
    applyDefaultRange();
  }

  async function handleDeleteAnnotation(id: string) {
    setBusy(true);
    setError(null);
    try {
      await deleteAnnotation(id);
      setAnnotations((current) => current.filter((item) => item.id !== id));
      setStatus("标注已删除");
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <aside className="nav-rail" aria-label="主导航">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.panel}
              className={activePanel === item.panel ? "rail-item active" : "rail-item"}
              title={item.label}
              aria-label={item.label}
              onClick={() => setActivePanel(item.panel)}
            >
              <Icon size={22} />
            </button>
          );
        })}
      </aside>

      <section className="left-pane">
        <div className="brand">
          <div className="brand-mark">
            <Activity size={22} />
          </div>
          <div>
            <h1>AetherStock</h1>
            <p>本地缠论 / 波浪分析工作台</p>
          </div>
        </div>

        <section className="surface source-panel">
          <div className="section-title">
            <Database size={18} />
            <span>数据源</span>
          </div>
          <div className={source?.valid ? "status-pill ok" : "status-pill warn"}>
            {source?.valid ? <CheckCircle2 size={16} /> : <TriangleAlert size={16} />}
            <span>{status}</span>
          </div>
          <input
            className="path-input"
            value={manualPath}
            onChange={(event) => setManualPath(event.target.value)}
            placeholder="选择或粘贴通达信 vipdoc 路径"
          />
          <div className="button-row">
            <button className="tonal-button" onClick={() => void refreshSources()} disabled={busy}>
              <RefreshCw size={16} />
              探测
            </button>
            <button className="filled-button" onClick={() => void handleSaveSource(manualPath)} disabled={busy}>
              保存
            </button>
          </div>
          <button className="import-button" onClick={() => void handleImport()} disabled={busy || !manualPath}>
            <Download size={17} />
            导入行情数据
          </button>
        </section>

        <section className="surface search-panel">
          <div className="section-title">
            <Search size={18} />
            <span>证券搜索</span>
          </div>
          <div className="search-box">
            <Search size={17} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="代码 / 名称" />
          </div>
          <div className="symbol-list">
            {symbols.map((item) => (
              <button
                key={item.symbol}
                className={selectedSymbol?.symbol === item.symbol ? "symbol-row active" : "symbol-row"}
                onClick={() => selectSymbol(item)}
              >
                <span>
                  <strong>{displayName(item)}</strong>
                  <small>
                    {item.symbol.toUpperCase()} · {kindLabel(item.kind)}
                  </small>
                </span>
                <span>{item.last_date ?? "-"}</span>
              </button>
            ))}
            {symbols.length === 0 && <p className="empty-note">没有匹配的证券。导入后可按名称或代码搜索。</p>}
          </div>
        </section>
      </section>

      <section className="workspace">
        <header className="top-app-bar">
          <div className="symbol-heading">
            <p className="eyebrow">当前标的</p>
            <h2>{selectedName}</h2>
            {selectedCode && <span>{selectedCode}</span>}
          </div>
          <div className="segmented" aria-label="K 线周期">
            {timeframes.map((frame) => (
              <button key={frame.value} className={timeframe === frame.value ? "selected" : ""} onClick={() => handleTimeframeChange(frame.value)}>
                {frame.label}
              </button>
            ))}
          </div>
        </header>

        <section className="chart-surface">
          <KLineChart
            bars={bars}
            analysis={analysis}
            waveAnalysis={waveAnalysis}
            layers={layers}
            theme={theme}
            emptyMessage={
              minuteFrameSelected
                ? "当前数据源尚未导入这个分钟级别的数据；请先在通达信下载分钟线后重新导入行情数据。"
                : "先导入通达信行情数据，或选择已导入的证券。"
            }
          />
        </section>

        <section className="bottom-sheet">
          <div>
            <strong>数据状态</strong>
            <span>
              {source?.latest_modified ? `最近文件更新：${formatDateTime(source.latest_modified)}` : "未发现更新信息"}
            </span>
          </div>
          <div>
            <strong>当前周期</strong>
            <span>
              {selectedTimeframe.label}
              {minuteFrameSelected && bars.length === 0 && " · 暂无分钟数据"}
            </span>
          </div>
          <div>
            <strong>图表状态</strong>
            <span>{chartStatus}</span>
          </div>
          <div>
            <strong>时间范围</strong>
            <span>
              {dateStart || "-"} 至 {dateEnd || "-"}
            </span>
          </div>
          <div>
            <strong>导入结果</strong>
            <span>
              {importResult
                ? `${importResult.files_imported}/${importResult.files_seen} 日线文件，${importResult.bars_imported.toLocaleString()} 根日线，${importResult.minute_bars_imported.toLocaleString()} 根分钟线`
                : "尚未导入"}
            </span>
          </div>
        </section>
      </section>

      <aside className="right-pane">
        <div className="panel-tabs" aria-label="功能面板">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.panel}
                className={activePanel === item.panel ? "selected" : ""}
                onClick={() => setActivePanel(item.panel)}
                title={item.label}
              >
                <Icon size={16} />
                <span>{item.label.replace("行情", "")}</span>
              </button>
            );
          })}
        </div>
        {renderSidePanel()}
      </aside>

      {error && <div className="snackbar">{error}</div>}
      {busy && <div className="busy-indicator" />}
    </main>
  );

  function renderSidePanel() {
    if (activePanel === "data") {
      return (
        <>
          {renderDataHealthPanel()}
          <section className="surface">
            <div className="section-title">
              <Download size={18} />
              <span>导入状态</span>
            </div>
            <p className="explain-text">
              当前会导入通达信日线和已下载的 1 分钟 / 5 分钟数据；15 / 30 / 60 分钟由 5 分钟数据聚合。
            </p>
            <button className="filled-button full-width" onClick={() => void handleImport()} disabled={busy || !manualPath}>
              <Download size={17} />
              重新导入行情
            </button>
          </section>
        </>
      );
    }

    if (activePanel === "layers") {
      return (
        <>
          {renderLayerPanel()}
          {renderAnalysisPanel()}
        </>
      );
    }

    if (activePanel === "settings") {
      return (
        <>
          <section className="surface">
            <div className="section-title">
              <Settings size={18} />
              <span>外观</span>
            </div>
            <button
              className="tonal-button full-width"
              onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
            >
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
              {theme === "dark" ? "切换浅色主题" : "切换深色主题"}
            </button>
          </section>
          <section className="surface">
            <div className="section-title">
              <CandlestickChart size={18} />
              <span>默认图表</span>
            </div>
            <label className="field-row">
              <span>默认周期</span>
              <select
                value={defaultTimeframe}
                onChange={(event) => {
                  setDefaultTimeframe(event.target.value);
                  handleTimeframeChange(event.target.value);
                }}
              >
                {timeframes.map((frame) => (
                  <option key={frame.value} value={frame.value}>
                    {frame.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-row">
              <span>日线默认范围</span>
              <select
                value={defaultRangeMonths}
                onChange={(event) => {
                  const months = Number(event.target.value);
                  setDefaultRangeMonths(months);
                  if (!minuteFrames.has(timeframe)) {
                    applyDefaultRange(months);
                  }
                }}
              >
                <option value={3}>近 3 个月</option>
                <option value={6}>近 6 个月</option>
                <option value={12}>近 1 年</option>
                <option value={24}>近 2 年</option>
              </select>
            </label>
          </section>
          {renderRulePanel()}
          {renderDataHealthPanel()}
        </>
      );
    }

    return (
      <>
        {renderRangePanel()}
        {renderLayerPanel()}
        {renderAnalysisPanel()}
        {renderAnnotationPanel()}
        {renderRulePanel()}
      </>
    );
  }

  function renderLayerPanel() {
    return (
      <section className="surface">
        <div className="section-title">
          <Layers3 size={18} />
          <span>图层</span>
        </div>
        <label className="switch-row">
          <span>成交量</span>
          <input
            type="checkbox"
            checked={layers.volume}
            onChange={(event) => setLayers((current) => ({ ...current, volume: event.target.checked }))}
          />
        </label>
        <label className="switch-row">
          <span>缠论分型</span>
          <input
            type="checkbox"
            checked={layers.fractals}
            onChange={(event) => setLayers((current) => ({ ...current, fractals: event.target.checked }))}
          />
        </label>
        <label className="switch-row">
          <span>波浪候选</span>
          <input
            type="checkbox"
            checked={layers.wave}
            onChange={(event) => setLayers((current) => ({ ...current, wave: event.target.checked }))}
          />
        </label>
      </section>
    );
  }

  function renderRangePanel() {
    return (
      <section className="surface">
        <div className="section-title">
          <CandlestickChart size={18} />
          <span>时间范围</span>
        </div>
        <div className="date-grid">
          <label>
            <span>开始</span>
            <input
              type="date"
              value={dateStart}
              onChange={(event) => {
                setDateStart(event.target.value);
                setDateRangeTouched(true);
              }}
            />
          </label>
          <label>
            <span>结束</span>
            <input
              type="date"
              value={dateEnd}
              onChange={(event) => {
                setDateEnd(event.target.value);
                setDateRangeTouched(true);
              }}
            />
          </label>
        </div>
        <div className="button-row">
          <button className="tonal-button" onClick={() => applyDefaultRange(6)}>
            近 6 个月
          </button>
          {minuteFrameSelected && (
            <button className="tonal-button" onClick={() => applyIntradayRange()}>
              日内近 7 天
            </button>
          )}
        </div>
      </section>
    );
  }

  function renderAnalysisPanel() {
    return (
      <section className="surface">
        <div className="section-title">
          <Activity size={18} />
          <span>分析解释</span>
        </div>
        <div className="metric-grid">
          <div>
            <span>K 线数量</span>
            <strong>{bars.length}</strong>
          </div>
          <div>
            <span>分型数量</span>
            <strong>{analysis?.fractals.length ?? 0}</strong>
          </div>
          <div>
            <span>波段候选</span>
            <strong>{waveAnalysis?.pivots.length ?? 0}</strong>
          </div>
          <div>
            <span>ZigZag 阈值</span>
            <strong>{waveAnalysis ? `${waveAnalysis.threshold_pct}%` : "-"}</strong>
          </div>
        </div>
        <p className="explain-text">当前版本先标记简单顶 / 底分型和 ZigZag 波段候选。</p>
      </section>
    );
  }

  function renderAnnotationPanel() {
    return (
      <section className="surface">
        <div className="section-title">
          <PenLine size={18} />
          <span>人工标注</span>
        </div>
        <textarea
          className="annotation-input"
          value={annotationDraft}
          onChange={(event) => setAnnotationDraft(event.target.value)}
          placeholder="记录当前周期的结构判断、买卖点观察或复盘说明"
        />
        <button
          className="filled-button full-width"
          onClick={() => void handleCreateAnnotation()}
          disabled={busy || !selectedSymbol || !annotationDraft.trim()}
        >
          保存标注
        </button>
        <div className="annotation-list">
          {annotations.map((item) => (
            <div className="annotation-item" key={item.id}>
              <div>
                <strong>{overlayTypeLabel(item.overlay_type)}</strong>
                <span>{String(item.payload.note ?? "未命名标注")}</span>
                <small>{formatDateTime(item.updated_at)}</small>
              </div>
              <button title="删除标注" onClick={() => void handleDeleteAnnotation(item.id)} disabled={busy}>
                <Trash2 size={15} />
              </button>
            </div>
          ))}
          {annotations.length === 0 && <p className="empty-note">当前标的和周期还没有人工标注。</p>}
        </div>
      </section>
    );
  }

  function renderRulePanel() {
    return (
      <section className="surface">
        <div className="section-title">
          <Settings size={18} />
          <span>规则配置</span>
        </div>
        <div className="profile-list">
          {ruleProfiles.map((profile) => (
            <div className="profile-item" key={profile.id}>
              <div>
                <strong>{profile.name}</strong>
                <span>
                  {analysisTypeLabel(profile.analysis_type)} · {profile.version}
                </span>
              </div>
              {profile.is_default && <small>默认</small>}
            </div>
          ))}
        </div>
      </section>
    );
  }

  function renderDataHealthPanel() {
    return (
      <section className="surface">
        <div className="section-title">
          <Database size={18} />
          <span>数据健康</span>
        </div>
        <div className="health-list">
          {healthItems.map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
        {candidates.length > 0 && (
          <div className="candidate-list">
            {candidates.map((candidate) => (
              <button
                key={candidate.path}
                className={candidate.valid ? "candidate valid" : "candidate"}
                onClick={() => {
                  setManualPath(candidate.path);
                  if (candidate.valid) {
                    void handleSaveSource(candidate.path);
                  }
                }}
              >
                <span>{candidate.label}</span>
                <small>{candidate.valid ? `${candidate.daily_files} 日线文件` : "未发现日线"}</small>
              </button>
            ))}
          </div>
        )}
      </section>
    );
  }
}

function displayName(symbol: SymbolRecord): string {
  const fallback = symbol.symbol.toUpperCase();
  return symbol.name && symbol.name !== fallback ? symbol.name : fallback;
}

function kindLabel(kind: string): string {
  const labels: Record<string, string> = {
    stock: "股票",
    index: "指数",
    etf: "ETF",
  };
  return labels[kind] ?? kind;
}

function formatError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "未知错误";
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN");
}

function overlayTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    note: "笔记",
  };
  return labels[value] ?? value;
}

function analysisTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    chan: "缠论",
    wave: "波浪",
  };
  return labels[value] ?? value;
}

function readDefaultRangeMonths(): number {
  const stored = Number(localStorage.getItem("defaultRangeMonths"));
  return [3, 6, 12, 24].includes(stored) ? stored : 6;
}

function toDateInputValue(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function shiftMonth(value: string, months: number): string {
  const date = new Date(`${value}T00:00:00`);
  date.setMonth(date.getMonth() + months);
  return toDateInputValue(date);
}

function shiftDay(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00`);
  date.setDate(date.getDate() + days);
  return toDateInputValue(date);
}

function initialDateStart(timeframe: string, rangeMonths: number, end: string): string {
  return minuteFrames.has(timeframe) ? shiftDay(end, -7) : shiftMonth(end, -rangeMonths);
}
