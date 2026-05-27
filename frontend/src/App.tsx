import { Component, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BookOpenText,
  CandlestickChart,
  CheckCircle2,
  Database,
  Download,
  FileText,
  FolderPlus,
  Layers3,
  Lock,
  Move,
  Moon,
  PenLine,
  RefreshCw,
  Save,
  Search,
  Settings,
  Star,
  Sun,
  Trash2,
  Unlock,
  TriangleAlert,
  Upload,
} from "lucide-react";
import {
  AnnotationRecord,
  AnalysisSchemePayload,
  BacktestOptions,
  BacktestResult,
  BacktestStrategy,
  BarRecord,
  DataHealth,
  DataRecommendation,
  ChanAnalysis,
  DataSourceCandidate,
  ImportJob,
  ImportResult,
  RuleProfile,
  SymbolRecord,
  WaveAnalysis,
  createAnnotation,
  createRuleProfile,
  deleteAnnotation,
  detectSources,
  exportAnalysisScheme,
  exportUserBackup,
  getChartData,
  getCurrentSource,
  getDataHealth,
  getImportJob,
  listImportJobs,
  listImportJobsWithFilters,
  getRuleProfiles,
  getStructureBacktest,
  importAnalysisScheme,
  importUserBackup,
  saveSource,
  saveReviewNote,
  searchSymbols,
  startImportJob,
  updateAnnotation,
} from "./api";
import { type ChartClickAnchor, type ManualDrawLine, KLineChart, KLineChartHandle } from "./KLineChart";

type Panel = "workbench" | "data" | "layers" | "review" | "settings";
type Theme = "light" | "dark";
type AnnotationMode = "browse" | "edit";
type MinuteDataState = "ready" | "downloaded" | "missing";
type ImportJobFilter = "all" | "pending" | "failed" | "succeeded" | "broken";
type ImportJobQueryFilters = NonNullable<Parameters<typeof listImportJobsWithFilters>[1]>;
type WavePivot = WaveAnalysis["pivots"][number];
type ChanFractalPoint = ChanAnalysis["fractals"][number];
type ChanBiPoint = ChanAnalysis["bis"][number];
type ChanSegmentPoint = ChanAnalysis["segments"][number];
type ChanZhongshuPoint = ChanAnalysis["zhongshu"][number];

type RuleDraft = {
  chanIncludeContainment: boolean;
  chanMinBarsForBi: number;
  chanMinBisForSegment: number;
  chanSegmentStepBis: number;
  chanMinBisForZhongshu: number;
  chanZhongshuStepBis: number;
  waveThresholdPct: number;
  waveMinSwingBars: number;
};
type RuleDraftNumberKey = Exclude<keyof RuleDraft, "chanIncludeContainment">;
type RuleChangeItem = {
  label: string;
  current: string;
  next: string;
  changed: boolean;
};

type MinuteDataStatus = {
  timeframe: string;
  sourceFiles: number;
  dbBars: number;
  dbAvailable: boolean;
  state: MinuteDataState;
  detail: string;
  action: string;
};

type LayerState = {
  volume: boolean;
  fractals: boolean;
  bi: boolean;
  segments: boolean;
  zhongshu: boolean;
  wave: boolean;
  annotations: boolean;
  backtest: boolean;
};

type SymbolGroup = {
  id: string;
  name: string;
  symbols: string[];
};

type StoredManualLine = ManualDrawLine & {
  symbol: string;
  timeframe: string;
  createdAt: string;
};

type ManualLineStyle = {
  color: string;
  width: number;
};

type AnalysisSchemeWorkspaceState = {
  defaultTimeframe: string;
  defaultRangeMonths: number;
  timeframe: string;
  dateStart: string;
  dateEnd: string;
  dateRangeTouched: boolean;
  waveThresholdPct: number;
  backtestStrategy: BacktestStrategy;
  backtestOptions: BacktestOptions;
  layers: LayerState;
  theme: Theme;
  activePanel: Panel;
  importJobFilter: ImportJobFilter;
  selectedSymbol: SymbolRecord | null;
  manualLines: StoredManualLine[];
  manualLineStyle: ManualLineStyle;
};

type ParsedAnalysisSchemeWorkspace = {
  defaultTimeframe: string | null;
  defaultRangeMonths: number | null;
  timeframe: string | null;
  dateStart: string | null;
  dateEnd: string | null;
  dateRangeTouched: boolean | null;
  waveThresholdPct: number | null;
  backtestStrategy: BacktestStrategy | null;
  backtestOptions: BacktestOptions | null;
  layers: LayerState | null;
  theme: Theme | null;
  activePanel: Panel | null;
  importJobFilter: ImportJobFilter | null;
  selectedSymbol: SymbolRecord | null | undefined;
  manualLines: StoredManualLine[] | null | undefined;
  manualLineStyle: ManualLineStyle | null | undefined;
};

type BacktestRequestSnapshot = {
  symbol: SymbolRecord | null;
  timeframe: string;
  dateStart: string;
  dateEnd: string;
  waveThresholdPct: number;
  strategy: BacktestStrategy;
  options: BacktestOptions;
};

type AnalysisSchemeWorkspaceSetters = {
  setSelectedSymbol: (value: SymbolRecord | null) => void;
  setDefaultTimeframe: (value: string) => void;
  setDefaultRangeMonths: (value: number) => void;
  setTimeframe: (value: string) => void;
  setDateStart: (value: string) => void;
  setDateEnd: (value: string) => void;
  setDateRangeTouched: (value: boolean) => void;
  setWaveThresholdPct: (value: number) => void;
  setBacktestStrategy: (value: BacktestStrategy) => void;
  setBacktestOptions: (value: BacktestOptions) => void;
  setLayers: (value: LayerState) => void;
  setTheme: (value: Theme) => void;
  setActivePanel: (value: Panel) => void;
  setImportJobFilter: (value: ImportJobFilter) => void;
  setManualLines: (value: StoredManualLine[]) => void;
  setManualLineStyle: (value: ManualLineStyle) => void;
};

type ReviewReportState = {
  selectedSymbol: SymbolRecord;
  selectedName: string;
  selectedCode: string;
  timeframeLabel: string;
  timeframe: string;
  dateStart: string;
  dateEnd: string;
  loadedWindowStart: string | null;
  loadedWindowEnd: string | null;
  bars: BarRecord[];
  analysis: ChanAnalysis | null;
  waveAnalysis: WaveAnalysis | null;
  backtest: BacktestResult | null;
  manualChanAnnotation: AnnotationRecord | null;
  manualWaveAnnotation: AnnotationRecord | null;
  annotations: AnnotationRecord[];
  reviewNotes: AnnotationRecord[];
  ruleProfiles: RuleProfile[];
  layers: LayerState;
  chartStatus: string;
  dataHealth: DataHealth | null;
};

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

const waveLevels = [
  { label: "细浪", thresholdPct: 3 },
  { label: "标准", thresholdPct: 5 },
  { label: "大浪", thresholdPct: 8 },
];

const backtestStrategies: Array<{ value: BacktestStrategy; label: string; detail: string }> = [
  { value: "chan_fractal_reversal", label: "分型反转", detail: "底分型确认买入，顶分型确认卖出" },
  { value: "chan_bi_reversal", label: "笔方向反转", detail: "向下笔结束买入，向上笔结束卖出" },
  { value: "chan_zhongshu_breakout", label: "中枢突破", detail: "收盘突破中枢上沿买入，跌破下沿卖出" },
  { value: "wave_zigzag_reversal", label: "波浪反转", detail: "ZigZag 低点买入，ZigZag 高点卖出" },
];

const defaultRuleDraft: RuleDraft = {
  chanIncludeContainment: true,
  chanMinBarsForBi: 5,
  chanMinBisForSegment: 3,
  chanSegmentStepBis: 3,
  chanMinBisForZhongshu: 3,
  chanZhongshuStepBis: 1,
  waveThresholdPct: 5,
  waveMinSwingBars: 3,
};

const navItems = [
  { panel: "workbench" as const, label: "行情工作台", icon: CandlestickChart },
  { panel: "data" as const, label: "数据源", icon: Database },
  { panel: "layers" as const, label: "分析图层", icon: Layers3 },
  { panel: "review" as const, label: "复盘笔记", icon: BookOpenText },
  { panel: "settings" as const, label: "设置", icon: Settings },
];

const DEFAULT_MANUAL_LINE_STYLE: ManualLineStyle = {
  color: "#ff8f00",
  width: 2,
};

export function App() {
  const [source, setSource] = useState<DataSourceCandidate | null>(null);
  const [candidates, setCandidates] = useState<DataSourceCandidate[]>([]);
  const [dataHealth, setDataHealth] = useState<DataHealth | null>(null);
  const [manualPath, setManualPath] = useState("");
  const [symbols, setSymbols] = useState<SymbolRecord[]>([]);
  const [query, setQuery] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState<SymbolRecord | null>(() => readSelectedSymbolFromStorage());
  const [defaultTimeframe, setDefaultTimeframe] = useState(() => readDefaultTimeframe());
  const [defaultRangeMonths, setDefaultRangeMonths] = useState(() => readDefaultRangeMonths());
  const [timeframe, setTimeframe] = useState(() => readCurrentTimeframe(defaultTimeframe));
  const [dateRangeTouched, setDateRangeTouched] = useState(() => readDateRangeTouched());
  const [dateEnd, setDateEnd] = useState(() => readCurrentDateEnd(selectedSymbol, dateRangeTouched));
  const [dateStart, setDateStart] = useState(() => readCurrentDateStart(timeframe, defaultRangeMonths, dateEnd, selectedSymbol, dateRangeTouched));
  const [waveThresholdPct, setWaveThresholdPct] = useState(() => readWaveThresholdPct());
  const [bars, setBars] = useState<BarRecord[]>([]);
  const [analysis, setAnalysis] = useState<ChanAnalysis | null>(null);
  const [waveAnalysis, setWaveAnalysis] = useState<WaveAnalysis | null>(null);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [backtestStatus, setBacktestStatus] = useState("等待选择标的");
  const [isBacktestLoading, setIsBacktestLoading] = useState(false);
  const [backtestStrategy, setBacktestStrategy] = useState<BacktestStrategy>(() => readBacktestStrategy());
  const [backtestOptions, setBacktestOptions] = useState<BacktestOptions>(() => readBacktestOptions());
  const [annotations, setAnnotations] = useState<AnnotationRecord[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [hasMoreHistory, setHasMoreHistory] = useState(true);
  const [loadedWindowStart, setLoadedWindowStart] = useState<string | null>(null);
  const [loadedWindowEnd, setLoadedWindowEnd] = useState<string | null>(null);
  const [ruleProfiles, setRuleProfiles] = useState<RuleProfile[]>([]);
  const [ruleDraft, setRuleDraft] = useState<RuleDraft>(defaultRuleDraft);
  const [ruleRefreshKey, setRuleRefreshKey] = useState(0);
  const [annotationDraft, setAnnotationDraft] = useState(() => readLegacyAnnotationDraft());
  const [annotationMode, setAnnotationMode] = useState<AnnotationMode>("browse");
  const [annotationDeleteTarget, setAnnotationDeleteTarget] = useState<AnnotationRecord | null>(null);
  const [movingAnnotationId, setMovingAnnotationId] = useState<string | null>(null);
  const [pendingManualChanFractalKind, setPendingManualChanFractalKind] = useState<ChanFractalPoint["kind"] | null>(null);
  const [pendingManualWavePivotKind, setPendingManualWavePivotKind] = useState<WavePivot["kind"] | null>(null);
  const [reviewNotes, setReviewNotes] = useState<AnnotationRecord[]>([]);
  const [reviewTitle, setReviewTitle] = useState(() => readLegacyReviewTitle());
  const [reviewDraft, setReviewDraft] = useState(() => readLegacyReviewDraft());
  const [reviewTags, setReviewTags] = useState(() => readLegacyReviewTags());
  const [draftScopeKeyLoaded, setDraftScopeKeyLoaded] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importJob, setImportJob] = useState<ImportJob | null>(null);
  const [importJobs, setImportJobs] = useState<ImportJob[]>([]);
  const [importJobFilter, setImportJobFilter] = useState<ImportJobFilter>(() => readImportJobFilter());
  const [highlightSourcePathInput, setHighlightSourcePathInput] = useState(false);
  const [status, setStatus] = useState("正在检测数据源");
  const [chartStatus, setChartStatus] = useState("等待选择标的");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activePanel, setActivePanel] = useState<Panel>(() => readActivePanel());
  const [theme, setTheme] = useState<Theme>(() => readTheme());
  const [layers, setLayers] = useState<LayerState>(() => readLayers());
  const [symbolCatalog, setSymbolCatalog] = useState<Record<string, SymbolRecord>>(() => readSymbolCatalog());
  const [favoriteSymbols, setFavoriteSymbols] = useState<string[]>(() => readFavoriteSymbols());
  const [symbolGroups, setSymbolGroups] = useState<SymbolGroup[]>(() => readSymbolGroups());
  const [activeSymbolGroupId, setActiveSymbolGroupId] = useState<string>(() => readActiveSymbolGroupId());
  const [lineDrawingMode, setLineDrawingMode] = useState(false);
  const [manualLines, setManualLines] = useState<StoredManualLine[]>(() => readStoredManualLines());
  const [manualLineStyle, setManualLineStyle] = useState<ManualLineStyle>(() => readManualLineStyle());
  const historyRequestRef = useRef<string | null>(null);
  const klineChartRef = useRef<KLineChartHandle | null>(null);
  const sourcePathInputRef = useRef<HTMLInputElement | null>(null);
  const backupFileInputRef = useRef<HTMLInputElement | null>(null);
  const schemeFileInputRef = useRef<HTMLInputElement | null>(null);
  const importJobPollingRef = useRef<string | null>(null);
  const importJobFilterRef = useRef<ImportJobFilter>(importJobFilter);
  const selectedSymbolRef = useRef<SymbolRecord | null>(selectedSymbol);
  const startupDefaultSymbolAppliedRef = useRef(false);
  const legacyDraftCleanupDoneRef = useRef(false);
  const previousDraftScopeKeyRef = useRef<string | null>(null);
  const pendingWorkspaceDraftRef = useRef<{ scopeKey: string; snapshot: WorkspaceDraftSnapshot } | null>(null);
  const pendingWorkspaceRetryTimerRef = useRef<number | null>(null);
  const pendingWorkspaceRetryDelayMsRef = useRef(1500);
  const pendingWorkspaceRetryCountRef = useRef(0);
  const [workspaceDraftRuntimeStatus, setWorkspaceDraftRuntimeStatus] = useState<WorkspaceDraftRuntimeStatus>({
    reason: "init",
    lastAttemptAt: null,
    lastPersistedAt: null,
    lastScopeKey: null,
    lastPersisted: null,
    lastPersistenceTarget: "none",
    lastErrorKind: null,
    retryCount: 0,
    nextRetryDelayMs: 1500,
    pendingScopeKey: null,
  });
  const workspaceDraftRuntimeStatusRef = useRef<WorkspaceDraftRuntimeStatus>({
    reason: "init",
    lastAttemptAt: null,
    lastPersistedAt: null,
    lastScopeKey: null,
    lastPersisted: null,
    lastPersistenceTarget: "none",
    lastErrorKind: null,
    retryCount: 0,
    nextRetryDelayMs: 1500,
    pendingScopeKey: null,
  });

  const selectedTimeframe = timeframes.find((item) => item.value === timeframe) ?? timeframes[5];
  const draftScopeKey = useMemo(
    () => buildWorkspaceDraftScopeKey(selectedSymbol?.symbol ?? null, timeframe),
    [selectedSymbol?.symbol, timeframe],
  );
  const selectedWaveLevel =
    waveLevels.find((item) => item.thresholdPct === waveThresholdPct) ?? { label: "自定义", thresholdPct: waveThresholdPct };
  const selectedName = selectedSymbol ? displayName(selectedSymbol) : "等待导入数据";
  const selectedCode = selectedSymbol ? selectedSymbol.symbol.toUpperCase() : "";
  const minuteFrameSelected = minuteFrames.has(timeframe);
  const fitContentToken = `${selectedSymbol?.symbol ?? "none"}:${timeframe}:${dateStart}:${dateEnd}`;
  const selectedRangeMismatch = Boolean(
    selectedSymbol && dateRangeTouched && isDateRangeOutsideSymbol(dateStart, dateEnd, selectedSymbol),
  );
  const manualChanAnnotation = useMemo(() => latestManualChanAnnotation(annotations), [annotations]);
  const manualWaveAnnotation = useMemo(() => latestManualWaveAnnotation(annotations), [annotations]);
  const workbenchAnnotations = useMemo(() => annotations.filter((item) => item.overlay_type !== "review_note"), [annotations]);
  const favoriteSymbolSet = useMemo(() => new Set(favoriteSymbols), [favoriteSymbols]);
  const activeSymbolGroup = useMemo(
    () => symbolGroups.find((group) => group.id === activeSymbolGroupId) ?? null,
    [activeSymbolGroupId, symbolGroups],
  );
  const groupedSymbolSet = useMemo(() => {
    if (!activeSymbolGroup) {
      return null;
    }
    return new Set(activeSymbolGroup.symbols);
  }, [activeSymbolGroup]);
  const favoriteSymbolRecords = useMemo(
    () => favoriteSymbols.map((symbol) => symbolCatalog[symbol]).filter((item): item is SymbolRecord => Boolean(item)),
    [favoriteSymbols, symbolCatalog],
  );
  const displayedSymbols = useMemo(() => {
    const queryText = query.trim();
    const catalogItems = Object.values(symbolCatalog);
    const scoped =
      queryText.length > 0
        ? symbols
        : activeSymbolGroupId === "__favorites"
          ? favoriteSymbolRecords
          : activeSymbolGroup
            ? activeSymbolGroup.symbols.map((symbol) => symbolCatalog[symbol]).filter((item): item is SymbolRecord => Boolean(item))
            : catalogItems.length > 0
              ? catalogItems
              : symbols;
    const filtered = groupedSymbolSet
      ? scoped.filter((item) => groupedSymbolSet.has(item.symbol))
      : activeSymbolGroupId === "__favorites"
        ? scoped.filter((item) => favoriteSymbolSet.has(item.symbol))
        : scoped;
    return [...filtered].sort((left, right) => {
      if (selectedSymbol?.symbol === left.symbol) {
        return -1;
      }
      if (selectedSymbol?.symbol === right.symbol) {
        return 1;
      }
      return right.bar_count - left.bar_count;
    });
  }, [
    activeSymbolGroup,
    activeSymbolGroupId,
    favoriteSymbolRecords,
    favoriteSymbolSet,
    groupedSymbolSet,
    query,
    selectedSymbol?.symbol,
    symbolCatalog,
    symbols,
  ]);
  const manualLinesForCurrentChart = useMemo(() => {
    if (!selectedSymbol) {
      return [];
    }
    return manualLines.filter((line) => line.symbol === selectedSymbol.symbol && line.timeframe === timeframe);
  }, [manualLines, selectedSymbol, timeframe]);
  const displayedAnalysis = useMemo(
    () => applyManualChanAnnotation(analysis, manualChanAnnotation),
    [analysis, manualChanAnnotation],
  );
  const displayedWaveAnalysis = useMemo(
    () => applyManualWaveAnnotation(waveAnalysis, manualWaveAnnotation),
    [waveAnalysis, manualWaveAnnotation],
  );
  const defaultChanRuleProfile = useMemo(
    () => defaultRuleProfile(ruleProfiles, "chan"),
    [ruleProfiles],
  );
  const defaultWaveRuleProfile = useMemo(
    () => defaultRuleProfile(ruleProfiles, "wave"),
    [ruleProfiles],
  );
  const chanRuleChanges = useMemo(
    () => chanRuleChangeItems(defaultChanRuleProfile, ruleDraft),
    [defaultChanRuleProfile, ruleDraft],
  );
  const waveRuleChanges = useMemo(
    () => waveRuleChangeItems(defaultWaveRuleProfile, ruleDraft),
    [defaultWaveRuleProfile, ruleDraft],
  );
  const dataStoreSummary = formatDataStoreSummary(dataHealth);
  const sourceUpdateSummary = source?.latest_modified ? `文件更新：${formatDateTime(source.latest_modified)}` : "未发现源文件更新信息";
  const workspaceDraftSummary = formatWorkspaceDraftRuntimeSummary(workspaceDraftRuntimeStatus);
  const workspaceDraftDetail = formatWorkspaceDraftRuntimeDetail(workspaceDraftRuntimeStatus);
  const flushPendingWorkspaceDraft = useCallback((expectedScopeKey?: string) => {
    const pending = pendingWorkspaceDraftRef.current;
    if (!pending) {
      if (pendingWorkspaceRetryTimerRef.current !== null) {
        window.clearTimeout(pendingWorkspaceRetryTimerRef.current);
        pendingWorkspaceRetryTimerRef.current = null;
      }
      pendingWorkspaceRetryDelayMsRef.current = 1500;
      pendingWorkspaceRetryCountRef.current = 0;
      publishWorkspaceDraftRuntimeStatus(workspaceDraftRuntimeStatusRef, {
        reason: "idle",
        retryCount: 0,
        nextRetryDelayMs: 1500,
        pendingScopeKey: null,
      }, setWorkspaceDraftRuntimeStatus);
      return;
    }
    if (expectedScopeKey && pending.scopeKey !== expectedScopeKey) {
      return;
    }
    publishWorkspaceDraftRuntimeStatus(workspaceDraftRuntimeStatusRef, {
      reason: "flush_attempt",
      lastAttemptAt: Date.now(),
      lastScopeKey: pending.scopeKey,
      pendingScopeKey: pending.scopeKey,
      lastErrorKind: "none",
      retryCount: pendingWorkspaceRetryCountRef.current,
      nextRetryDelayMs: pendingWorkspaceRetryDelayMsRef.current,
    }, setWorkspaceDraftRuntimeStatus);
    const writeResult = writeWorkspaceDraftSnapshot(pending.scopeKey, pending.snapshot);
    if (!writeResult.persisted) {
      if (pendingWorkspaceRetryTimerRef.current === null) {
        const retryDelayMs = pendingWorkspaceRetryCountRef.current >= 6
          ? 12000
          : pendingWorkspaceRetryDelayMsRef.current;
        pendingWorkspaceRetryTimerRef.current = window.setTimeout(() => {
          pendingWorkspaceRetryTimerRef.current = null;
          flushPendingWorkspaceDraft(pending.scopeKey);
        }, retryDelayMs);
        if (pendingWorkspaceRetryCountRef.current < 6) {
          pendingWorkspaceRetryDelayMsRef.current = Math.min(retryDelayMs * 2, 12000);
          pendingWorkspaceRetryCountRef.current += 1;
        }
        publishWorkspaceDraftRuntimeStatus(workspaceDraftRuntimeStatusRef, {
          reason: "persist_failed_retry_scheduled",
          lastPersisted: false,
          lastPersistenceTarget: writeResult.persistenceTarget,
          lastErrorKind: writeResult.errorKind,
          lastScopeKey: pending.scopeKey,
          pendingScopeKey: pending.scopeKey,
          retryCount: pendingWorkspaceRetryCountRef.current,
          nextRetryDelayMs: retryDelayMs,
        }, setWorkspaceDraftRuntimeStatus);
      } else {
        publishWorkspaceDraftRuntimeStatus(workspaceDraftRuntimeStatusRef, {
          reason: "persist_failed_retry_waiting",
          lastPersisted: false,
          lastPersistenceTarget: writeResult.persistenceTarget,
          lastErrorKind: writeResult.errorKind,
          lastScopeKey: pending.scopeKey,
          pendingScopeKey: pending.scopeKey,
          retryCount: pendingWorkspaceRetryCountRef.current,
          nextRetryDelayMs: pendingWorkspaceRetryDelayMsRef.current,
        }, setWorkspaceDraftRuntimeStatus);
      }
      return;
    }
    if (pendingWorkspaceRetryTimerRef.current !== null) {
      window.clearTimeout(pendingWorkspaceRetryTimerRef.current);
      pendingWorkspaceRetryTimerRef.current = null;
    }
    pendingWorkspaceRetryDelayMsRef.current = 1500;
    pendingWorkspaceRetryCountRef.current = 0;
    pendingWorkspaceDraftRef.current = null;
    publishWorkspaceDraftRuntimeStatus(workspaceDraftRuntimeStatusRef, {
      reason: "persisted",
      lastPersisted: true,
      lastPersistenceTarget: writeResult.persistenceTarget,
      lastErrorKind: "none",
      lastScopeKey: pending.scopeKey,
      lastPersistedAt: Date.now(),
      retryCount: 0,
      nextRetryDelayMs: 1500,
      pendingScopeKey: null,
    }, setWorkspaceDraftRuntimeStatus);
    if (writeResult.canCleanupLegacy && !legacyDraftCleanupDoneRef.current) {
      legacyDraftCleanupDoneRef.current = clearLegacyDraftKeysAndVerify().persisted;
    }
  }, []);

  const triggerWorkspaceDraftSync = useCallback((forceSync = false) => {
    if (!forceSync && workspaceDraftRuntimeIsSyncing(workspaceDraftRuntimeStatusRef.current)) {
      return;
    }
    if (draftScopeKeyLoaded !== draftScopeKey) {
      flushPendingWorkspaceDraft();
      return;
    }
    pendingWorkspaceDraftRef.current = {
      scopeKey: draftScopeKey,
      snapshot: {
        annotationDraft,
        reviewTitle,
        reviewDraft,
        reviewTags,
      },
    };
    if (pendingWorkspaceRetryTimerRef.current !== null) {
      window.clearTimeout(pendingWorkspaceRetryTimerRef.current);
      pendingWorkspaceRetryTimerRef.current = null;
    }
    pendingWorkspaceRetryDelayMsRef.current = 1500;
    pendingWorkspaceRetryCountRef.current = 0;
    publishWorkspaceDraftRuntimeStatus(workspaceDraftRuntimeStatusRef, {
      reason: "draft_manual_sync",
      lastScopeKey: draftScopeKey,
      pendingScopeKey: draftScopeKey,
      lastErrorKind: "none",
      retryCount: 0,
      nextRetryDelayMs: 1500,
    }, setWorkspaceDraftRuntimeStatus);
    flushPendingWorkspaceDraft(draftScopeKey);
  }, [annotationDraft, draftScopeKey, draftScopeKeyLoaded, flushPendingWorkspaceDraft, reviewDraft, reviewTags, reviewTitle]);

  const selectSymbol = useCallback(
    (symbol: SymbolRecord) => {
      setSymbolCatalog((current) => ({ ...current, [symbol.symbol]: symbol }));
      setSelectedSymbol(symbol);
      setMovingAnnotationId(null);
      setPendingManualChanFractalKind(null);
      setPendingManualWavePivotKind(null);
      if (dateRangeTouched) {
        return;
      }
      const end = symbol.last_date ?? toDateInputValue(new Date());
      const start = minuteFrames.has(timeframe) ? shiftDay(end, -7) : shiftMonth(end, -defaultRangeMonths);
      setDateEnd(end);
      setDateStart(start);
    },
    [dateRangeTouched, defaultRangeMonths, timeframe],
  );

  const toggleFavoriteSymbol = useCallback(
    (symbol: SymbolRecord) => {
      setSymbolCatalog((current) => ({ ...current, [symbol.symbol]: symbol }));
      setFavoriteSymbols((current) => {
        if (current.includes(symbol.symbol)) {
          return current.filter((item) => item !== symbol.symbol);
        }
        return [...current, symbol.symbol];
      });
    },
    [],
  );

  const createSymbolGroup = useCallback(() => {
    const rawName = window.prompt("输入分组名称");
    if (typeof rawName !== "string") {
      return;
    }
    const name = rawName.trim();
    if (!name) {
      return;
    }
    setSymbolGroups((current) => {
      const exists = current.find((group) => group.name === name);
      if (exists) {
        setActiveSymbolGroupId(exists.id);
        return current;
      }
      const next = { id: `group_${Date.now()}`, name, symbols: [] };
      setActiveSymbolGroupId(next.id);
      return [...current, next];
    });
  }, []);

  const addSelectedSymbolToGroup = useCallback(() => {
    if (!selectedSymbol) {
      return;
    }
    const rawName = window.prompt("输入目标分组名称（已存在则追加，不存在则新建）");
    if (typeof rawName !== "string") {
      return;
    }
    const name = rawName.trim();
    if (!name) {
      return;
    }
    setSymbolGroups((current) => {
      const existing = current.find((group) => group.name === name);
      if (existing) {
        setActiveSymbolGroupId(existing.id);
        return current.map((group) =>
          group.id === existing.id && !group.symbols.includes(selectedSymbol.symbol)
            ? { ...group, symbols: [...group.symbols, selectedSymbol.symbol] }
            : group,
        );
      }
      const next = {
        id: `group_${Date.now()}`,
        name,
        symbols: [selectedSymbol.symbol],
      };
      setActiveSymbolGroupId(next.id);
      return [...current, next];
    });
    setSymbolCatalog((current) => ({ ...current, [selectedSymbol.symbol]: selectedSymbol }));
  }, [selectedSymbol]);

  const handleCreateManualLine = useCallback(
    (start: ChartClickAnchor, end: ChartClickAnchor) => {
      if (!selectedSymbol) {
        console.warn("[App] create-manual-line ignored: no selected symbol");
        return;
      }
      const id = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `line_${Date.now()}`;
      console.info("[App] create-manual-line", {
        id,
        symbol: selectedSymbol.symbol,
        timeframe,
        start,
        end,
      });
      setManualLines((current) => {
        const next = [
          ...current,
          {
            id,
            symbol: selectedSymbol.symbol,
            timeframe,
            start,
            end,
            createdAt: new Date().toISOString(),
          },
        ];
        console.info("[App] manual-lines-size", {
          total: next.length,
          currentChart: next.filter((line) => line.symbol === selectedSymbol.symbol && line.timeframe === timeframe).length,
          symbol: selectedSymbol.symbol,
          timeframe,
        });
        return next;
      });
      setStatus(`已新增划线：${start.tradeDate} -> ${end.tradeDate}`);
    },
    [selectedSymbol, timeframe],
  );

  const undoLastManualLine = useCallback(() => {
    if (!selectedSymbol) {
      return;
    }
    setManualLines((current) => {
      const indexes = current
        .map((line, index) => ({ line, index }))
        .filter(({ line }) => line.symbol === selectedSymbol.symbol && line.timeframe === timeframe);
      const last = indexes.at(-1);
      if (!last) {
        return current;
      }
      return current.filter((_, index) => index !== last.index);
    });
  }, [selectedSymbol, timeframe]);

  const handleSelectSymbol = useCallback(
    (symbol: SymbolRecord) => {
      const sameSymbol = selectedSymbol?.symbol === symbol.symbol;
      selectSymbol(symbol);
      setError(null);
      setStatus(sameSymbol ? `已选中 ${displayName(symbol)}，正在刷新图表` : `已切换到 ${displayName(symbol)}`);
      if (sameSymbol) {
        setRuleRefreshKey((current) => current + 1);
      }
    },
    [selectSymbol, selectedSymbol?.symbol],
  );

  const autoSelectDefaultSymbolIfMissing = useCallback(async (forcePreferred = false) => {
    if (!forcePreferred && selectedSymbolRef.current) {
      return;
    }

    const pickByQuery = async (queryText: string): Promise<SymbolRecord | null> => {
      const result = await searchSymbols(queryText);
      if (result.length === 0) {
        return null;
      }
      return result.find((item) => item.symbol.toLowerCase() === "sh000001") ?? result[0];
    };

    let fallback: SymbolRecord | null;
    try {
      const byIndex = await pickByQuery("sh000001");
      const byCode = byIndex ?? await pickByQuery("000001");
      fallback = byCode ?? await pickByQuery("");
    } catch {
      return;
    }

    if (!fallback) {
      return;
    }
    if (!forcePreferred && selectedSymbolRef.current) {
      return;
    }
    if (selectedSymbolRef.current?.symbol === fallback.symbol) {
      return;
    }
    selectSymbol(fallback);
  }, [selectSymbol]);

  useEffect(() => {
    void refreshSources();
    // 仅在应用启动时执行一次源探测，避免因为函数身份变化触发重复刷新。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    safeLocalStorageSetItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    safeLocalStorageSetItem("defaultTimeframe", defaultTimeframe);
  }, [defaultTimeframe]);

  useEffect(() => {
    safeLocalStorageSetItem("defaultRangeMonths", String(defaultRangeMonths));
  }, [defaultRangeMonths]);

  useEffect(() => {
    safeLocalStorageSetItem("currentTimeframe", timeframe);
  }, [timeframe]);

  useEffect(() => {
    safeLocalStorageSetItem("dateStart", dateStart);
  }, [dateStart]);

  useEffect(() => {
    safeLocalStorageSetItem("dateEnd", dateEnd);
  }, [dateEnd]);

  useEffect(() => {
    safeLocalStorageSetItem("dateRangeTouched", String(dateRangeTouched));
  }, [dateRangeTouched]);

  useEffect(() => {
    selectedSymbolRef.current = selectedSymbol;
  }, [selectedSymbol]);

  useEffect(() => {
    if (selectedSymbol) {
      safeLocalStorageSetItem("selectedSymbol", JSON.stringify(selectedSymbol));
      return;
    }
    safeLocalStorageRemoveItem("selectedSymbol");
  }, [selectedSymbol]);

  useEffect(() => {
    safeLocalStorageSetItem("waveThresholdPct", String(waveThresholdPct));
  }, [waveThresholdPct]);

  useEffect(() => {
    safeLocalStorageSetItem("backtestStrategy", backtestStrategy);
  }, [backtestStrategy]);

  useEffect(() => {
    safeLocalStorageSetItem("backtestOptions", JSON.stringify(backtestOptions));
  }, [backtestOptions]);

  useEffect(() => {
    safeLocalStorageSetItem("activePanel", activePanel);
  }, [activePanel]);

  useEffect(() => {
    safeLocalStorageSetItem("importJobFilter", importJobFilter);
  }, [importJobFilter]);

  useEffect(() => {
    safeLocalStorageSetItem("layers", JSON.stringify(layers));
  }, [layers]);

  useEffect(() => {
    safeLocalStorageSetItem("favoriteSymbols", JSON.stringify(favoriteSymbols));
  }, [favoriteSymbols]);

  useEffect(() => {
    safeLocalStorageSetItem("symbolGroups", JSON.stringify(symbolGroups));
  }, [symbolGroups]);

  useEffect(() => {
    safeLocalStorageSetItem("activeSymbolGroupId", activeSymbolGroupId);
  }, [activeSymbolGroupId]);

  useEffect(() => {
    safeLocalStorageSetItem("symbolCatalog", JSON.stringify(symbolCatalog));
  }, [symbolCatalog]);

  useEffect(() => {
    safeLocalStorageSetItem("manualLines", JSON.stringify(manualLines));
  }, [manualLines]);

  useEffect(() => {
    safeLocalStorageSetItem("manualLineStyle", JSON.stringify(manualLineStyle));
  }, [manualLineStyle]);

  useEffect(() => {
    const useLegacyFallback = draftScopeKeyLoaded === null;
    const snapshot = readWorkspaceDraftSnapshot(draftScopeKey, useLegacyFallback);
    const timer = window.setTimeout(() => {
      setAnnotationDraft(snapshot.annotationDraft);
      setReviewTitle(snapshot.reviewTitle);
      setReviewDraft(snapshot.reviewDraft);
      setReviewTags(snapshot.reviewTags);
      setDraftScopeKeyLoaded(draftScopeKey);
    }, 0);
    return () => {
      window.clearTimeout(timer);
    };
  }, [draftScopeKey, draftScopeKeyLoaded]);

  useEffect(() => {
    if (draftScopeKeyLoaded !== draftScopeKey) {
      return;
    }
    pendingWorkspaceDraftRef.current = {
      scopeKey: draftScopeKey,
      snapshot: {
        annotationDraft,
        reviewTitle,
        reviewDraft,
        reviewTags,
      },
    };
    if (pendingWorkspaceRetryTimerRef.current !== null) {
      window.clearTimeout(pendingWorkspaceRetryTimerRef.current);
      pendingWorkspaceRetryTimerRef.current = null;
    }
    pendingWorkspaceRetryDelayMsRef.current = 1500;
    pendingWorkspaceRetryCountRef.current = 0;
    publishWorkspaceDraftRuntimeStatus(workspaceDraftRuntimeStatusRef, {
      reason: "draft_updated_debounce",
      lastScopeKey: draftScopeKey,
      pendingScopeKey: draftScopeKey,
      lastErrorKind: "none",
      retryCount: 0,
      nextRetryDelayMs: 1500,
    }, setWorkspaceDraftRuntimeStatus);
    const timer = window.setTimeout(() => {
      flushPendingWorkspaceDraft(draftScopeKey);
    }, 150);
    return () => {
      window.clearTimeout(timer);
    };
  }, [annotationDraft, draftScopeKey, draftScopeKeyLoaded, flushPendingWorkspaceDraft, reviewDraft, reviewTags, reviewTitle]);

  useEffect(() => {
    const previousScopeKey = previousDraftScopeKeyRef.current;
    if (previousScopeKey && previousScopeKey !== draftScopeKey) {
      flushPendingWorkspaceDraft(previousScopeKey);
    }
    previousDraftScopeKeyRef.current = draftScopeKey;
    return () => {
      flushPendingWorkspaceDraft(draftScopeKey);
    };
  }, [draftScopeKey, flushPendingWorkspaceDraft]);

  useEffect(() => {
    const handlePageHide = () => {
      flushPendingWorkspaceDraft();
    };
    window.addEventListener("pagehide", handlePageHide);
    return () => {
      window.removeEventListener("pagehide", handlePageHide);
      flushPendingWorkspaceDraft();
    };
  }, [flushPendingWorkspaceDraft]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        flushPendingWorkspaceDraft();
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [flushPendingWorkspaceDraft]);

  useEffect(() => {
    const handleBeforeUnload = () => {
      flushPendingWorkspaceDraft();
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [flushPendingWorkspaceDraft]);

  useEffect(() => {
    const handleWindowBlur = () => {
      flushPendingWorkspaceDraft();
    };
    window.addEventListener("blur", handleWindowBlur);
    return () => {
      window.removeEventListener("blur", handleWindowBlur);
    };
  }, [flushPendingWorkspaceDraft]);

  useEffect(() => {
    const handleDraftSyncHotkey = (event: KeyboardEvent) => {
      if (event.repeat) {
        return;
      }
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "s") {
        return;
      }
      const forceSync = event.shiftKey;
      if (!forceSync && !workspaceDraftRuntimeCanForceSync(workspaceDraftRuntimeStatusRef.current)) {
        return;
      }
      event.preventDefault();
      triggerWorkspaceDraftSync(forceSync);
    };
    window.addEventListener("keydown", handleDraftSyncHotkey);
    return () => {
      window.removeEventListener("keydown", handleDraftSyncHotkey);
    };
  }, [triggerWorkspaceDraftSync]);

  useEffect(() => {
    return () => {
      if (pendingWorkspaceRetryTimerRef.current !== null) {
        window.clearTimeout(pendingWorkspaceRetryTimerRef.current);
        pendingWorkspaceRetryTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    importJobFilterRef.current = importJobFilter;
  }, [importJobFilter]);

  useEffect(() => {
    const timeout = window.setTimeout(async () => {
      if (!query.trim()) {
        setSymbols([]);
        return;
      }
      try {
        const result = await searchSymbols(query);
        setSymbols(result);
        if (result.length > 0) {
          setSymbolCatalog((current) => {
            const next = { ...current };
            for (const item of result) {
              next[item.symbol] = item;
            }
            return next;
          });
        }
      } catch {
        setSymbols([]);
      }
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [query]);

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
        const result = await getChartData(selectedSymbol.symbol, timeframe, range, waveThresholdPct);
        if (!cancelled) {
          setBars(result.bars);
          setAnalysis(result.chan);
          setWaveAnalysis(result.wave);
          setAnnotations(result.annotations);
          setReviewNotes(result.annotations.filter((item) => item.overlay_type === "review_note"));
          setLoadedWindowStart(result.bars[0]?.trade_date ?? null);
          setLoadedWindowEnd(result.bars.at(-1)?.trade_date ?? null);
          setHasMoreHistory(hasOlderHistory(result.bars[0]?.trade_date, selectedSymbol.first_date));
          setChartStatus(
            result.bars.length > 0
              ? `已加载 ${result.bars.length.toLocaleString()} 根 K 线`
              : selectedRangeMismatch
                ? "当前日期范围不覆盖该标的"
                : minuteFrames.has(timeframe)
                  ? chartEmptyStatus(timeframe, source, dataHealth)
                  : "当前范围暂无 K 线数据",
          );
        }
      } catch (err) {
        if (!cancelled) {
          setBars([]);
          setAnalysis(null);
          setWaveAnalysis(null);
          setAnnotations([]);
          setReviewNotes([]);
          setLoadedWindowStart(null);
          setLoadedWindowEnd(null);
          setHasMoreHistory(false);
          setChartStatus("K 线加载失败");
          setError(formatError(err));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedSymbol, timeframe, dateStart, dateEnd, source, dataHealth, selectedRangeMismatch, waveThresholdPct, ruleRefreshKey]);

  const loadBacktest = useCallback(async (snapshot?: BacktestRequestSnapshot) => {
    await Promise.resolve();
    const request = snapshot ?? {
      symbol: selectedSymbol,
      timeframe,
      dateStart,
      dateEnd,
      waveThresholdPct,
      strategy: backtestStrategy,
      options: backtestOptions,
    };
    if (!request.symbol) {
      setBacktest(null);
      setBacktestStatus("等待选择标的");
      return;
    }
    setIsBacktestLoading(true);
    setBacktestStatus("正在运行回测");
    try {
      const range = { startDate: request.dateStart || undefined, endDate: request.dateEnd || undefined, limit: 520 };
      const result = await getStructureBacktest(request.symbol.symbol, request.timeframe, range, request.strategy, {
        ...request.options,
        thresholdPct: request.waveThresholdPct,
      });
      setBacktest(result);
      setBacktestStatus(result.trades.length > 0 ? `已生成 ${result.trades.length.toLocaleString()} 笔交易` : "当前窗口没有结构交易信号");
    } catch (err) {
      setBacktest(null);
      setBacktestStatus("回测失败");
      setError(formatError(err));
    } finally {
      setIsBacktestLoading(false);
    }
  }, [backtestOptions, backtestStrategy, dateEnd, dateStart, selectedSymbol, timeframe, waveThresholdPct]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void loadBacktest();
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [loadBacktest, ruleRefreshKey]);

  const loadMoreHistory = useCallback(async () => {
    const oldestLoaded = bars[0]?.trade_date;
    if (!selectedSymbol || !oldestLoaded || isLoadingHistory || !hasMoreHistory) {
      return;
    }
    const requestKey = `${selectedSymbol.symbol}:${timeframe}:${oldestLoaded}`;
    if (historyRequestRef.current === requestKey) {
      return;
    }
    historyRequestRef.current = requestKey;
    setIsLoadingHistory(true);
    try {
      const older = await getChartData(selectedSymbol.symbol, timeframe, { before: oldestLoaded, limit: 260 }, waveThresholdPct);
      if (older.bars.length === 0 || older.bars[0]?.trade_date === oldestLoaded) {
        setHasMoreHistory(false);
        setChartStatus("已加载到本地最早数据");
        return;
      }

      const mergedBars = mergeBars(older.bars, bars);
      const mergedStart = mergedBars[0]?.trade_date;
      const mergedEnd = mergedBars.at(-1)?.trade_date;
      setBars(mergedBars);
      setLoadedWindowStart(mergedStart ?? null);
      setLoadedWindowEnd(mergedEnd ?? null);
      setHasMoreHistory(hasOlderHistory(mergedStart, selectedSymbol.first_date));
      setChartStatus(`已加载 ${mergedBars.length.toLocaleString()} 根 K 线`);

      if (mergedStart && mergedEnd && mergedBars.length <= 2000) {
        const refreshed = await getChartData(
          selectedSymbol.symbol,
          timeframe,
          {
            startDate: dateOnly(mergedStart),
            endDate: dateOnly(mergedEnd),
            limit: Math.min(Math.max(mergedBars.length + 20, 520), 2000),
          },
          waveThresholdPct,
        );
        const refreshedBars = mergeBars(refreshed.bars);
        setBars(refreshedBars);
        setAnalysis(refreshed.chan);
        setWaveAnalysis(refreshed.wave);
        setAnnotations(refreshed.annotations);
        setReviewNotes(refreshed.annotations.filter((item) => item.overlay_type === "review_note"));
        setLoadedWindowStart(refreshedBars[0]?.trade_date ?? mergedStart);
        setLoadedWindowEnd(refreshedBars.at(-1)?.trade_date ?? mergedEnd);
        setChartStatus(`已加载 ${refreshedBars.length.toLocaleString()} 根 K 线`);
      }
    } catch (err) {
      setError(formatError(err));
      setChartStatus("历史数据加载失败");
    } finally {
      setIsLoadingHistory(false);
      historyRequestRef.current = null;
    }
  }, [bars, hasMoreHistory, isLoadingHistory, selectedSymbol, timeframe, waveThresholdPct]);

  useEffect(() => {
    void loadRuleProfiles();
  }, []);

  const sourceHealthItems = useMemo(() => {
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

  const dataSummaryItems = useMemo(
    () => [
      ["库内最新 T 日", dataHealth?.latest_trade_date ?? "-"],
      ["滞后自然日", dataHealth?.days_since_latest == null ? "-" : `${dataHealth.days_since_latest} 天`],
      ["日线标的", formatCount(dataHealth?.daily_symbols)],
      ["日线 K 线", formatCount(dataHealth?.daily_bars)],
      ["全库跨度", formatDateRange(dataHealth?.first_trade_date, dataHealth?.latest_trade_date)],
      ["当前标的", selectedSymbol ? formatDateRange(selectedSymbol.first_date, selectedSymbol.last_date) : "-"],
      ["图表窗口", formatDateRange(loadedWindowStart ?? dateStart, loadedWindowEnd ?? dateEnd)],
      ["图表 K 线", bars.length.toLocaleString()],
    ],
    [bars.length, dataHealth, dateEnd, dateStart, loadedWindowEnd, loadedWindowStart, selectedSymbol],
  );

  const minuteStatuses = useMemo(() => buildMinuteStatuses(source, dataHealth), [source, dataHealth]);
  const displayRecommendations = useMemo(
    () => mergeDataRecommendations(dataHealth?.recommendations ?? [], minuteStatuses),
    [dataHealth, minuteStatuses],
  );
  const selectedMinuteStatus = minuteFrameSelected ? statusForTimeframe(timeframe, minuteStatuses) : null;
  const minuteEmptyMessage = minuteChartEmptyMessage(timeframe, selectedMinuteStatus);
  const chartAction =
    minuteFrameSelected && bars.length === 0 && selectedMinuteStatus && !selectedRangeMismatch
      ? minuteChartAction(timeframe, selectedMinuteStatus)
      : null;

  async function refreshSources() {
    setBusy(true);
    setError(null);
    try {
      const [current, detected, health, allJobs, filteredJobs] = await Promise.all([
        getCurrentSource(),
        detectSources(),
        getDataHealth(),
        listImportJobs(20),
        listImportJobsWithFilters(20, importJobFiltersFromSelection(importJobFilterRef.current)),
      ]);
      setCandidates(detected);
      setSource(current.health);
      setDataHealth(health);
      setManualPath(current.path ?? detected.find((item) => item.valid)?.path ?? "");
      const latestJob = allJobs[0] ?? null;
      const latestSucceededJob = allJobs.find((item) => item.status === "succeeded") ?? null;
      setImportJobs(filteredJobs);
      setImportJob(latestJob);
      setImportResult(latestSucceededJob ? importResultFromJob(latestSucceededJob) : null);
      if (latestJob && (latestJob.status === "queued" || latestJob.status === "running")) {
        setStatus(importJobStatusText(latestJob));
      } else if (latestJob?.status === "failed") {
        setStatus(latestJob.message || latestJob.errors[0] || "最近导入任务失败");
      } else {
        setStatus(current.valid ? "已连接通达信数据源" : "未配置数据源");
      }
      if (health.daily_symbols > 0) {
        await autoSelectDefaultSymbolIfMissing(!startupDefaultSymbolAppliedRef.current);
        startupDefaultSymbolAppliedRef.current = true;
      }
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

  async function runImportFlow(
    path: string,
    resetImportResult = true,
    options?: { onError?: (message: string) => void },
  ) {
    if (importJobFilterRef.current !== "all" && importJobFilterRef.current !== "pending") {
      importJobFilterRef.current = "pending";
      setImportJobFilter("pending");
    }
    setBusy(true);
    setError(null);
    if (resetImportResult) {
      setImportResult(null);
    }
    setImportJob(null);
    setStatus("正在启动导入任务");
    try {
      let job = await startImportJob(path);
      setImportJob(job);
      setImportJobs((current) => mergeImportJobsByFilter(current, job, importJobFilterRef.current));
      setStatus(importJobStatusText(job));
      while (job.status === "queued" || job.status === "running") {
        await sleep(1000);
        job = await getImportJob(job.id);
        setImportJob(job);
        setImportJobs((current) => mergeImportJobsByFilter(current, job, importJobFilterRef.current));
        setStatus(importJobStatusText(job));
      }
      if (job.status === "failed") {
        throw new Error(job.message || job.errors[0] || "导入任务失败");
      }
      const result = importResultFromJob(job);
      setImportResult(result);
      setStatus(
        `导入完成：${result.files_imported}/${result.files_seen} 日线文件，${result.minute_files_imported}/${result.minute_files_seen} 分钟文件，${result.symbols_imported.toLocaleString()} 个标的`
      );
      const [health, current] = await Promise.all([getDataHealth(), getCurrentSource()]);
      setDataHealth(health);
      setSource(current.health);
      const latestJobs = await listImportJobsWithFilters(20, importJobFiltersFromSelection(importJobFilterRef.current));
      setImportJobs(latestJobs);
      if (query.trim()) {
        setSymbols(await searchSymbols(query));
      }
      await autoSelectDefaultSymbolIfMissing();
    } catch (err) {
      const errorMessage = formatError(err);
      setError(errorMessage);
      options?.onError?.(errorMessage);
      setStatus("导入失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleImport() {
    await runImportFlow(manualPath, true);
  }

  async function handleRetryImportJob(job: ImportJob) {
    setActivePanel("data");
    if (!job.source_path) {
      setStatus("该任务缺少数据源路径，无法重试");
      setHighlightSourcePathInput(true);
      requestAnimationFrame(() => sourcePathInputRef.current?.focus());
      return;
    }
    if (job.source_path_exists === false) {
      setManualPath(job.source_path);
      setStatus("原任务路径已失效，请更新数据源路径后再重试");
      setHighlightSourcePathInput(true);
      requestAnimationFrame(() => sourcePathInputRef.current?.focus());
      return;
    }
    setHighlightSourcePathInput(false);
    setManualPath(job.source_path);
    await runImportFlow(job.source_path, false, {
      onError: (message) => {
        if (
          message.includes("数据源路径无效") ||
          message.includes("数据源路径不能为空") ||
          message.includes("数据源无效：没有找到可导入的日线文件")
        ) {
          setHighlightSourcePathInput(true);
          setStatus("原任务路径已失效，请更新数据源路径后再重试");
          requestAnimationFrame(() => sourcePathInputRef.current?.focus());
        }
      },
    });
  }

  useEffect(() => {
    if (!importJob || busy || (importJob.status !== "queued" && importJob.status !== "running")) {
      if (!importJob || (importJob.status !== "queued" && importJob.status !== "running")) {
        importJobPollingRef.current = null;
      }
      return;
    }
    if (importJobPollingRef.current === importJob.id) {
      return;
    }
    importJobPollingRef.current = importJob.id;
    let cancelled = false;
    void (async () => {
      let job = importJob;
      while (!cancelled && (job.status === "queued" || job.status === "running")) {
        await sleep(1000);
        job = await getImportJob(job.id);
        if (cancelled) {
          return;
        }
        setImportJob(job);
        setImportJobs((current) => mergeImportJobsByFilter(current, job, importJobFilterRef.current));
        setStatus(importJobStatusText(job));
      }
      if (cancelled) {
        return;
      }
      if (job.status === "succeeded") {
        const result = importResultFromJob(job);
        setImportResult(result);
        setStatus(
          `导入完成：${result.files_imported}/${result.files_seen} 日线文件，${result.minute_files_imported}/${result.minute_files_seen} 分钟文件，${result.symbols_imported.toLocaleString()} 个标的`
        );
        const [health, current] = await Promise.all([getDataHealth(), getCurrentSource()]);
        if (cancelled) {
          return;
        }
        setDataHealth(health);
        setSource(current.health);
        await autoSelectDefaultSymbolIfMissing();
      }
      importJobPollingRef.current = null;
    })().catch((err) => {
      if (!cancelled) {
        setError(formatError(err));
        setStatus("导入状态同步失败");
      }
      importJobPollingRef.current = null;
    });
    return () => {
      cancelled = true;
    };
  }, [autoSelectDefaultSymbolIfMissing, busy, importJob]);

  useEffect(() => {
    if (activePanel !== "data") {
      return;
    }
    let cancelled = false;
    const syncRecentJobs = async () => {
      try {
        const jobs = await listImportJobsWithFilters(20, importJobFiltersFromSelection(importJobFilter));
        if (cancelled) {
          return;
        }
        setImportJobs(jobs);
        if (importJobFilter === "all") {
          const latestJob = jobs[0] ?? null;
          const latestSucceededJob = jobs.find((item) => item.status === "succeeded") ?? null;
          if (latestJob) {
            setImportJob(latestJob);
          }
          if (latestSucceededJob) {
            setImportResult(importResultFromJob(latestSucceededJob));
          }
        }
      } catch {
        // 面板轮询失败时静默，避免打断主工作流。
      }
    };
    void syncRecentJobs();
    const timer = window.setInterval(() => {
      void syncRecentJobs();
    }, 8000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activePanel, importJobFilter]);

  async function loadRuleProfiles() {
    try {
      const profiles = await getRuleProfiles();
      setRuleProfiles(profiles);
      setRuleDraft(ruleDraftFromProfiles(profiles));
    } catch (err) {
      setRuleProfiles([]);
      setRuleDraft(defaultRuleDraft);
      setError(formatError(err));
    }
  }

  async function handleCreateAnnotation() {
    if (!selectedSymbol || !annotationDraft.trim()) {
      return;
    }
    const anchorBar = bars.at(-1) ?? null;
    setBusy(true);
    setError(null);
    try {
      const created = await createAnnotation(selectedSymbol.symbol, timeframe, "note", {
        note: annotationDraft.trim(),
        source: "workbench",
        anchor: anchorBar ? "latest_bar" : null,
        trade_date: anchorBar?.trade_date ?? null,
        price: anchorBar?.close ?? null,
        bar_count: bars.length,
        chan_algorithm: displayedAnalysis?.algorithm ?? null,
        chan_version: displayedAnalysis?.version ?? null,
        manual_chan_annotation_id: manualChanAnnotation?.id ?? null,
        wave_algorithm: waveAnalysis?.algorithm ?? null,
        wave_version: waveAnalysis?.version ?? null,
        locked: false,
        confirmed: false,
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

  async function handleSaveReviewNote() {
    if (!selectedSymbol || !reviewDraft.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await saveReviewNote({
        symbol: selectedSymbol.symbol,
        timeframe,
        title: reviewTitle.trim() || "复盘笔记",
        content: reviewDraft.trim(),
        tags: parseTagInput(reviewTags),
        payload: {
          note: reviewTitle.trim() || "复盘笔记",
          date_start: dateStart || null,
          date_end: dateEnd || null,
          loaded_window_start: loadedWindowStart,
          loaded_window_end: loadedWindowEnd,
          bar_count: bars.length,
          chan_algorithm: displayedAnalysis?.algorithm ?? null,
          chan_version: displayedAnalysis?.version ?? null,
          chan_generated_at: displayedAnalysis?.generated_at ?? null,
          manual_chan_annotation_id: manualChanAnnotation?.id ?? null,
          wave_algorithm: displayedWaveAnalysis?.algorithm ?? null,
          wave_version: displayedWaveAnalysis?.version ?? null,
          wave_generated_at: displayedWaveAnalysis?.generated_at ?? null,
          wave_threshold_pct: displayedWaveAnalysis?.threshold_pct ?? null,
          manual_wave_annotation_id: manualWaveAnnotation?.id ?? null,
        },
      });
      setAnnotations((current) => [created, ...current]);
      setReviewNotes((current) => [created, ...current]);
      setReviewDraft("");
      setStatus("复盘笔记已保存");
    } catch (err) {
      setError(formatError(err));
      setStatus("复盘笔记保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveManualWave() {
    if (!selectedSymbol || !waveAnalysis || waveAnalysis.pivots.length === 0) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await createAnnotation(selectedSymbol.symbol, timeframe, "wave", {
        note: `${selectedWaveLevel.label} ZigZag 人工浪型`,
        source: "wave-panel",
        active: true,
        locked: false,
        confirmed: true,
        bar_count: bars.length,
        threshold_pct: waveAnalysis.threshold_pct,
        wave_algorithm: waveAnalysis.algorithm,
        wave_version: waveAnalysis.version,
        wave_generated_at: waveAnalysis.generated_at,
        pivots: waveAnalysis.pivots,
      });
      setAnnotations((current) => [created, ...current]);
      setStatus("当前浪型已保存为人工浪型");
      void loadBacktest();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveManualChan() {
    if (!selectedSymbol || !analysis || (analysis.fractals.length === 0 && analysis.bis.length === 0 && analysis.segments.length === 0 && analysis.zhongshu.length === 0)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await createAnnotation(selectedSymbol.symbol, timeframe, "chan", {
        note: "缠论结构人工覆盖",
        source: "chan-panel",
        active: true,
        locked: false,
        confirmed: true,
        bar_count: bars.length,
        chan_algorithm: analysis.algorithm,
        chan_version: analysis.version,
        chan_generated_at: analysis.generated_at,
        params: analysis.params,
        fractals: analysis.fractals,
        bis: analysis.bis,
        segments: analysis.segments,
        zhongshu: analysis.zhongshu,
      });
      setAnnotations((current) => [created, ...current]);
      setStatus("当前缠论结构已保存为人工覆盖");
      void loadBacktest();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveDefaultChanRule() {
    const params = {
      strict_fractal: false,
      include_containment: ruleDraft.chanIncludeContainment,
      min_bars_for_bi: clampNumber(ruleDraft.chanMinBarsForBi, 1, 20, defaultRuleDraft.chanMinBarsForBi),
      min_bis_for_segment: clampNumber(ruleDraft.chanMinBisForSegment, 1, 12, defaultRuleDraft.chanMinBisForSegment),
      segment_step_bis: clampNumber(ruleDraft.chanSegmentStepBis, 1, 12, defaultRuleDraft.chanSegmentStepBis),
      min_bis_for_zhongshu: clampNumber(ruleDraft.chanMinBisForZhongshu, 1, 12, defaultRuleDraft.chanMinBisForZhongshu),
      zhongshu_step_bis: clampNumber(ruleDraft.chanZhongshuStepBis, 1, 12, defaultRuleDraft.chanZhongshuStepBis),
    };
    setBusy(true);
    setError(null);
    try {
      await createRuleProfile({
        name: `缠论默认规则 ${formatRuleProfileTimestamp(new Date())}`,
        analysis_type: "chan",
        version: displayedAnalysis?.version ?? defaultChanRuleProfile?.version ?? "0.5.0",
        params,
        is_default: true,
      });
      await loadRuleProfiles();
      setRuleRefreshKey((current) => current + 1);
      setStatus("默认缠论规则已保存，并将用于下一次自动分析");
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveDefaultWaveRule() {
    const thresholdPct = clampNumber(ruleDraft.waveThresholdPct, 0.1, 50, defaultRuleDraft.waveThresholdPct);
    const minSwingBars = clampNumber(ruleDraft.waveMinSwingBars, 1, 20, defaultRuleDraft.waveMinSwingBars);
    setBusy(true);
    setError(null);
    try {
      await createRuleProfile({
        name: `波浪 ZigZag 默认 ${formatRuleProfileTimestamp(new Date())}`,
        analysis_type: "wave",
        version: displayedWaveAnalysis?.version ?? defaultWaveRuleProfile?.version ?? "0.1.0",
        params: {
          zigzag_threshold_pct: thresholdPct,
          min_swing_bars: minSwingBars,
        },
        is_default: true,
      });
      setWaveThresholdPct(thresholdPct);
      await loadRuleProfiles();
      setRuleRefreshKey((current) => current + 1);
      setStatus("默认波浪规则已保存，并同步到当前浪级");
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRestoreAutomaticChan() {
    if (!manualChanAnnotation) {
      return;
    }
    setPendingManualChanFractalKind(null);
    setBusy(true);
    setError(null);
    try {
      const updated = await updateAnnotation(manualChanAnnotation.id, null, {
        ...manualChanAnnotation.payload,
        active: false,
        deactivated_at: new Date().toISOString(),
      });
      setAnnotations((current) => current.map((annotation) => (annotation.id === updated.id ? updated : annotation)));
      setStatus("已恢复自动缠论结构");
      void loadBacktest();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleToggleManualChanFractalKind(point: ChanFractalPoint) {
    if (!manualChanAnnotation) {
      return;
    }
    const fractals = parseChanFractals(manualChanAnnotation.payload.fractals);
    const nextKind: ChanFractalPoint["kind"] = point.kind === "top" ? "bottom" : "top";
    const nextFractals = fractals.map((item) =>
      item.index === point.index && item.trade_date === point.trade_date
        ? {
            ...item,
            kind: nextKind,
          }
        : item,
    );
    await saveManualChanFractals(nextFractals, `${point.trade_date} 分型已改为${chanFractalKindLabel(nextKind)}`);
  }

  async function handleDeleteManualChanFractal(point: ChanFractalPoint) {
    if (!manualChanAnnotation) {
      return;
    }
    const fractals = parseChanFractals(manualChanAnnotation.payload.fractals);
    if (fractals.length <= 2) {
      setStatus("至少保留 2 个分型");
      return;
    }
    await saveManualChanFractals(
      fractals.filter((item) => item.index !== point.index || item.trade_date !== point.trade_date),
      `${point.trade_date} 分型已删除`,
    );
  }

  async function handleAddManualChanFractalFromChart(anchor: ChartClickAnchor) {
    if (!manualChanAnnotation || !pendingManualChanFractalKind) {
      setPendingManualChanFractalKind(null);
      return;
    }
    if (annotationLocked(manualChanAnnotation)) {
      setPendingManualChanFractalKind(null);
      setStatus("人工缠论已锁定，不能新增分型");
      return;
    }
    const anchorIndex = bars.findIndex((bar) => bar.trade_date === anchor.tradeDate);
    if (anchorIndex < 0) {
      setStatus("点击位置不在当前 K 线窗口内");
      return;
    }
    const fractals = parseChanFractals(manualChanAnnotation.payload.fractals);
    const nextFractal: ChanFractalPoint = {
      index: anchorIndex,
      trade_date: anchor.tradeDate,
      price: roundPrice(anchor.price),
      kind: pendingManualChanFractalKind,
    };
    const remainingFractals = fractals.filter((item) => item.index !== nextFractal.index && item.trade_date !== nextFractal.trade_date);
    setPendingManualChanFractalKind(null);
    await saveManualChanFractals([...remainingFractals, nextFractal], `${chanFractalKindLabel(nextFractal.kind)}已添加：${anchor.tradeDate}`);
  }

  function beginAddManualChanFractal(kind: ChanFractalPoint["kind"]) {
    if (!manualChanAnnotation) {
      setStatus("请先保存当前缠论结构为人工覆盖");
      return;
    }
    if (annotationLocked(manualChanAnnotation)) {
      setStatus("人工缠论已锁定，不能新增分型");
      return;
    }
    setMovingAnnotationId(null);
    setPendingManualWavePivotKind(null);
    setPendingManualChanFractalKind((current) => (current === kind ? null : kind));
    setStatus(`${chanFractalKindLabel(kind)}添加模式：点击 K 线图选择位置`);
  }

  async function saveManualChanFractals(fractals: ChanFractalPoint[], successMessage: string) {
    if (!manualChanAnnotation) {
      return;
    }
    if (annotationLocked(manualChanAnnotation)) {
      setStatus("人工缠论已锁定，不能修改分型");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await updateAnnotation(manualChanAnnotation.id, null, {
        ...manualChanAnnotation.payload,
        fractals: renumberChanFractals(fractals),
        bis: [],
        segments: [],
        zhongshu: [],
        edited_at: new Date().toISOString(),
        structure_reset_reason: "manual_fractal_edit",
      });
      setAnnotations((current) => current.map((annotation) => (annotation.id === updated.id ? updated : annotation)));
      setStatus(successMessage);
      void loadBacktest();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRestoreAutomaticWave() {
    if (!manualWaveAnnotation) {
      return;
    }
    setPendingManualWavePivotKind(null);
    setBusy(true);
    setError(null);
    try {
      const updated = await updateAnnotation(manualWaveAnnotation.id, null, {
        ...manualWaveAnnotation.payload,
        active: false,
        deactivated_at: new Date().toISOString(),
      });
      setAnnotations((current) => current.map((annotation) => (annotation.id === updated.id ? updated : annotation)));
      setStatus("已恢复自动波浪候选");
      void loadBacktest();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleToggleManualWavePivotKind(point: WavePivot) {
    if (!manualWaveAnnotation || point.kind === "start") {
      return;
    }
    const pivots = parseWavePivots(manualWaveAnnotation.payload.pivots);
    const nextKind: WavePivot["kind"] = point.kind === "top" ? "bottom" : "top";
    const nextPivots = pivots.map((item) =>
      item.wave_no === point.wave_no
        ? {
            ...item,
            kind: nextKind,
          }
        : item,
    );
    await saveManualWavePivots(nextPivots, `W${point.wave_no} 已改为${waveKindLabel(nextKind)}`);
  }

  async function handleDeleteManualWavePivot(point: WavePivot) {
    if (!manualWaveAnnotation) {
      return;
    }
    const pivots = parseWavePivots(manualWaveAnnotation.payload.pivots);
    if (pivots.length <= 2) {
      setStatus("至少保留 2 个浪点");
      return;
    }
    await saveManualWavePivots(
      pivots.filter((item) => item.wave_no !== point.wave_no),
      `W${point.wave_no} 已从人工浪型删除`,
    );
  }

  async function handleAddManualWavePivotFromChart(anchor: ChartClickAnchor) {
    if (!manualWaveAnnotation || !pendingManualWavePivotKind) {
      setPendingManualWavePivotKind(null);
      return;
    }
    if (annotationLocked(manualWaveAnnotation)) {
      setPendingManualWavePivotKind(null);
      setStatus("人工浪型已锁定，不能新增浪点");
      return;
    }
    const anchorIndex = bars.findIndex((bar) => bar.trade_date === anchor.tradeDate);
    if (anchorIndex < 0) {
      setStatus("点击位置不在当前 K 线窗口内");
      return;
    }
    const pivots = parseWavePivots(manualWaveAnnotation.payload.pivots);
    const nextPivot: WavePivot = {
      index: anchorIndex,
      trade_date: anchor.tradeDate,
      price: roundPrice(anchor.price),
      kind: pendingManualWavePivotKind,
      wave_no: pivots.length + 1,
    };
    setPendingManualWavePivotKind(null);
    await saveManualWavePivots([...pivots, nextPivot], `${waveKindLabel(nextPivot.kind)}浪点已添加：${anchor.tradeDate}`);
  }

  function beginAddManualWavePivot(kind: Exclude<WavePivot["kind"], "start">) {
    if (!manualWaveAnnotation) {
      setStatus("请先保存当前浪型为人工浪型");
      return;
    }
    if (annotationLocked(manualWaveAnnotation)) {
      setStatus("人工浪型已锁定，不能新增浪点");
      return;
    }
    setMovingAnnotationId(null);
    setPendingManualChanFractalKind(null);
    setPendingManualWavePivotKind((current) => (current === kind ? null : kind));
    setStatus(`${waveKindLabel(kind)}浪点添加模式：点击 K 线图选择位置`);
  }

  async function saveManualWavePivots(pivots: WavePivot[], successMessage: string) {
    if (!manualWaveAnnotation) {
      return;
    }
    if (annotationLocked(manualWaveAnnotation)) {
      setStatus("人工浪型已锁定，不能改浪");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await updateAnnotation(manualWaveAnnotation.id, null, {
        ...manualWaveAnnotation.payload,
        pivots: renumberWavePivots(pivots),
        edited_at: new Date().toISOString(),
      });
      setAnnotations((current) => current.map((annotation) => (annotation.id === updated.id ? updated : annotation)));
      setStatus(successMessage);
      void loadBacktest();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleToggleAnnotationFlag(item: AnnotationRecord, flag: "locked" | "confirmed") {
    const nextValue = !item.payload[flag];
    const nextPayload = {
      ...item.payload,
      [flag]: nextValue,
    };
    setBusy(true);
    setError(null);
    try {
      const updated = await updateAnnotation(item.id, null, nextPayload);
      setAnnotations((current) => current.map((annotation) => (annotation.id === updated.id ? updated : annotation)));
      if (flag === "locked" && nextValue) {
        setMovingAnnotationId((current) => (current === item.id ? null : current));
        if (item.overlay_type === "chan") {
          setPendingManualChanFractalKind(null);
        }
        if (item.overlay_type === "wave") {
          setPendingManualWavePivotKind(null);
        }
      }
      setStatus(flag === "locked" ? (nextValue ? "标注已锁定" : "标注已解锁") : nextValue ? "标注已确认" : "标注已取消确认");
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleMoveAnnotationToChart(anchor: ChartClickAnchor) {
    if (!movingAnnotationId || annotationMode !== "edit") {
      return;
    }
    const annotation = annotations.find((item) => item.id === movingAnnotationId);
    if (!annotation) {
      setMovingAnnotationId(null);
      return;
    }
    if (!annotationMovable(annotation)) {
      setMovingAnnotationId(null);
      setStatus("该类型标注不能移动锚点");
      return;
    }
    if (annotationLocked(annotation)) {
      setMovingAnnotationId(null);
      setStatus("标注已锁定，不能移动锚点");
      return;
    }
    const nextPayload = {
      ...annotation.payload,
      anchor: "manual_chart_click",
      trade_date: anchor.tradeDate,
      price: roundPrice(anchor.price),
      moved_at: new Date().toISOString(),
    };
    setBusy(true);
    setError(null);
    try {
      const updated = await updateAnnotation(annotation.id, null, nextPayload);
      setAnnotations((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setMovingAnnotationId(null);
      setStatus(`标注位置已更新：${anchor.tradeDate} @ ${formatPrice(roundPrice(anchor.price))}`);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  function handleToggleAnnotationMove(item: AnnotationRecord) {
    const nextId = movingAnnotationId === item.id ? null : item.id;
    setMovingAnnotationId(nextId);
    setPendingManualChanFractalKind(null);
    setPendingManualWavePivotKind(null);
    setStatus(nextId ? "请选择图表上的目标 K 线位置，或按住拖拽到目标位置后松开" : "已取消移动标注");
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

  function resetRangeForSelectedSymbol() {
    if (minuteFrameSelected) {
      applyIntradayRange();
      return;
    }
    applyDefaultRange();
  }

  function handleTimeframeChange(nextFrame: string) {
    setTimeframe(nextFrame);
    setMovingAnnotationId(null);
    setPendingManualChanFractalKind(null);
    setPendingManualWavePivotKind(null);
    if (dateRangeTouched) {
      return;
    }
    if (minuteFrames.has(nextFrame)) {
      applyIntradayRange();
      return;
    }
    applyDefaultRange();
  }

  function handleDateStartChange(value: string) {
    setDateStart(value);
    setDateRangeTouched(true);
  }

  function handleDateEndChange(value: string) {
    setDateEnd(value);
    setDateRangeTouched(true);
  }

  function updateRuleDraftNumber(key: RuleDraftNumberKey, value: string) {
    const fallback = defaultRuleDraft[key];
    const [min, max] = ruleDraftNumberRange(key);
    setRuleDraft((current) => ({
      ...current,
      [key]: clampNumber(Number(value), min, max, fallback),
    }));
  }

  function updateBacktestOption(key: "feeBps" | "slippageBps" | "positionPct" | "limitPct", value: string) {
    const fallback = key === "positionPct" ? 100 : key === "limitPct" ? 10 : 0;
    const max = key === "positionPct" ? 100 : key === "limitPct" ? 30 : 1000;
    const min = key === "limitPct" ? 0.1 : 0;
    const nextValue = clampNumber(Number(value), 0, max, fallback);
    setBacktestOptions((current) => ({
      ...current,
      [key]: clampNumber(nextValue, min, max, fallback),
    }));
  }

  function updateBacktestLimitConstraint(enabled: boolean) {
    setBacktestOptions((current) => ({
      ...current,
      applyLimitConstraints: enabled,
    }));
  }

  function clearAnnotationInteractionState() {
    setMovingAnnotationId(null);
    setPendingManualChanFractalKind(null);
    setPendingManualWavePivotKind(null);
    setAnnotationDeleteTarget(null);
  }

  async function handleDeleteAnnotation(id: string) {
    setBusy(true);
    setError(null);
    const deletedAnnotation = annotationDeleteTarget?.id === id ? annotationDeleteTarget : annotations.find((item) => item.id === id) ?? null;
    try {
      await deleteAnnotation(id);
      setAnnotations((current) => current.filter((item) => item.id !== id));
      setReviewNotes((current) => current.filter((item) => item.id !== id));
      setMovingAnnotationId((current) => (current === id ? null : current));
      if (deletedAnnotation?.overlay_type === "chan") {
        setPendingManualChanFractalKind(null);
        void loadBacktest();
      }
      if (deletedAnnotation?.overlay_type === "wave") {
        setPendingManualWavePivotKind(null);
        void loadBacktest();
      }
      setStatus(deletedAnnotation?.overlay_type === "review_note" ? "复盘笔记已删除" : "标注已删除");
      setAnnotationDeleteTarget(null);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleExportUserBackup() {
    setBusy(true);
    setError(null);
    try {
      const backup = await exportUserBackup();
      downloadJsonFile(backup, `aether-user-backup-${toDateInputValue(new Date())}.json`);
      setStatus(`已导出用户数据：${backup.annotations.length} 条标注，${backup.rule_profiles.length} 个规则配置`);
    } catch (err) {
      setError(formatError(err));
      setStatus("用户数据导出失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleImportUserBackup(file: File | null) {
    if (!file) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const backup = JSON.parse(await file.text());
      const result = await importUserBackup(backup);
      clearAnnotationInteractionState();
      setStatus(`用户数据已导入：${result.annotations_imported} 条标注，${result.rule_profiles_imported} 个规则配置`);
      await refreshSources();
      await loadRuleProfiles();
      setRuleRefreshKey((current) => current + 1);
      if (selectedSymbol) {
        const refreshed = await getChartData(
          selectedSymbol.symbol,
          timeframe,
          {
            startDate: dateStart || undefined,
            endDate: dateEnd || undefined,
            limit: 520,
          },
          waveThresholdPct,
        );
        const refreshedBars = mergeBars(refreshed.bars);
        setBars(refreshedBars);
        setAnalysis(refreshed.chan);
        setWaveAnalysis(refreshed.wave);
        setAnnotations(refreshed.annotations);
        setReviewNotes(refreshed.annotations.filter((item) => item.overlay_type === "review_note"));
        setLoadedWindowStart(refreshedBars[0]?.trade_date ?? null);
        setLoadedWindowEnd(refreshedBars.at(-1)?.trade_date ?? null);
        setHasMoreHistory(hasOlderHistory(refreshedBars[0]?.trade_date, selectedSymbol.first_date));
        setChartStatus(
          refreshedBars.length > 0
            ? `已加载 ${refreshedBars.length.toLocaleString()} 根 K 线`
            : selectedRangeMismatch
              ? "当前日期范围不覆盖该标的"
              : minuteFrames.has(timeframe)
                ? chartEmptyStatus(timeframe, source, dataHealth)
                : "当前范围暂无 K 线数据",
        );
        void loadBacktest({
          symbol: selectedSymbol,
          timeframe,
          dateStart,
          dateEnd,
          waveThresholdPct,
          strategy: backtestStrategy,
          options: backtestOptions,
        });
      }
    } catch (err) {
      setError(formatError(err));
      setStatus("用户数据导入失败");
    } finally {
      if (backupFileInputRef.current) {
        backupFileInputRef.current.value = "";
      }
      setBusy(false);
    }
  }

  async function handleExportAnalysisScheme() {
    setBusy(true);
    setError(null);
    try {
      const schemeDescription = selectedSymbol
        ? `${selectedName} ${timeframe} 周期工作台参数`
        : "AetherStock 工作台参数";
      const scheme = await exportAnalysisScheme(`${selectedName} 分析方案`, schemeDescription);
      const payload: AnalysisSchemePayload = {
        ...scheme,
        workspace: buildAnalysisSchemeWorkspace({
          defaultTimeframe,
          defaultRangeMonths,
          timeframe,
          dateStart,
          dateEnd,
          dateRangeTouched,
          waveThresholdPct,
          backtestStrategy,
          backtestOptions,
          layers,
          theme,
          activePanel,
          importJobFilter,
          selectedSymbol,
          manualLines,
          manualLineStyle,
        }),
      };
      downloadJsonFile(payload, `aether-analysis-scheme-${toDateInputValue(new Date())}.json`);
      setStatus(`已导出分析方案：${payload.rule_profiles.length} 个规则配置，${manualLines.length} 条手工划线`);
    } catch (err) {
      setError(formatError(err));
      setStatus("分析方案导出失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleImportAnalysisScheme(file: File | null) {
    if (!file) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const scheme = JSON.parse(await file.text()) as AnalysisSchemePayload;
      const result = await importAnalysisScheme(scheme);
      clearAnnotationInteractionState();
      const importedWorkspace = applyAnalysisSchemeWorkspace(isRecord(scheme.workspace) ? scheme.workspace : {}, {
        setDefaultTimeframe,
        setDefaultRangeMonths,
        setTimeframe,
        setDateStart,
        setDateEnd,
        setDateRangeTouched,
        setWaveThresholdPct,
        setBacktestStrategy,
        setBacktestOptions,
        setLayers,
        setTheme,
        setActivePanel,
        setImportJobFilter,
        setSelectedSymbol,
        setManualLines,
        setManualLineStyle,
      });
      await loadRuleProfiles();
      const effectiveSymbol = importedWorkspace.selectedSymbol === undefined ? selectedSymbol : importedWorkspace.selectedSymbol;
      const effectiveTimeframe = importedWorkspace.timeframe ?? timeframe;
      const effectiveDateStart = importedWorkspace.dateStart ?? dateStart;
      const effectiveDateEnd = importedWorkspace.dateEnd ?? dateEnd;
      const effectiveWaveThresholdPct = importedWorkspace.waveThresholdPct ?? waveThresholdPct;
      const effectiveBacktestStrategy = importedWorkspace.backtestStrategy ?? backtestStrategy;
      const effectiveBacktestOptions = importedWorkspace.backtestOptions ?? backtestOptions;
      if (effectiveSymbol) {
        const range = {
          startDate: effectiveDateStart || undefined,
          endDate: effectiveDateEnd || undefined,
          limit: 520,
        };
        const refreshed = await getChartData(effectiveSymbol.symbol, effectiveTimeframe, range, effectiveWaveThresholdPct);
        const refreshedBars = mergeBars(refreshed.bars);
        setBars(refreshedBars);
        setAnalysis(refreshed.chan);
        setWaveAnalysis(refreshed.wave);
        setAnnotations(refreshed.annotations);
        setReviewNotes(refreshed.annotations.filter((item) => item.overlay_type === "review_note"));
        setLoadedWindowStart(refreshedBars[0]?.trade_date ?? null);
        setLoadedWindowEnd(refreshedBars.at(-1)?.trade_date ?? null);
        setHasMoreHistory(hasOlderHistory(refreshedBars[0]?.trade_date, effectiveSymbol.first_date));
        setChartStatus(
          refreshedBars.length > 0
            ? `已加载 ${refreshedBars.length.toLocaleString()} 根 K 线`
            : minuteFrames.has(effectiveTimeframe)
              ? chartEmptyStatus(effectiveTimeframe, source, dataHealth)
              : "当前范围暂无 K 线数据",
        );
        await loadBacktest({
          symbol: effectiveSymbol,
          timeframe: effectiveTimeframe,
          dateStart: effectiveDateStart,
          dateEnd: effectiveDateEnd,
          waveThresholdPct: effectiveWaveThresholdPct,
          strategy: effectiveBacktestStrategy,
          options: effectiveBacktestOptions,
        });
      } else {
        setBars([]);
        setAnalysis(null);
        setWaveAnalysis(null);
        setAnnotations([]);
        setReviewNotes([]);
        setLoadedWindowStart(null);
        setLoadedWindowEnd(null);
        setHasMoreHistory(false);
        setBacktest(null);
        setBacktestStatus("等待选择标的");
        setChartStatus("请选择标的");
      }
      setRuleRefreshKey((current) => current + 1);
      const importedManualLineCount = importedWorkspace.manualLines === undefined ? manualLines.length : (importedWorkspace.manualLines?.length ?? 0);
      setStatus(`分析方案已导入：${result.rule_profiles_imported} 个规则配置，${importedManualLineCount} 条手工划线`);
    } catch (err) {
      setError(formatError(err));
      setStatus("分析方案导入失败");
    } finally {
      if (schemeFileInputRef.current) {
        schemeFileInputRef.current.value = "";
      }
      setBusy(false);
    }
  }

  function handleExportReviewReport() {
    if (!selectedSymbol) {
      return;
    }
    const report = buildReviewReportMarkdown({
      selectedSymbol,
      selectedName,
      selectedCode,
      timeframeLabel: selectedTimeframe.label,
      timeframe,
      dateStart,
      dateEnd,
      loadedWindowStart,
      loadedWindowEnd,
      bars,
      analysis: displayedAnalysis,
      waveAnalysis: displayedWaveAnalysis,
      backtest,
      manualChanAnnotation,
      manualWaveAnnotation,
      annotations: workbenchAnnotations,
      reviewNotes,
      ruleProfiles,
      layers,
      chartStatus,
      dataHealth,
    });
    downloadTextFile(
      report,
      `aether-review-report-${selectedSymbol.symbol}-${timeframe}-${toDateInputValue(new Date())}.md`,
      "text/markdown",
    );
    setStatus("复盘报告已导出");
  }

  function handleExportChartScreenshot() {
    if (!selectedSymbol || bars.length === 0) {
      return;
    }
    const dataUrl = klineChartRef.current?.takeScreenshotDataUrl();
    if (!dataUrl) {
      setError("图表截图生成失败");
      return;
    }
    downloadDataUrlFile(
      dataUrl,
      `aether-chart-${selectedSymbol.symbol}-${timeframe}-${toDateInputValue(new Date())}.png`,
    );
    setStatus("K 线截图已导出");
  }

  function handleExportBacktestCsv() {
    if (!selectedSymbol || !hasBacktestCsvRows(backtest)) {
      return;
    }
    downloadTextFile(
      formatBacktestTradesCsv(backtest),
      `aether-backtest-trades-${selectedSymbol.symbol}-${timeframe}-${backtest.strategy}-${toDateInputValue(new Date())}.csv`,
      "text/csv;charset=utf-8",
    );
    setStatus("回测交易明细已导出");
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
            ref={sourcePathInputRef}
            className={highlightSourcePathInput ? "path-input path-input-attention" : "path-input"}
            value={manualPath}
            onChange={(event) => {
              setManualPath(event.target.value);
              setHighlightSourcePathInput(false);
            }}
            placeholder="选择或粘贴通达信 vipdoc 路径"
          />
          {highlightSourcePathInput && <p className="path-input-hint">原任务路径已失效，请更新数据源路径后重试导入。</p>}
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
          {importJob && <ImportJobProgress job={importJob} compact />}
        </section>

        <section className="surface search-panel">
          <div className="section-title">
            <Search size={18} />
            <span>证券搜索</span>
          </div>
          <div className="search-box">
            <Search size={17} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入代码 / 名称搜索" />
          </div>
          <div className="symbol-group-toolbar">
            <div className="segmented symbol-group-tabs" aria-label="证券列表分组">
              <button
                className={activeSymbolGroupId === "__all" ? "selected" : ""}
                onClick={() => setActiveSymbolGroupId("__all")}
                type="button"
              >
                全部
              </button>
              <button
                className={activeSymbolGroupId === "__favorites" ? "selected" : ""}
                onClick={() => setActiveSymbolGroupId("__favorites")}
                type="button"
              >
                收藏
              </button>
              {symbolGroups.map((group) => (
                <button
                  key={group.id}
                  className={activeSymbolGroupId === group.id ? "selected" : ""}
                  onClick={() => setActiveSymbolGroupId(group.id)}
                  type="button"
                >
                  {group.name}
                </button>
              ))}
            </div>
            <div className="symbol-group-actions">
              <button className="tonal-button compact-button" type="button" onClick={createSymbolGroup}>
                <FolderPlus size={15} />
                新分组
              </button>
              <button className="tonal-button compact-button" type="button" onClick={addSelectedSymbolToGroup} disabled={!selectedSymbol}>
                <FolderPlus size={15} />
                加入分组
              </button>
            </div>
          </div>
          <div className="symbol-list">
            {displayedSymbols.map((item) => (
              <div key={item.symbol} className={selectedSymbol?.symbol === item.symbol ? "symbol-row active" : "symbol-row"}>
                <button type="button" className="symbol-select" onClick={() => handleSelectSymbol(item)}>
                  <span>
                    <strong>{displayName(item)}</strong>
                    <small>
                      {item.symbol.toUpperCase()} · {kindLabel(item.kind)}
                    </small>
                  </span>
                  <span>{item.last_date ?? "-"}</span>
                </button>
                <button
                  type="button"
                  className={favoriteSymbolSet.has(item.symbol) ? "symbol-favorite active" : "symbol-favorite"}
                  title={favoriteSymbolSet.has(item.symbol) ? "取消收藏" : "收藏"}
                  onClick={() => toggleFavoriteSymbol(item)}
                >
                  <Star size={15} />
                </button>
              </div>
            ))}
            {displayedSymbols.length === 0 && (
              <p className="empty-note">
                {query.trim()
                  ? "没有匹配的证券。"
                  : selectedSymbol
                    ? `当前已选 ${displayName(selectedSymbol)}，可继续搜索切换标的。`
                    : "输入代码或名称后选择标的。"}
              </p>
            )}
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
          <div className="top-bar-controls">
            <div className="segmented" aria-label="K 线周期">
              {timeframes.map((frame) => (
                <button key={frame.value} className={timeframe === frame.value ? "selected" : ""} onClick={() => handleTimeframeChange(frame.value)}>
                  {frame.label}
                </button>
              ))}
            </div>
            <div className="chart-tools">
              <button
                className={lineDrawingMode ? "filled-button compact-button" : "tonal-button compact-button"}
                type="button"
                onClick={() =>
                  setLineDrawingMode((current) => {
                    const next = !current;
                    setStatus(next ? "划线模式已开启：请在图上点两次（起点 / 终点）。" : "划线模式已关闭。");
                    return next;
                  })
                }
              >
                <PenLine size={15} />
                {lineDrawingMode ? "退出划线" : "划线模式"}
              </button>
              <label className="line-style-control" title="划线颜色">
                <span>颜色</span>
                <input
                  type="color"
                  value={manualLineStyle.color}
                  onChange={(event) =>
                    setManualLineStyle((current) => ({
                      ...current,
                      color: normalizeManualLineColor(event.target.value, current.color),
                    }))
                  }
                />
              </label>
              <label className="line-style-control line-width-control" title="划线粗细">
                <span>粗细</span>
                <input
                  type="range"
                  min={1}
                  max={4}
                  step={1}
                  value={manualLineStyle.width}
                  onChange={(event) =>
                    setManualLineStyle((current) => ({
                      ...current,
                      width: normalizeManualLineWidth(Number(event.target.value)),
                    }))
                  }
                />
                <strong>{manualLineStyle.width}px</strong>
              </label>
              <button
                className="tonal-button compact-button"
                type="button"
                onClick={undoLastManualLine}
                disabled={!selectedSymbol || manualLinesForCurrentChart.length === 0}
              >
                <Trash2 size={15} />
                撤销划线
              </button>
            </div>
          </div>
        </header>

        <section className="chart-surface">
          <ChartErrorBoundary resetKey={`${selectedSymbol?.symbol ?? "none"}:${timeframe}:${fitContentToken}`}>
            <KLineChart
              ref={klineChartRef}
              bars={bars}
              analysis={displayedAnalysis}
              waveAnalysis={displayedWaveAnalysis}
              annotations={workbenchAnnotations}
              backtestTrades={backtest?.trades ?? []}
              layers={layers}
              theme={theme}
              fitContentToken={fitContentToken}
              hasMoreHistory={hasMoreHistory}
              isLoadingHistory={isLoadingHistory}
              onLoadMoreHistory={loadMoreHistory}
              manualLines={manualLinesForCurrentChart}
              manualLineColor={manualLineStyle.color}
              manualLineWidth={manualLineStyle.width}
              lineDrawingMode={lineDrawingMode}
              onLineDrawingHint={setStatus}
              onCreateManualLine={handleCreateManualLine}
              onChartClick={
                movingAnnotationId
                  ? handleMoveAnnotationToChart
                  : pendingManualChanFractalKind
                    ? handleAddManualChanFractalFromChart
                  : pendingManualWavePivotKind
                    ? handleAddManualWavePivotFromChart
                    : undefined
              }
              emptyMessage={
                selectedRangeMismatch
                  ? "当前手动日期范围不覆盖该标的；请在右侧时间范围面板重置到标的最新区间。"
                  : minuteFrameSelected
                    ? minuteEmptyMessage
                    : "先导入通达信行情数据，或选择已导入的证券。"
              }
            />
          </ChartErrorBoundary>
          {chartAction && (
            <div className={`chart-action-card ${selectedMinuteStatus?.state ?? ""}`}>
              <div>
                <strong>{chartAction.title}</strong>
                <span>{chartAction.detail}</span>
              </div>
              <button
                className={chartAction.primary ? "filled-button compact-button" : "tonal-button compact-button"}
                onClick={chartAction.primary ? () => void handleImport() : () => setActivePanel("data")}
                disabled={busy || (chartAction.primary && !manualPath)}
              >
                {chartAction.primary ? <Download size={15} /> : <Database size={15} />}
                {chartAction.label}
              </button>
            </div>
          )}
          {bars.length > 0 && (
            <div className="history-hint">
              <span>
                {isLoadingHistory
                  ? "正在加载更早 K 线"
                  : hasMoreHistory
                    ? "向左拖动 K 线可继续加载历史"
                    : "已加载到本地最早数据"}
              </span>
              {hasMoreHistory && (
                <button className="tonal-button compact-button" onClick={() => void loadMoreHistory()} disabled={isLoadingHistory}>
                  {isLoadingHistory ? "加载中" : "加载更早"}
                </button>
              )}
            </div>
          )}
        </section>

        <section className="bottom-sheet">
          <div>
            <strong>库内数据</strong>
            <span>{dataStoreSummary}</span>
          </div>
          <div>
            <strong>源文件</strong>
            <span>{sourceUpdateSummary}</span>
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
              {(loadedWindowStart ?? dateStart) || "-"} 至 {(loadedWindowEnd ?? dateEnd) || "-"}
              {isLoadingHistory && " · 正在加载历史"}
              {!hasMoreHistory && bars.length > 0 && " · 已到最早"}
            </span>
          </div>
          <div>
            <strong>本次导入</strong>
            <span>
              {importResult
                ? `${importResult.files_imported}/${importResult.files_seen} 日线文件，${importResult.minute_files_imported}/${importResult.minute_files_seen} 分钟文件，${importResult.bars_imported.toLocaleString()} 根日线，${importResult.minute_bars_imported.toLocaleString()} 根分钟线`
                : "尚未导入"}
            </span>
          </div>
          <div>
            <strong>草稿状态</strong>
            <span title={workspaceDraftDetail}>{workspaceDraftSummary}</span>
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

      {annotationDeleteTarget && (
        <div className="dialog-backdrop" role="presentation">
          <div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-annotation-title">
            <h2 id="delete-annotation-title">{annotationDeleteTarget.overlay_type === "review_note" ? "删除复盘笔记" : "删除人工标注"}</h2>
            <p>
              {annotationDeleteTarget.overlay_type === "review_note"
                ? "删除后无法从当前工作台恢复。复盘笔记会从本地标注库中移除。"
                : "删除后无法从当前工作台恢复。已锁定的标注需要先解锁。"}
            </p>
            <div className="dialog-preview">
              <strong>{overlayTypeLabel(annotationDeleteTarget.overlay_type)}</strong>
              <span>{annotationDeleteTarget.overlay_type === "review_note" ? reviewNoteTitle(annotationDeleteTarget) : annotationNote(annotationDeleteTarget)}</span>
            </div>
            <div className="dialog-actions">
              <button className="tonal-button" onClick={() => setAnnotationDeleteTarget(null)} disabled={busy}>
                取消
              </button>
              <button
                className="danger-button"
                onClick={() => void handleDeleteAnnotation(annotationDeleteTarget.id)}
                disabled={busy || annotationLocked(annotationDeleteTarget)}
              >
                删除
              </button>
            </div>
          </div>
        </div>
      )}

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
              通达信下载或更新数据后，需要再次导入，图表才会使用最新文件。
            </p>
            <button className="filled-button full-width" onClick={() => void handleImport()} disabled={busy || !manualPath}>
              <Download size={17} />
              重新导入行情
            </button>
            {importJob && <ImportJobProgress job={importJob} />}
            <div className="health-section-title">最近任务</div>
            <div className="segmented import-job-filter" aria-label="任务状态筛选">
              {[
                { value: "all", label: "全部" },
                { value: "pending", label: "运行中" },
                { value: "failed", label: "失败" },
                { value: "succeeded", label: "成功" },
                { value: "broken", label: "路径失效" },
              ].map((item) => (
                <button
                  key={item.value}
                  className={importJobFilter === item.value ? "selected" : ""}
                  onClick={() => setImportJobFilter(item.value as ImportJobFilter)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <div className="import-job-list">
              {importJobs.slice(0, 5).map((item) => (
                <div key={item.id} className="import-job-item">
                  <div>
                    <span className={`job-dot ${item.status}`} />
                    <strong>{importJobStatusLabel(item.status)}</strong>
                  </div>
                  <span>{item.source_path ?? "-"}</span>
                  <small>
                    {item.files_imported}/{item.files_seen} 日线 · {item.minute_files_imported}/{item.minute_files_seen} 分钟
                    {item.finished_at ? ` · ${formatDateTime(item.finished_at)}` : item.started_at ? ` · ${formatDateTime(item.started_at)}` : ""}
                  </small>
                  {item.status === "failed" && item.source_path_exists === false && <small className="job-path-warning">数据源路径已失效</small>}
                  {item.status === "failed" && (
                    <div className="import-job-actions">
                      <button
                        className="tonal-button import-job-retry"
                        onClick={() => void handleRetryImportJob(item)}
                        disabled={busy}
                        title={
                          !item.source_path
                            ? "任务缺少数据源路径，请先更新路径再重试"
                            : item.source_path_exists === false
                              ? "原任务路径已失效，请先更新路径再重试"
                              : "使用该任务的数据源路径重新发起导入"
                        }
                      >
                        <RefreshCw size={14} />
                        重试
                      </button>
                    </div>
                  )}
                </div>
              ))}
              {importJobs.length === 0 && (
                <p className="empty-note">{importJobFilter === "all" ? "暂无导入任务记录。" : "该状态下暂无任务记录。"}</p>
              )}
            </div>
          </section>
        </>
      );
    }

    if (activePanel === "layers") {
      return (
        <>
          {renderLayerPanel()}
          {renderAnalysisPanel()}
          {renderRuleExplanationPanel()}
        </>
      );
    }

    if (activePanel === "review") {
      return (
        <>
          {renderBacktestPanel()}
          {renderReviewPanel()}
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
          <section className="surface">
            <div className="section-title">
              <Download size={18} />
              <span>用户数据</span>
            </div>
            <p className="explain-text">导出配置、人工标注、复盘笔记和规则参数；行情缓存不会写入备份文件。</p>
            <div className="button-row">
              <button className="tonal-button" onClick={() => void handleExportUserBackup()} disabled={busy}>
                <Download size={17} />
                导出备份
              </button>
              <button className="filled-button" onClick={() => backupFileInputRef.current?.click()} disabled={busy}>
                <Upload size={17} />
                导入备份
              </button>
            </div>
            <input
              ref={backupFileInputRef}
              className="hidden-file-input"
              type="file"
              accept="application/json,.json"
              onChange={(event) => void handleImportUserBackup(event.target.files?.[0] ?? null)}
            />
          </section>
          <section className="surface">
            <div className="section-title">
              <Layers3 size={18} />
              <span>分析方案</span>
            </div>
            <p className="explain-text">导出规则配置、图层开关、默认周期、时间范围、波浪浪级和回测参数；不包含行情缓存、人工标注和复盘笔记。</p>
            <div className="button-row">
              <button className="tonal-button" onClick={() => void handleExportAnalysisScheme()} disabled={busy}>
                <Download size={17} />
                导出方案
              </button>
              <button className="filled-button" onClick={() => schemeFileInputRef.current?.click()} disabled={busy}>
                <Upload size={17} />
                导入方案
              </button>
            </div>
            <input
              ref={schemeFileInputRef}
              className="hidden-file-input"
              type="file"
              accept="application/json,.json"
              onChange={(event) => void handleImportAnalysisScheme(event.target.files?.[0] ?? null)}
            />
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
        {renderRuleExplanationPanel()}
        {renderBacktestPanel()}
        {renderReviewPanel()}
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
          <span>缠论笔</span>
          <input
            type="checkbox"
            checked={layers.bi}
            onChange={(event) => setLayers((current) => ({ ...current, bi: event.target.checked }))}
          />
        </label>
        <label className="switch-row">
          <span>缠论线段</span>
          <input
            type="checkbox"
            checked={layers.segments}
            onChange={(event) => setLayers((current) => ({ ...current, segments: event.target.checked }))}
          />
        </label>
        <label className="switch-row">
          <span>缠论中枢</span>
          <input
            type="checkbox"
            checked={layers.zhongshu}
            onChange={(event) => setLayers((current) => ({ ...current, zhongshu: event.target.checked }))}
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
        <label className="switch-row">
          <span>人工标注</span>
          <input
            type="checkbox"
            checked={layers.annotations}
            onChange={(event) => setLayers((current) => ({ ...current, annotations: event.target.checked }))}
          />
        </label>
        <label className="switch-row">
          <span>回测买卖点</span>
          <input
            type="checkbox"
            checked={layers.backtest}
            onChange={(event) => setLayers((current) => ({ ...current, backtest: event.target.checked }))}
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
              onInput={(event) => handleDateStartChange(event.currentTarget.value)}
              onChange={(event) => handleDateStartChange(event.target.value)}
            />
          </label>
          <label>
            <span>结束</span>
            <input
              type="date"
              value={dateEnd}
              onInput={(event) => handleDateEndChange(event.currentTarget.value)}
              onChange={(event) => handleDateEndChange(event.target.value)}
            />
          </label>
        </div>
        <div className="button-row">
          <button className="tonal-button" onClick={() => applyDefaultRange(6)}>
            近 6 个月
          </button>
          {hasMoreHistory && bars.length > 0 && (
            <button className="tonal-button" onClick={() => void loadMoreHistory()} disabled={isLoadingHistory}>
              {isLoadingHistory ? "加载中" : "加载更早"}
            </button>
          )}
          {selectedRangeMismatch && (
            <button className="tonal-button" onClick={() => resetRangeForSelectedSymbol()}>
              重置到标的最新区间
            </button>
          )}
          {minuteFrameSelected && (
            <button className="tonal-button" onClick={() => applyIntradayRange()}>
              日内近 7 天
            </button>
          )}
        </div>
        {selectedRangeMismatch && (
          <p className="range-warning">
            当前日期范围在 {formatDateRange(selectedSymbol?.first_date, selectedSymbol?.last_date)} 之外。
          </p>
        )}
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
            <strong>{displayedAnalysis?.fractals.length ?? 0}</strong>
          </div>
          <div>
            <span>笔数量</span>
            <strong>{displayedAnalysis?.bis.length ?? 0}</strong>
          </div>
          <div>
            <span>线段数量</span>
            <strong>{displayedAnalysis?.segments.length ?? 0}</strong>
          </div>
          <div>
            <span>中枢数量</span>
            <strong>{displayedAnalysis?.zhongshu.length ?? 0}</strong>
          </div>
          <div>
            <span>波段候选</span>
            <strong>{displayedWaveAnalysis?.pivots.length ?? 0}</strong>
          </div>
          <div>
            <span>当前浪级</span>
            <strong>
              {displayedWaveAnalysis
                ? `${manualWaveAnnotation ? "人工" : selectedWaveLevel.label} · ${displayedWaveAnalysis.threshold_pct}%`
                : "-"}
            </strong>
          </div>
        </div>
        <div className="wave-level-control" aria-label="波浪浪级">
          {waveLevels.map((level) => (
            <button
              key={level.thresholdPct}
              className={waveThresholdPct === level.thresholdPct ? "selected" : ""}
              onClick={() => setWaveThresholdPct(level.thresholdPct)}
            >
              <span>{level.label}</span>
              <small>{level.thresholdPct}%</small>
            </button>
          ))}
        </div>
        <div className="analysis-meta">
          <div>
            <span>缠论算法</span>
            <strong>{displayedAnalysis ? `${displayedAnalysis.algorithm} · ${displayedAnalysis.version}` : "-"}</strong>
            <small>{displayedAnalysis ? `参数 ${formatParams(displayedAnalysis.params)}` : "等待分析结果"}</small>
          </div>
          <div>
            <span>缠论规则来源</span>
            <strong>{chanRuleSourceTitle(displayedAnalysis, manualChanAnnotation, defaultChanRuleProfile)}</strong>
            <small>{chanRuleSourceDetail(displayedAnalysis, manualChanAnnotation, defaultChanRuleProfile)}</small>
          </div>
          <div>
            <span>人工派生结构</span>
            <strong>{manualChanDerivationTitle(displayedAnalysis, manualChanAnnotation)}</strong>
            <small>{manualChanDerivationDetail(displayedAnalysis, manualChanAnnotation)}</small>
          </div>
          <div>
            <span>波浪算法</span>
            <strong>{displayedWaveAnalysis ? `${displayedWaveAnalysis.algorithm} · ${displayedWaveAnalysis.version}` : "-"}</strong>
            <small>{displayedWaveAnalysis ? `参数 ${formatParams(displayedWaveAnalysis.params)}` : "等待分析结果"}</small>
          </div>
          <div>
            <span>波浪规则来源</span>
            <strong>{waveRuleSourceTitle(displayedWaveAnalysis, manualWaveAnnotation, defaultWaveRuleProfile)}</strong>
            <small>{waveRuleSourceDetail(displayedWaveAnalysis, manualWaveAnnotation, defaultWaveRuleProfile, selectedWaveLevel.label)}</small>
          </div>
          <div>
            <span>生成时间</span>
            <strong>{displayedAnalysis?.generated_at ? formatDateTime(displayedAnalysis.generated_at) : "-"}</strong>
            <small>
              {displayedWaveAnalysis?.generated_at ? `波浪 ${formatDateTime(displayedWaveAnalysis.generated_at)}` : "随当前图表区间刷新"}
            </small>
          </div>
        </div>
        <div className="wave-edit-actions">
          <span className={manualChanAnnotation ? "status-chip confirmed" : "status-chip"}>
            {manualChanAnnotation ? "人工缠论优先" : "自动缠论结构"}
          </span>
          <button
            className="tonal-button compact-button"
            onClick={() => void handleSaveManualChan()}
            disabled={
              busy ||
              !selectedSymbol ||
              !analysis ||
              (analysis.fractals.length === 0 && analysis.bis.length === 0 && analysis.segments.length === 0 && analysis.zhongshu.length === 0)
            }
          >
            保存当前缠论
          </button>
          <button
            className="tonal-button compact-button"
            onClick={() => void handleRestoreAutomaticChan()}
            disabled={busy || !manualChanAnnotation}
          >
            恢复自动缠论
          </button>
          <button
            className={pendingManualChanFractalKind === "top" ? "filled-button compact-button" : "tonal-button compact-button"}
            onClick={() => beginAddManualChanFractal("top")}
            disabled={busy || !manualChanAnnotation || annotationLocked(manualChanAnnotation)}
          >
            添加顶分型
          </button>
          <button
            className={pendingManualChanFractalKind === "bottom" ? "filled-button compact-button" : "tonal-button compact-button"}
            onClick={() => beginAddManualChanFractal("bottom")}
            disabled={busy || !manualChanAnnotation || annotationLocked(manualChanAnnotation)}
          >
            添加底分型
          </button>
        </div>
        {pendingManualChanFractalKind && (
          <p className="annotation-mode-note">
            正在添加{chanFractalKindLabel(pendingManualChanFractalKind)}：点击 K 线图选择日期和价格，再保存到当前人工缠论结构。
          </p>
        )}
        {manualChanAnnotation && displayedAnalysis && displayedAnalysis.fractals.length > 0 && (
          <>
            <p className="annotation-mode-note">人工缠论分型可新增、删除或切换顶 / 底；修改后后端会按人工分型重新派生笔、线段和中枢。</p>
            <p className="annotation-mode-note">{manualChanDerivationDetail(displayedAnalysis, manualChanAnnotation)}</p>
            <div className="wave-candidate-list" aria-label="人工缠论分型">
              {displayedAnalysis.fractals.slice(0, 12).map((point) => (
                <div className="wave-candidate" key={`chan-fractal-${point.index}-${point.trade_date}`}>
                  <strong>{chanFractalKindLabel(point.kind)}</strong>
                  <span>{point.trade_date}</span>
                  <small>{point.price.toFixed(2)}</small>
                  <div className="wave-point-actions">
                    <button
                      type="button"
                      onClick={() => void handleToggleManualChanFractalKind(point)}
                      disabled={busy || annotationLocked(manualChanAnnotation)}
                      title="切换分型顶底"
                    >
                      切换顶底
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDeleteManualChanFractal(point)}
                      disabled={busy || annotationLocked(manualChanAnnotation) || displayedAnalysis.fractals.length <= 2}
                      title={displayedAnalysis.fractals.length <= 2 ? "至少保留 2 个分型" : "删除分型"}
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
        <div className="wave-edit-actions">
          <span className={manualWaveAnnotation ? "status-chip confirmed" : "status-chip"}>
            {manualWaveAnnotation ? "人工浪型优先" : "自动候选"}
          </span>
          <button
            className="tonal-button compact-button"
            onClick={() => void handleSaveManualWave()}
            disabled={busy || !selectedSymbol || !waveAnalysis || waveAnalysis.pivots.length === 0}
          >
            保存当前浪型
          </button>
          <button
            className="tonal-button compact-button"
            onClick={() => void handleRestoreAutomaticWave()}
            disabled={busy || !manualWaveAnnotation}
          >
            恢复自动候选
          </button>
          <button
            className={pendingManualWavePivotKind === "top" ? "filled-button compact-button" : "tonal-button compact-button"}
            onClick={() => beginAddManualWavePivot("top")}
            disabled={busy || !manualWaveAnnotation || annotationLocked(manualWaveAnnotation)}
          >
            添加高点
          </button>
          <button
            className={pendingManualWavePivotKind === "bottom" ? "filled-button compact-button" : "tonal-button compact-button"}
            onClick={() => beginAddManualWavePivot("bottom")}
            disabled={busy || !manualWaveAnnotation || annotationLocked(manualWaveAnnotation)}
          >
            添加低点
          </button>
        </div>
        {pendingManualWavePivotKind && (
          <p className="annotation-mode-note">
            正在添加{waveKindLabel(pendingManualWavePivotKind)}浪点：点击 K 线图选择日期和价格，再保存到当前人工浪型。
          </p>
        )}
        {displayedWaveAnalysis && displayedWaveAnalysis.pivots.length > 0 && (
          <div className="wave-candidate-list" aria-label="波浪候选编号">
            {displayedWaveAnalysis.pivots.map((point) => (
              <div className="wave-candidate" key={`${point.wave_no}-${point.trade_date}`}>
                <strong>W{point.wave_no}</strong>
                <span>{waveKindLabel(point.kind)}</span>
                <small>
                  {point.trade_date} · {point.price.toFixed(2)}
                </small>
                {manualWaveAnnotation && (
                  <div className="wave-point-actions">
                    <button
                      type="button"
                      onClick={() => void handleToggleManualWavePivotKind(point)}
                      disabled={busy || annotationLocked(manualWaveAnnotation) || point.kind === "start"}
                      title={point.kind === "start" ? "起点不参与顶底切换" : "切换顶底"}
                    >
                      切换顶底
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDeleteManualWavePivot(point)}
                      disabled={busy || annotationLocked(manualWaveAnnotation) || displayedWaveAnalysis.pivots.length <= 2}
                      title={displayedWaveAnalysis.pivots.length <= 2 ? "至少保留 2 个浪点" : "删除浪点"}
                    >
                      删除
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <p className="explain-text">当前版本先标记简单顶 / 底分型、缠论笔、线段候选、中枢候选和 ZigZag 波段候选。</p>
      </section>
    );
  }

  function renderRuleExplanationPanel() {
    return (
      <section className="surface">
        <div className="section-title">
          <BookOpenText size={18} />
          <span>规则说明</span>
        </div>
        <div className="rule-doc-list">
          <div className="rule-doc-item">
            <strong>缠论分型 / 笔 / 线段 / 中枢 MVP</strong>
            <span>算法：chan-fractal · 0.5.0</span>
            <p>
              当前先做 K 线包含关系预处理，再使用 3 根 K 线窗口识别顶 / 底分型，按顶底交替生成笔，以连续 3 笔生成线段候选，并用连续 3 笔价格区间重叠生成中枢候选。
            </p>
            <small>参数：strict_fractal=false，include_containment=true，window=3，min_bars_for_bi=5，min_bis_for_segment=3，min_bis_for_zhongshu=3。当前版本尚未执行标准线段破坏规则。</small>
          </div>
          <div className="rule-doc-item">
            <strong>波浪 ZigZag 候选</strong>
            <span>算法：wave-zigzag · 0.1.0</span>
            <p>
              当前按阈值确认反向摆动并生成 W 编号候选点。前端提供 3% 细浪、5% 标准、8% 大浪三档；阈值越小，候选波段越细。
            </p>
            <small>该结果只作为辅助候选，不代表唯一浪型结论；人工浪型可覆盖自动候选。</small>
          </div>
          <div className="rule-doc-item">
            <strong>人工优先规则</strong>
            <span>overlay_type=chan / wave</span>
            <p>
              当存在 active 不为 false 的人工缠论结构或人工浪型时，图表和报告分别使用 manual-chan、manual-wave 显示；恢复自动候选会把当前人工结构设为 inactive。
            </p>
            <small>普通标注和复盘笔记会记录算法版本；当前分析版本变化时，界面会提示“需复核”。</small>
          </div>
          <div className="rule-doc-item">
            <strong>规则配置边界</strong>
            <span>rule_profiles</span>
            <p>
              默认缠论规则会参与自动分型、笔、线段、中枢和缠论结构回测；默认波浪规则会参与未显式选择浪级时的 ZigZag 候选和波浪结构回测。
            </p>
            <small>工作台当前浪级和接口显式传入的 threshold_pct 优先于默认波浪规则；人工缠论 / 人工浪型仍优先于自动结果。</small>
          </div>
        </div>
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
        <div className="mode-switch" aria-label="标注模式">
          <button
            className={annotationMode === "browse" ? "selected" : ""}
            onClick={() => {
              setAnnotationMode("browse");
              setMovingAnnotationId(null);
              setPendingManualChanFractalKind(null);
              setPendingManualWavePivotKind(null);
            }}
          >
            浏览模式
          </button>
          <button className={annotationMode === "edit" ? "selected" : ""} onClick={() => setAnnotationMode("edit")}>
            编辑模式
          </button>
        </div>
        {annotationMode === "edit" ? (
          <>
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
          </>
        ) : (
          <p className="annotation-mode-note">浏览模式下只显示已保存标注；切换到编辑模式后可新增、锁定、确认或删除。</p>
        )}
        <div className="annotation-list">
          {workbenchAnnotations.map((item) => (
            <div className="annotation-item" key={item.id}>
              <div>
                <div className="annotation-heading">
                  <strong>{overlayTypeLabel(item.overlay_type)}</strong>
                  <span className={annotationConfirmed(item) ? "status-chip confirmed" : "status-chip"}>{annotationConfirmed(item) ? "已确认" : "待确认"}</span>
                  <span className={annotationLocked(item) ? "status-chip locked" : "status-chip"}>{annotationLocked(item) ? "已锁定" : "可编辑"}</span>
                  {annotationNeedsReview(item, displayedAnalysis, displayedWaveAnalysis) && <span className="status-chip review">需复核</span>}
                </div>
                <span>{annotationNote(item)}</span>
                <small>
                  {formatDateTime(item.updated_at)}
                  {annotationAnchorText(item) && ` · ${annotationAnchorText(item)}`}
                  {annotationLocked(item) && " · 删除前需要先解锁"}
                </small>
              </div>
              {annotationMode === "edit" && (
                <div className="annotation-actions">
                  <button
                    title={annotationLocked(item) ? "解锁标注" : "锁定标注"}
                    onClick={() => void handleToggleAnnotationFlag(item, "locked")}
                    disabled={busy}
                  >
                    {annotationLocked(item) ? <Unlock size={15} /> : <Lock size={15} />}
                  </button>
                  <button
                    title={annotationConfirmed(item) ? "取消确认" : "确认标注"}
                    onClick={() => void handleToggleAnnotationFlag(item, "confirmed")}
                    disabled={busy}
                  >
                    <CheckCircle2 size={15} />
                  </button>
                  <button
                    className={movingAnnotationId === item.id ? "selected" : ""}
                    title={
                      !annotationMovable(item)
                        ? "结构化标注不能移动锚点"
                          : annotationLocked(item)
                          ? "标注已锁定"
                          : movingAnnotationId === item.id
                            ? "正在移动，点击或拖拽图表定位"
                            : "选择后点击或拖拽图表移动锚点"
                    }
                    onClick={() => handleToggleAnnotationMove(item)}
                    disabled={busy || annotationLocked(item) || !annotationMovable(item)}
                  >
                    <Move size={15} />
                  </button>
                  <button
                    title={annotationLocked(item) ? "标注已锁定" : "删除标注"}
                    onClick={() => setAnnotationDeleteTarget(item)}
                    disabled={busy || annotationLocked(item)}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              )}
            </div>
          ))}
          {workbenchAnnotations.length === 0 && <p className="empty-note">当前标的和周期还没有人工标注。</p>}
        </div>
      </section>
    );
  }

  function renderReviewPanel() {
    const draftRuntime = workspaceDraftRuntimeStatus;
    const draftRuntimeSummary = formatWorkspaceDraftRuntimeSummary(draftRuntime);
    const draftRuntimeDetail = formatWorkspaceDraftRuntimeDetail(draftRuntime);
    const canForceSyncDraft = workspaceDraftRuntimeCanForceSync(draftRuntime);
    return (
      <section className="surface">
        <div className="section-title">
          <BookOpenText size={18} />
          <span>复盘笔记</span>
        </div>
        <div className={`draft-runtime-card ${workspaceDraftRuntimeTone(draftRuntime)}`}>
          <strong>{draftRuntimeSummary}</strong>
          <small>{draftRuntimeDetail}</small>
        </div>
        <label className="review-title-field">
          <span>标题</span>
          <input value={reviewTitle} onChange={(event) => setReviewTitle(event.target.value)} placeholder="复盘标题" />
        </label>
        <textarea
          className="annotation-input review-input"
          value={reviewDraft}
          onChange={(event) => setReviewDraft(event.target.value)}
          placeholder="记录结构判断、关键买卖点、后续观察条件和失效条件"
        />
        <label className="review-title-field">
          <span>标签</span>
          <input value={reviewTags} onChange={(event) => setReviewTags(event.target.value)} placeholder="例如：中枢, 三买, 风险" />
        </label>
        <button
          className="filled-button full-width"
          onClick={() => void handleSaveReviewNote()}
          disabled={busy || !selectedSymbol || !reviewDraft.trim()}
        >
          <Save size={17} />
          保存复盘笔记
        </button>
        <button
          className="tonal-button full-width report-export-button"
          onClick={() => triggerWorkspaceDraftSync()}
          disabled={!canForceSyncDraft}
          title={canForceSyncDraft ? "立即触发草稿落盘" : "当前没有待同步草稿"}
        >
          <RefreshCw size={17} />
          立即同步草稿
        </button>
        <button
          className="tonal-button full-width report-export-button"
          onClick={() => handleExportReviewReport()}
          disabled={!selectedSymbol}
        >
          <FileText size={17} />
          导出复盘报告
        </button>
        <button
          className="tonal-button full-width report-export-button"
          onClick={() => handleExportChartScreenshot()}
          disabled={!selectedSymbol || bars.length === 0}
        >
          <Download size={17} />
          导出 K 线截图
        </button>
        <div className="review-note-list">
          {reviewNotes.map((item) => (
            <div className="review-note-item" key={item.id}>
              <div className="review-note-header">
                <div className="annotation-heading">
                  <strong>{reviewNoteTitle(item)}</strong>
                  {annotationNeedsReview(item, displayedAnalysis, displayedWaveAnalysis) && <span className="status-chip review">需复核</span>}
                </div>
                <button
                  type="button"
                  title="删除复盘笔记"
                  onClick={() => setAnnotationDeleteTarget(item)}
                  disabled={busy}
                >
                  <Trash2 size={15} />
                </button>
              </div>
              <p>{reviewNoteContent(item)}</p>
              <div className="review-note-tags">
                {reviewNoteTags(item).map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
              <small>
                {formatDateTime(item.updated_at)}
                {reviewNoteRange(item) && ` · ${reviewNoteRange(item)}`}
              </small>
            </div>
          ))}
          {reviewNotes.length === 0 && <p className="empty-note">当前标的和周期还没有复盘笔记。</p>}
        </div>
      </section>
    );
  }

  function renderBacktestPanel() {
    const summary = backtest?.summary ?? null;
    const trades = backtest?.trades ?? [];
    const equityCurve = backtest?.equity_curve ?? [];
    const latestEquity = equityCurve.at(-1) ?? null;
    const maxDrawdownPoint = equityCurve.reduce<typeof latestEquity>(
      (current, point) => (!current || point.drawdown_pct > current.drawdown_pct ? point : current),
      null,
    );
    const signalEvidence = backtest ? formatBacktestSignalEvidence(backtest) : "运行后显示候选信号数量";
    const structureCounts = backtest ? formatBacktestStructureCounts(backtest) : "-";
    const executionParams = backtest ? formatBacktestExecutionParams(backtest.params) : backtestStrategyDetail(backtestStrategy);
    const openPosition = backtest && isRecord(backtest.params.open_position) ? backtest.params.open_position : null;
    const openPositionEntryPrice = openPosition ? numericBacktestParam(openPosition.entry_price) : null;
    const openPositionLatestClose = openPosition ? numericBacktestParam(openPosition.latest_close) : null;
    const openPositionHoldingBars = openPosition ? numericBacktestParam(openPosition.holding_bars) : null;
    const openPositionReason = openPosition && typeof openPosition.reason === "string" ? openPositionReasonLabel(openPosition.reason) : "原因未知";
    return (
      <section className="surface">
        <div className="section-title">
          <Activity size={18} />
          <span>轻量回测</span>
        </div>
        <div className="backtest-toolbar">
          <div>
            <strong>{backtest ? `${backtest.algorithm} · ${backtest.version}` : "结构信号回测"}</strong>
            <span>{backtestStatus}</span>
          </div>
          <div className="toolbar-actions">
            <button className="tonal-button compact-button" onClick={() => handleExportBacktestCsv()} disabled={!hasBacktestCsvRows(backtest)}>
              <Download size={15} />
              导出 CSV
            </button>
            <button className="tonal-button compact-button" onClick={() => void loadBacktest()} disabled={isBacktestLoading || !selectedSymbol}>
              <RefreshCw size={15} />
              {isBacktestLoading ? "运行中" : "刷新"}
            </button>
          </div>
        </div>
        <div className="metric-grid backtest-metrics">
          <div>
            <span>交易数</span>
            <strong>{summary?.total_trades ?? 0}</strong>
          </div>
          <div>
            <span>胜率</span>
            <strong>{summary ? `${formatPercent(summary.win_rate)}` : "-"}</strong>
          </div>
          <div>
            <span>总收益</span>
            <strong className={summary ? returnClassName(summary.total_return_pct) : undefined}>
              {summary ? formatSignedPercent(summary.total_return_pct) : "-"}
            </strong>
          </div>
          <div>
            <span>最大回撤</span>
            <strong>{summary ? formatSignedPercent(-summary.max_drawdown_pct) : "-"}</strong>
          </div>
          <div>
            <span>平均收益</span>
            <strong className={summary ? returnClassName(summary.average_return_pct) : undefined}>
              {summary ? formatSignedPercent(summary.average_return_pct) : "-"}
            </strong>
          </div>
          <div>
            <span>平均持仓</span>
            <strong>{summary ? `${summary.average_holding_bars.toFixed(1)} 根` : "-"}</strong>
          </div>
          <div>
            <span>持仓区间</span>
            <strong>{summary ? `${summary.min_holding_bars}-${summary.max_holding_bars} 根` : "-"}</strong>
          </div>
          <div>
            <span>中位持仓</span>
            <strong>{summary ? `${summary.median_holding_bars.toFixed(1)} 根` : "-"}</strong>
          </div>
          <div>
            <span>权益净值</span>
            <strong className={latestEquity ? returnClassName(latestEquity.equity_return_pct) : undefined}>
              {latestEquity ? latestEquity.equity.toFixed(4) : "-"}
            </strong>
          </div>
          <div>
            <span>曲线点数</span>
            <strong>{equityCurve.length.toLocaleString()}</strong>
          </div>
        </div>
        <div className="analysis-meta">
          <div>
            <span>策略条件</span>
            <strong>{backtest ? backtestStrategyLabel(backtest.strategy) : backtestStrategyLabel(backtestStrategy)}</strong>
            <small>{backtest ? backtestStrategyCondition(backtest) : backtestStrategyDetail(backtestStrategy)}</small>
          </div>
          <div>
            <span>触发信号</span>
            <strong>{signalEvidence}</strong>
            <small>{executionParams}</small>
          </div>
          <div>
            <span>结构用量</span>
            <strong>{structureCounts}</strong>
            <small>{backtest ? `${backtest.params.source_algorithm ?? "-"} · ${backtest.params.source_version ?? "-"}` : "随当前策略刷新"}</small>
          </div>
          <div>
            <span>结构来源</span>
            <strong>{backtest ? backtestStructureSourceLabel(backtest) : "-"}</strong>
            <small>
              {backtest?.manual_annotation_id
                ? `${backtestManualSourceLabel(backtest)} ${backtest.manual_annotation_id}`
                : backtestAutoSourceHint(backtestStrategy)}
            </small>
          </div>
          <div>
            <span>样本范围</span>
            <strong>{backtest ? `${backtest.bars_tested.toLocaleString()} 根 K 线` : "-"}</strong>
            <small>{backtest?.generated_at ? `生成 ${formatDateTime(backtest.generated_at)}` : "随当前标的、周期和时间范围刷新"}</small>
          </div>
          <div>
            <span>权益曲线</span>
            <strong>{latestEquity ? `${latestEquity.trade_date} · ${formatSignedPercent(latestEquity.equity_return_pct)}` : "-"}</strong>
            <small>
              {maxDrawdownPoint
                ? `最大回撤点 ${maxDrawdownPoint.trade_date} · ${formatSignedPercent(-maxDrawdownPoint.drawdown_pct)}`
                : "随完整交易闭合后生成"}
            </small>
          </div>
        </div>
        {openPosition && (
          <div className="open-position-card" aria-label="未闭合持仓">
            <div>
              <span>未闭合持仓</span>
              <strong>{openPositionReason}</strong>
            </div>
            <small>
              {stringParam(openPosition.entry_trade_date)} @ {formatPrice(openPositionEntryPrice ?? Number.NaN)}
              {" -> "}
              {stringParam(openPosition.latest_trade_date)} @ {formatPrice(openPositionLatestClose ?? Number.NaN)}
              {" · "}持仓 {openPositionHoldingBars ?? 0} 根 K 线
            </small>
            <small>该记录会随回测 CSV 以 row_type=open_position 导出。</small>
          </div>
        )}
        <div className="backtest-option-grid" aria-label="回测参数">
          <label>
            <span>策略</span>
            <select
              value={backtestStrategy}
              onChange={(event) => setBacktestStrategy(event.target.value as BacktestStrategy)}
            >
              {backtestStrategies.map((item) => (
                <option value={item.value} key={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>手续费 bps</span>
            <input
              type="number"
              min={0}
              max={1000}
              step={1}
              value={backtestOptions.feeBps}
              onChange={(event) => updateBacktestOption("feeBps", event.target.value)}
            />
          </label>
          <label>
            <span>滑点 bps</span>
            <input
              type="number"
              min={0}
              max={1000}
              step={1}
              value={backtestOptions.slippageBps}
              onChange={(event) => updateBacktestOption("slippageBps", event.target.value)}
            />
          </label>
          <label>
            <span>仓位 %</span>
            <input
              type="number"
              min={0}
              max={100}
              step={5}
              value={backtestOptions.positionPct}
              onChange={(event) => updateBacktestOption("positionPct", event.target.value)}
            />
          </label>
          <label>
            <span>涨跌停幅度 %</span>
            <input
              type="number"
              min={0.1}
              max={30}
              step={0.1}
              value={backtestOptions.limitPct}
              onChange={(event) => updateBacktestOption("limitPct", event.target.value)}
            />
          </label>
          <label className="switch-row compact-switch backtest-toggle-option">
            <span>涨跌停约束</span>
            <input
              type="checkbox"
              checked={backtestOptions.applyLimitConstraints}
              onChange={(event) => updateBacktestLimitConstraint(event.target.checked)}
            />
          </label>
        </div>
        <div className="backtest-trade-list" aria-label="回测交易列表">
          {trades.slice(0, 8).map((trade) => (
            <div className="backtest-trade" key={`${trade.index}-${trade.entry_trade_date}-${trade.exit_trade_date}`}>
              <div>
                <strong>#{trade.index}</strong>
                <span className={returnClassName(trade.return_pct)}>{formatSignedPercent(trade.return_pct)}</span>
              </div>
              <small>
                {trade.entry_trade_date} @ {formatPrice(trade.entry_price)} {"->"} {trade.exit_trade_date} @ {formatPrice(trade.exit_price)}
              </small>
              <small>
                {backtestSignalLabel(trade.entry_signal)} / {backtestSignalLabel(trade.exit_signal)} · 持仓 {trade.holding_bars} 根
              </small>
            </div>
          ))}
          {trades.length > 8 && <p className="empty-note">仅显示前 8 笔交易，完整列表可导出 CSV。</p>}
          {backtest && trades.length === 0 && isRecord(backtest.params.open_position) && (
            <p className="empty-note">当前窗口没有闭合交易，但存在未闭合持仓，可导出 CSV 复核。</p>
          )}
          {selectedSymbol && !isBacktestLoading && trades.length === 0 && !isRecord(backtest?.params.open_position) && (
            <p className="empty-note">当前窗口没有形成完整买卖交易。</p>
          )}
          {!selectedSymbol && <p className="empty-note">选择标的后自动运行结构信号回测。</p>}
        </div>
        {equityCurve.length > 0 && (
          <div className="backtest-trade-list" aria-label="回测权益曲线">
            {equityCurve.slice(-6).map((point) => (
              <div className="backtest-trade" key={`equity-${point.trade_index}-${point.trade_date}`}>
                <div>
                  <strong>#{point.trade_index}</strong>
                  <span className={returnClassName(point.equity_return_pct)}>{formatSignedPercent(point.equity_return_pct)}</span>
                </div>
                <small>
                  {point.trade_date} · 净值 {point.equity.toFixed(4)} · 回撤 {formatSignedPercent(-point.drawdown_pct)}
                </small>
              </div>
            ))}
          </div>
        )}
        <p className="explain-text">当前回测已支持手续费、滑点、仓位比例、人工缠论 / 人工浪型优先和可选涨跌停约束；暂不处理停牌或复杂仓位管理。</p>
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
        <div className="rule-editor">
          <div className="rule-editor-group">
            <div className="rule-editor-heading">
              <strong>缠论默认规则</strong>
              <span>{ruleProfileSourceLabel(defaultChanRuleProfile)}</span>
            </div>
            <label className="switch-row compact-switch">
              <span>包含处理</span>
              <input
                type="checkbox"
                checked={ruleDraft.chanIncludeContainment}
                onChange={(event) => setRuleDraft((current) => ({ ...current, chanIncludeContainment: event.target.checked }))}
              />
            </label>
            <div className="rule-input-grid">
              <label>
                <span>成笔间隔</span>
                <input
                  type="number"
                  min={1}
                  max={20}
                  step={1}
                  value={ruleDraft.chanMinBarsForBi}
                  onChange={(event) => updateRuleDraftNumber("chanMinBarsForBi", event.target.value)}
                />
              </label>
              <label>
                <span>线段笔数</span>
                <input
                  type="number"
                  min={1}
                  max={12}
                  step={1}
                  value={ruleDraft.chanMinBisForSegment}
                  onChange={(event) => updateRuleDraftNumber("chanMinBisForSegment", event.target.value)}
                />
              </label>
              <label>
                <span>线段步长</span>
                <input
                  type="number"
                  min={1}
                  max={12}
                  step={1}
                  value={ruleDraft.chanSegmentStepBis}
                  onChange={(event) => updateRuleDraftNumber("chanSegmentStepBis", event.target.value)}
                />
              </label>
              <label>
                <span>中枢笔数</span>
                <input
                  type="number"
                  min={1}
                  max={12}
                  step={1}
                  value={ruleDraft.chanMinBisForZhongshu}
                  onChange={(event) => updateRuleDraftNumber("chanMinBisForZhongshu", event.target.value)}
                />
              </label>
              <label>
                <span>中枢步长</span>
                <input
                  type="number"
                  min={1}
                  max={12}
                  step={1}
                  value={ruleDraft.chanZhongshuStepBis}
                  onChange={(event) => updateRuleDraftNumber("chanZhongshuStepBis", event.target.value)}
                />
              </label>
            </div>
            <div className="rule-change-summary">
              <strong>{ruleChangeSummaryTitle(chanRuleChanges)}</strong>
              {chanRuleChanges.map((item) => (
                <span className={item.changed ? "changed" : ""} key={item.label}>
                  {item.label}：{item.current} {"->"} {item.next}
                </span>
              ))}
            </div>
            <button className="filled-button full-width" onClick={() => void handleSaveDefaultChanRule()} disabled={busy}>
              <Save size={17} />
              保存为默认缠论规则
            </button>
          </div>
          <div className="rule-editor-group">
            <div className="rule-editor-heading">
              <strong>波浪默认规则</strong>
              <span>{ruleProfileSourceLabel(defaultWaveRuleProfile)}</span>
            </div>
            <div className="rule-input-grid">
              <label>
                <span>ZigZag 阈值 %</span>
                <input
                  type="number"
                  min={0.1}
                  max={50}
                  step={0.1}
                  value={ruleDraft.waveThresholdPct}
                  onChange={(event) => updateRuleDraftNumber("waveThresholdPct", event.target.value)}
                />
              </label>
              <label>
                <span>最小摆动 K 数</span>
                <input
                  type="number"
                  min={1}
                  max={20}
                  step={1}
                  value={ruleDraft.waveMinSwingBars}
                  onChange={(event) => updateRuleDraftNumber("waveMinSwingBars", event.target.value)}
                />
              </label>
            </div>
            <div className="rule-change-summary">
              <strong>{ruleChangeSummaryTitle(waveRuleChanges)}</strong>
              {waveRuleChanges.map((item) => (
                <span className={item.changed ? "changed" : ""} key={item.label}>
                  {item.label}：{item.current} {"->"} {item.next}
                </span>
              ))}
            </div>
            <button className="filled-button full-width" onClick={() => void handleSaveDefaultWaveRule()} disabled={busy}>
              <Save size={17} />
              保存为默认波浪规则
            </button>
          </div>
        </div>
        <div className="profile-list">
          {ruleProfiles.map((profile) => (
            <div className="profile-item" key={profile.id}>
              <div>
                <strong>{profile.name}</strong>
                <span>
                  {analysisTypeLabel(profile.analysis_type)} · {profile.version}
                </span>
                <small>{formatParams(profile.params)}</small>
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

        <div className="health-metric-grid">
          {dataSummaryItems.map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>

        <div className="health-section-title">数据源文件</div>
        <div className="health-list">
          {sourceHealthItems.map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
          <div>
            <span>最近文件变更</span>
            <strong>{source?.latest_modified ? formatDateTime(source.latest_modified) : "-"}</strong>
          </div>
        </div>

        <div className="health-section-title">市场覆盖</div>
        <div className="coverage-list">
          {(dataHealth?.markets ?? []).map((market) => (
            <div key={market.market} className="coverage-row">
              <span>{marketLabel(market.market)}</span>
              <strong>{market.last_date ?? "-"}</strong>
              <small>
                {market.symbols.toLocaleString()} 标的 · {market.latest_symbols.toLocaleString()} 到最新日
              </small>
            </div>
          ))}
          {!dataHealth?.markets.length && <p className="empty-note">库内还没有市场覆盖数据。</p>}
        </div>

        <div className="health-section-title">周期覆盖</div>
        <div className="timeframe-coverage">
          {(dataHealth?.timeframes ?? []).map((item) => (
            <span key={item.timeframe} className={item.available ? "coverage-chip ok" : "coverage-chip warn"}>
              {item.label}
              <small>{item.available ? item.derived_from ?? formatCount(item.bars) : "缺失"}</small>
            </span>
          ))}
          {minuteStatuses.map((item) => (
            <span key={`source-${item.timeframe}`} className={`coverage-chip ${item.state}`}>
              源目录 {item.timeframe}
              <small>{item.sourceFiles.toLocaleString()} 文件</small>
            </span>
          ))}
        </div>

        <div className="health-section-title">补数建议</div>
        <div className="recommendation-list">
          {displayRecommendations.map((item) => (
            <div key={`${item.severity}-${item.title}`} className={`recommendation ${item.severity}`}>
              <strong>{item.title}</strong>
              <span>{item.detail}</span>
              <small>{item.action}</small>
            </div>
          ))}
          {!displayRecommendations.length && <p className="empty-note">正在等待数据健康检查。</p>}
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

function ImportJobProgress({ job, compact = false }: { job: ImportJob; compact?: boolean }) {
  const statusLabel = importJobStatusLabel(job.status);
  const fileProgress =
    job.files_seen > 0
      ? `${job.files_imported.toLocaleString()} / ${job.files_seen.toLocaleString()} 日线文件`
      : "正在准备文件列表";
  const minuteFileProgress =
    job.minute_files_seen > 0
      ? `${job.minute_files_imported.toLocaleString()} / ${job.minute_files_seen.toLocaleString()} 分钟文件`
      : "分钟文件待扫描";
  return (
    <div className={compact ? "import-progress compact" : "import-progress"}>
      <div>
        <span className={`job-dot ${job.status}`} />
        <strong>{statusLabel}</strong>
      </div>
      <span>{job.message || fileProgress}</span>
      <small>
        {fileProgress} · {minuteFileProgress} · {job.bars_imported.toLocaleString()} 根日线 ·{" "}
        {job.minute_bars_imported.toLocaleString()} 根分钟线
      </small>
      {job.errors.length > 0 && <small>{job.errors[0]}</small>}
    </div>
  );
}

class ChartErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidUpdate(previousProps: { resetKey: string }) {
    if (previousProps.resetKey !== this.props.resetKey && this.state.hasError) {
      this.setState({ hasError: false });
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="chart-frame">
          <div className="empty-chart chart-error">
            <strong>图表渲染失败</strong>
            <span>请切换标的、周期或重置时间范围后重试。</span>
          </div>
        </div>
      );
    }
    return this.props.children;
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

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function downloadJsonFile(payload: unknown, filename: string): void {
  downloadTextFile(JSON.stringify(payload, null, 2), filename, "application/json");
}

function downloadTextFile(content: string, filename: string, type: string): void {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function downloadDataUrlFile(dataUrl: string, filename: string): void {
  const link = document.createElement("a");
  link.href = dataUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function buildReviewReportMarkdown(state: ReviewReportState): string {
  const latestBar = state.bars.at(-1) ?? null;
  const firstBar = state.bars[0] ?? null;
  const reportLines = [
    `# ${escapeMarkdown(state.selectedName)} ${escapeMarkdown(state.timeframeLabel)}复盘报告`,
    "",
    `- 标的：${escapeMarkdown(state.selectedName)}（${state.selectedCode || state.selectedSymbol.symbol.toUpperCase()}）`,
    `- 周期：${escapeMarkdown(state.timeframeLabel)}（${state.timeframe.toUpperCase()}）`,
    `- 导出时间：${formatDateTime(new Date().toISOString())}`,
    `- 图表状态：${escapeMarkdown(state.chartStatus)}`,
    `- 请求范围：${state.dateStart || "-"} 至 ${state.dateEnd || "-"}`,
    `- 已加载窗口：${state.loadedWindowStart ?? firstBar?.trade_date ?? "-"} 至 ${state.loadedWindowEnd ?? latestBar?.trade_date ?? "-"}`,
    `- K 线数量：${state.bars.length.toLocaleString()}`,
    latestBar ? `- 最新 K 线：${latestBar.trade_date}，收盘 ${formatPrice(latestBar.close)}，高低 ${formatPrice(latestBar.high)} / ${formatPrice(latestBar.low)}` : "- 最新 K 线：无",
    "",
    "## 导出清单",
    "",
    ...formatExportChecklist(state),
    "",
    "## 分析概览",
    "",
    `- 缠论算法：${state.analysis ? `${state.analysis.algorithm} · ${state.analysis.version}` : "-"}`,
    `- 缠论参数：${state.analysis ? formatParams(state.analysis.params) : "-"}`,
    `- 分型数量：${state.analysis?.fractals.length ?? 0}`,
    `- 笔数量：${state.analysis?.bis.length ?? 0}`,
    `- 线段数量：${state.analysis?.segments.length ?? 0}`,
    `- 中枢数量：${state.analysis?.zhongshu.length ?? 0}`,
    `- 波浪算法：${state.waveAnalysis ? `${state.waveAnalysis.algorithm} · ${state.waveAnalysis.version}` : "-"}`,
    `- 波浪参数：${state.waveAnalysis ? formatParams(state.waveAnalysis.params) : "-"}`,
    `- 波段候选：${state.waveAnalysis?.pivots.length ?? 0}`,
    `- 人工缠论：${state.manualChanAnnotation ? `启用（${state.manualChanAnnotation.id}）` : "未启用"}`,
    `- 人工浪型：${state.manualWaveAnnotation ? `启用（${state.manualWaveAnnotation.id}）` : "未启用"}`,
    `- 当前图层：${formatLayerState(state.layers)}`,
    "",
    "## 轻量回测",
    "",
    ...formatBacktestForReport(state.backtest),
    "",
    "## 数据状态",
    "",
    `- 库内最新 T 日：${state.dataHealth?.latest_trade_date ?? "-"}`,
    `- 日线标的：${formatCount(state.dataHealth?.daily_symbols)}`,
    `- 日线 K 线：${formatCount(state.dataHealth?.daily_bars)}`,
    `- 周期覆盖：${formatTimeframeCoverage(state.dataHealth)}`,
    "",
    "## 规则配置",
    "",
    ...formatRuleProfilesForReport(state.ruleProfiles),
    "",
    "## 人工标注",
    "",
    ...formatAnnotationsForReport(state.annotations.filter(annotationMovable)),
    "",
    "## 人工缠论结构",
    "",
    ...formatManualChanForReport(state.manualChanAnnotation, state.analysis),
    "",
    "## 人工浪型",
    "",
    ...formatManualWaveForReport(state.manualWaveAnnotation, state.waveAnalysis),
    "",
    "## 复盘笔记",
    "",
    ...formatReviewNotesForReport(state.reviewNotes),
    "",
    "## 后续观察",
    "",
    "- 观察条件：",
    "- 失效条件：",
    "- 下一次复盘：",
    "",
  ];
  return `${reportLines.join("\n")}\n`;
}

function formatRuleProfilesForReport(profiles: RuleProfile[]): string[] {
  if (profiles.length === 0) {
    return ["- 暂无规则配置"];
  }
  return profiles.map(
    (profile) =>
      `- ${escapeMarkdown(profile.name)}：${analysisTypeLabel(profile.analysis_type)} · ${profile.version} · ${profile.is_default ? "默认" : "非默认"} · ${formatParams(profile.params)}`,
  );
}

function formatExportChecklist(state: ReviewReportState): string[] {
  const items = [
    `- Markdown 复盘报告：当前文件，包含标的窗口、算法版本、规则配置、人工结构、复盘笔记和回测摘要。`,
    `- K 线 PNG 截图：可从复盘面板单独导出，建议与本报告同名保存，用于复核图层显示和人工锚点位置。`,
  ];
  if (hasBacktestCsvRows(state.backtest)) {
    items.push("- 回测交易 CSV：可从轻量回测面板单独导出，包含完整交易明细、结构证据、执行参数拆列和权益曲线。");
  } else {
    items.push("- 回测交易 CSV：当前没有闭合交易或未闭合持仓，CSV 导出入口会保持禁用。");
  }
  if (state.annotations.length > 20 || state.reviewNotes.length > 10) {
    items.push("- 用户数据备份：当标注或复盘笔记较多时，建议同时导出备份 JSON，完整迁移本地人工数据。");
  }
  return items;
}

function formatAnnotationsForReport(annotations: AnnotationRecord[]): string[] {
  if (annotations.length === 0) {
    return ["- 暂无人工标注"];
  }
  const visibleAnnotations = annotations.slice(0, 20);
  return [
    ...visibleAnnotations.map((item) => {
      const status = [annotationConfirmed(item) ? "已确认" : "待确认", annotationLocked(item) ? "已锁定" : "可编辑"].join(" / ");
      return `- ${escapeMarkdown(overlayTypeLabel(item.overlay_type))}：${escapeMarkdown(annotationNote(item))}（${status}，${annotationAnchorText(item) ?? "无锚点"}，${formatDateTime(item.updated_at)}）`;
    }),
    ...formatOmittedItemsNotice(annotations.length, visibleAnnotations.length, "条人工标注", "用户数据备份"),
  ];
}

function formatOmittedItemsNotice(total: number, visible: number, unit: string, source: string): string[] {
  const omitted = total - visible;
  if (omitted <= 0) {
    return [];
  }
  return [`- 另有 ${omitted} ${unit} 未在本报告展开，请查看${source}。`];
}

function formatManualChanForReport(annotation: AnnotationRecord | null, analysis: ChanAnalysis | null): string[] {
  if (!annotation) {
    return ["- 当前使用自动缠论结构"];
  }
  return [
    `- 人工缠论标注：${annotation.id}`,
    `- 保存时间：${formatDateTime(annotation.updated_at)}`,
    `- 算法版本：${analysis ? `${analysis.algorithm} · ${analysis.version}` : annotation.payload.chan_version ?? "-"}`,
    `- 分型 / 笔 / 线段 / 中枢：${analysis?.fractals.length ?? 0} / ${analysis?.bis.length ?? 0} / ${analysis?.segments.length ?? 0} / ${analysis?.zhongshu.length ?? 0}`,
    `- 派生说明：${manualChanDerivationDetail(analysis, annotation)}`,
  ];
}

function formatManualWaveForReport(annotation: AnnotationRecord | null, waveAnalysis: WaveAnalysis | null): string[] {
  if (!annotation) {
    return ["- 当前使用自动波浪候选"];
  }
  const pivots = waveAnalysis?.pivots ?? [];
  const visiblePivots = pivots.slice(0, 12);
  return [
    `- 人工浪型标注：${annotation.id}`,
    `- 保存时间：${formatDateTime(annotation.updated_at)}`,
    `- 阈值：${waveAnalysis?.threshold_pct ?? annotation.payload.threshold_pct ?? "-"}%`,
    `- 波段点：${pivots.length}`,
    ...visiblePivots.map((point) => `  - W${point.wave_no} ${waveKindLabel(point.kind)} ${point.trade_date} @ ${formatPrice(point.price)}`),
    ...formatOmittedItemsNotice(pivots.length, visiblePivots.length, "个浪点", "图表或用户数据备份").map((item) => `  ${item}`),
  ];
}

function formatBacktestForReport(backtest: BacktestResult | null): string[] {
  if (!backtest) {
    return ["- 暂无回测结果"];
  }
  const latestEquity = backtest.equity_curve.at(-1) ?? null;
  const visibleTrades = backtest.trades.slice(0, 8);
  const openPosition = formatOpenPositionParam(backtest.params.open_position);
  return [
    `- 算法：${backtest.algorithm} · ${backtest.version}`,
    `- 策略：${backtestStrategyLabel(backtest.strategy)}（${backtest.strategy}）`,
    `- 策略条件：${backtestStrategyCondition(backtest)}`,
    `- 触发信号：${formatBacktestSignalEvidence(backtest)}`,
    `- 结构用量：${formatBacktestStructureCounts(backtest)}`,
    `- 结构来源：${backtestStructureSourceLabel(backtest)}`,
    `- ${backtestManualSourceLabel(backtest)}：${backtest.manual_annotation_id ?? "未启用"}`,
    `- 执行参数：${formatBacktestExecutionParams(backtest.params)}`,
    `- 样本 K 线：${backtest.bars_tested.toLocaleString()}`,
    `- 交易数：${backtest.summary.total_trades}`,
    `- 胜率：${formatPercent(backtest.summary.win_rate)}`,
    `- 总收益：${formatSignedPercent(backtest.summary.total_return_pct)}`,
    `- 最大回撤：${formatSignedPercent(-backtest.summary.max_drawdown_pct)}`,
    `- 平均收益：${formatSignedPercent(backtest.summary.average_return_pct)}`,
    `- 平均持仓：${backtest.summary.average_holding_bars.toFixed(1)} 根 K 线`,
    `- 持仓区间：${backtest.summary.min_holding_bars} - ${backtest.summary.max_holding_bars} 根 K 线`,
    `- 中位持仓：${backtest.summary.median_holding_bars.toFixed(1)} 根 K 线`,
    `- 权益曲线：${latestEquity ? `${latestEquity.trade_date} 净值 ${latestEquity.equity.toFixed(4)}（${formatSignedPercent(latestEquity.equity_return_pct)}）` : "暂无闭合交易"}`,
    ...visibleTrades.map(
      (trade) =>
        `  - #${trade.index} ${trade.entry_trade_date} ${formatPrice(trade.entry_price)} -> ${trade.exit_trade_date} ${formatPrice(trade.exit_price)}，${formatSignedPercent(trade.return_pct)}，持仓 ${trade.holding_bars} 根`,
    ),
    ...(openPosition ? [`- 未闭合持仓：${openPosition}`, "  - 该记录会随回测 CSV 以 row_type=open_position 导出。"] : []),
    ...formatOmittedItemsNotice(backtest.trades.length, visibleTrades.length, "笔交易", "回测 CSV").map((item) => `  ${item}`),
  ];
}

function formatBacktestTradesCsv(backtest: BacktestResult): string {
  const header = [
    "row_type",
    "index",
    "strategy",
    "strategy_label",
    "strategy_condition",
    "entry_trade_date",
    "exit_trade_date",
    "entry_price",
    "exit_price",
    "return_pct",
    "holding_bars",
    "average_holding_bars",
    "min_holding_bars",
    "max_holding_bars",
    "median_holding_bars",
    "entry_signal",
    "entry_signal_label",
    "exit_signal",
    "exit_signal_label",
    "exit_reason",
    "exit_reason_label",
    "structure_source",
    "structure_source_label",
    "manual_annotation_id",
    "source_algorithm",
    "source_version",
    "structure_counts",
    "signal_count",
    "entry_signal_count",
    "exit_signal_count",
    "execution_params",
    "execution_price",
    "fee_bps",
    "slippage_bps",
    "position_pct",
    "apply_limit_constraints",
    "limit_pct",
    "limit_rule",
    "skipped_limit_up_entries",
    "skipped_limit_down_exits",
    "open_position_count",
    "equity",
    "equity_return_pct",
    "drawdown_pct",
  ];
  const executionColumns = backtestExecutionCsvColumns(backtest);
  const rows = backtest.trades.map((trade) => {
    const equityPoint = backtest.equity_curve.find((point) => point.trade_index === trade.index) ?? null;
    return [
      "closed_trade",
      trade.index,
      backtest.strategy,
      backtestStrategyLabel(backtest.strategy),
      backtestStrategyCondition(backtest),
      trade.entry_trade_date,
      trade.exit_trade_date,
      trade.entry_price,
      trade.exit_price,
      trade.return_pct,
      trade.holding_bars,
      backtest.summary.average_holding_bars,
      backtest.summary.min_holding_bars,
      backtest.summary.max_holding_bars,
      backtest.summary.median_holding_bars,
      trade.entry_signal,
      backtestSignalLabel(trade.entry_signal),
      trade.exit_signal,
      backtestSignalLabel(trade.exit_signal),
      trade.exit_reason,
      backtestSignalLabel(trade.exit_reason),
      backtest.structure_source,
      backtestStructureSourceLabel(backtest),
      backtest.manual_annotation_id ?? "",
      stringParam(backtest.params.source_algorithm),
      stringParam(backtest.params.source_version),
      formatBacktestStructureCounts(backtest),
      csvNumberParam(backtest.params.signal_count),
      csvNumberParam(backtest.params.entry_signal_count),
      csvNumberParam(backtest.params.exit_signal_count),
      formatBacktestExecutionParams(backtest.params),
      ...executionColumns,
      equityPoint?.equity ?? "",
      equityPoint?.equity_return_pct ?? "",
      equityPoint?.drawdown_pct ?? "",
    ];
  });
  const openPositionRow = formatOpenPositionCsvRow(backtest);
  return `${[header, ...rows, ...(openPositionRow ? [openPositionRow] : [])].map((row) => row.map(csvCell).join(",")).join("\n")}\n`;
}

function formatOpenPositionCsvRow(backtest: BacktestResult): Array<string | number> | null {
  const openPosition = backtest.params.open_position;
  if (!isRecord(openPosition)) {
    return null;
  }
  return [
    "open_position",
    "",
    backtest.strategy,
    backtestStrategyLabel(backtest.strategy),
    backtestStrategyCondition(backtest),
    stringParam(openPosition.entry_trade_date),
    stringParam(openPosition.latest_trade_date),
    csvNumberParam(openPosition.entry_price),
    csvNumberParam(openPosition.latest_close),
    "",
    csvNumberParam(openPosition.holding_bars),
    backtest.summary.average_holding_bars,
    backtest.summary.min_holding_bars,
    backtest.summary.max_holding_bars,
    backtest.summary.median_holding_bars,
    stringParam(openPosition.entry_signal),
    backtestSignalLabel(stringParam(openPosition.entry_signal)),
    "",
    "",
    stringParam(openPosition.reason),
    openPositionReasonLabel(stringParam(openPosition.reason)),
    backtest.structure_source,
    backtestStructureSourceLabel(backtest),
    backtest.manual_annotation_id ?? "",
    stringParam(backtest.params.source_algorithm),
    stringParam(backtest.params.source_version),
    formatBacktestStructureCounts(backtest),
    csvNumberParam(backtest.params.signal_count),
    csvNumberParam(backtest.params.entry_signal_count),
    csvNumberParam(backtest.params.exit_signal_count),
    formatBacktestExecutionParams(backtest.params),
    ...backtestExecutionCsvColumns(backtest),
    "",
    "",
    "",
  ];
}

function backtestExecutionCsvColumns(backtest: BacktestResult): Array<string | number> {
  return [
    stringParam(backtest.params.execution_price),
    csvNumberParam(backtest.params.fee_bps),
    csvNumberParam(backtest.params.slippage_bps),
    csvNumberParam(backtest.params.position_pct),
    backtest.params.apply_limit_constraints === true ? "true" : "false",
    csvNumberParam(backtest.params.limit_pct),
    stringParam(backtest.params.limit_rule),
    csvNumberParam(backtest.params.skipped_limit_up_entries),
    csvNumberParam(backtest.params.skipped_limit_down_exits),
    csvNumberParam(backtest.params.open_position_count),
  ];
}

function hasBacktestCsvRows(backtest: BacktestResult | null): backtest is BacktestResult {
  return Boolean(backtest && (backtest.trades.length > 0 || isRecord(backtest.params.open_position)));
}

function csvCell(value: string | number): string {
  const text = String(value);
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function formatReviewNotesForReport(notes: AnnotationRecord[]): string[] {
  if (notes.length === 0) {
    return ["- 暂无复盘笔记"];
  }
  return notes.slice(0, 10).flatMap((item) => {
    const tags = reviewNoteTags(item);
    return [
      `- ${escapeMarkdown(reviewNoteTitle(item))}（${formatDateTime(item.updated_at)}${tags.length > 0 ? `，${tags.join(" / ")}` : ""}）`,
      `  ${escapeMarkdown(reviewNoteContent(item)).replace(/\n/g, "\n  ") || "无内容"}`,
    ];
  });
}

function formatLayerState(layers: LayerState): string {
  const items = [
    ["成交量", layers.volume],
    ["缠论分型", layers.fractals],
    ["缠论笔", layers.bi],
    ["缠论线段", layers.segments],
    ["缠论中枢", layers.zhongshu],
    ["波浪候选", layers.wave],
    ["人工标注", layers.annotations],
    ["回测买卖点", layers.backtest],
  ];
  return items.map(([label, enabled]) => `${label}${enabled ? "开" : "关"}`).join("，");
}

function formatTimeframeCoverage(dataHealth: DataHealth | null): string {
  if (!dataHealth || dataHealth.timeframes.length === 0) {
    return "-";
  }
  return dataHealth.timeframes.map((item) => `${item.label}${item.available ? "可用" : "缺失"}`).join("，");
}

function formatPrice(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2) : "-";
}

function formatPercent(value: number): string {
  return Number.isFinite(value) ? `${value.toFixed(2)}%` : "-";
}

function formatSignedPercent(value: number): string {
  if (!Number.isFinite(value)) {
    return "-";
  }
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(2)}%`;
}

function returnClassName(value: number): string {
  if (value > 0) {
    return "positive-return";
  }
  if (value < 0) {
    return "negative-return";
  }
  return "flat-return";
}

function backtestSignalLabel(value: string): string {
  const labels: Record<string, string> = {
    bottom_fractal: "底分型买入",
    top_fractal: "顶分型卖出",
    down_bi_end: "向下笔结束买入",
    up_bi_end: "向上笔结束卖出",
    zhongshu_breakout: "中枢突破买入",
    zhongshu_breakdown: "中枢跌破卖出",
    wave_bottom: "波浪低点买入",
    wave_top: "波浪高点卖出",
    bottom: "底分型买入",
    top: "顶分型卖出",
    end: "区间结束",
  };
  return labels[value] ?? value;
}

function backtestStrategyLabel(value: string): string {
  return backtestStrategies.find((item) => item.value === value)?.label ?? value;
}

function backtestStrategyDetail(value: string): string {
  return backtestStrategies.find((item) => item.value === value)?.detail ?? value;
}

function backtestStructureSourceLabel(backtest: BacktestResult): string {
  if (backtest.structure_source === "manual") {
    return backtest.strategy === "wave_zigzag_reversal" ? "人工浪型覆盖" : "人工缠论覆盖";
  }
  if (backtest.structure_source === "auto") {
    return backtest.strategy === "wave_zigzag_reversal" ? "自动波浪候选" : "自动缠论结构";
  }
  return backtest.structure_source;
}

function backtestManualSourceLabel(backtest: BacktestResult): string {
  return backtest.strategy === "wave_zigzag_reversal" ? "人工浪型标注" : "人工缠论标注";
}

function backtestAutoSourceHint(strategy: BacktestStrategy | string): string {
  return strategy === "wave_zigzag_reversal" ? "没有 active 人工浪型时使用自动 ZigZag 候选" : "没有 active 人工缠论时使用自动结构";
}

function escapeMarkdown(value: string): string {
  return value.replace(/[\\`*_{}[\]()#+\-.!|>]/g, "\\$&");
}

function buildAnalysisSchemeWorkspace(state: AnalysisSchemeWorkspaceState): Record<string, unknown> {
  return {
    default_timeframe: state.defaultTimeframe,
    default_range_months: state.defaultRangeMonths,
    current_timeframe: state.timeframe,
    date_start: state.dateStart || null,
    date_end: state.dateEnd || null,
    date_range_touched: state.dateRangeTouched,
    wave_threshold_pct: state.waveThresholdPct,
    backtest_strategy: state.backtestStrategy,
    backtest_options: {
      fee_bps: state.backtestOptions.feeBps,
      slippage_bps: state.backtestOptions.slippageBps,
      position_pct: state.backtestOptions.positionPct,
      apply_limit_constraints: state.backtestOptions.applyLimitConstraints,
      limit_pct: state.backtestOptions.limitPct,
    },
    layers: state.layers,
    theme: state.theme,
    active_panel: state.activePanel,
    import_job_filter: state.importJobFilter,
    manual_line_style: {
      color: state.manualLineStyle.color,
      width: state.manualLineStyle.width,
    },
    manual_lines: state.manualLines.map((line) => ({
      id: line.id,
      symbol: line.symbol,
      timeframe: line.timeframe,
      start: {
        trade_date: line.start.tradeDate,
        price: line.start.price,
      },
      end: {
        trade_date: line.end.tradeDate,
        price: line.end.price,
      },
      created_at: line.createdAt,
    })),
    selected_symbol: state.selectedSymbol
      ? {
          symbol: state.selectedSymbol.symbol,
          market: state.selectedSymbol.market,
          code: state.selectedSymbol.code,
          name: state.selectedSymbol.name,
          kind: state.selectedSymbol.kind,
          first_date: state.selectedSymbol.first_date,
          last_date: state.selectedSymbol.last_date,
          bar_count: state.selectedSymbol.bar_count,
        }
      : null,
  };
}

function applyAnalysisSchemeWorkspace(
  workspace: Record<string, unknown>,
  setters: AnalysisSchemeWorkspaceSetters,
): ParsedAnalysisSchemeWorkspace {
  const parsed = parseAnalysisSchemeWorkspace(workspace);

  if (parsed.selectedSymbol !== undefined) {
    setters.setSelectedSymbol(parsed.selectedSymbol);
  }
  if (parsed.defaultTimeframe) {
    setters.setDefaultTimeframe(parsed.defaultTimeframe);
  }
  if (parsed.timeframe) {
    setters.setTimeframe(parsed.timeframe);
  }
  if (parsed.defaultRangeMonths) {
    setters.setDefaultRangeMonths(parsed.defaultRangeMonths);
  }
  if (parsed.waveThresholdPct) {
    setters.setWaveThresholdPct(parsed.waveThresholdPct);
  }
  if (parsed.backtestStrategy) {
    setters.setBacktestStrategy(parsed.backtestStrategy);
  }
  if (parsed.backtestOptions) {
    setters.setBacktestOptions(parsed.backtestOptions);
  }
  if (parsed.layers) {
    setters.setLayers(parsed.layers);
  }
  if (parsed.theme) {
    setters.setTheme(parsed.theme);
  }
  if (parsed.activePanel) {
    setters.setActivePanel(parsed.activePanel);
  }
  if (parsed.importJobFilter) {
    setters.setImportJobFilter(parsed.importJobFilter);
  }
  if (parsed.manualLines !== undefined) {
    setters.setManualLines(parsed.manualLines ?? []);
  }
  if (parsed.manualLineStyle !== undefined) {
    setters.setManualLineStyle(parsed.manualLineStyle ?? DEFAULT_MANUAL_LINE_STYLE);
  }
  if (parsed.dateStart !== null) {
    setters.setDateStart(parsed.dateStart);
  }
  if (parsed.dateEnd !== null) {
    setters.setDateEnd(parsed.dateEnd);
  }
  const hasImportedDateValue = (parsed.dateStart ?? "") !== "" || (parsed.dateEnd ?? "") !== "";
  if (parsed.dateRangeTouched !== null) {
    setters.setDateRangeTouched(parsed.dateRangeTouched);
  } else if (parsed.dateStart !== null || parsed.dateEnd !== null) {
    setters.setDateRangeTouched(hasImportedDateValue);
  }

  return parsed;
}

function parseAnalysisSchemeWorkspace(workspace: Record<string, unknown>): ParsedAnalysisSchemeWorkspace {
  const defaultTimeframe = parseTimeframe(workspace.default_timeframe ?? workspace.defaultTimeframe);
  const currentTimeframe = parseTimeframe(workspace.current_timeframe ?? workspace.currentTimeframe);
  const defaultRangeMonths = parseRangeMonths(workspace.default_range_months ?? workspace.defaultRangeMonths);
  const waveThreshold = parseWaveThreshold(workspace.wave_threshold_pct ?? workspace.waveThresholdPct);
  const backtestStrategy = parseBacktestStrategy(workspace.backtest_strategy ?? workspace.backtestStrategy);
  const backtestOptions = parseBacktestOptions(workspace.backtest_options ?? workspace.backtestOptions);
  const layers = parseLayerState(workspace.layers);
  const theme = parseThemeValue(workspace.theme);
  const activePanel = parseActivePanelValue(workspace.active_panel ?? workspace.activePanel);
  const importJobFilter = parseImportJobFilterValue(workspace.import_job_filter ?? workspace.importJobFilter);
  const manualLineStyle = parseManualLineStyle(workspace.manual_line_style ?? workspace.manualLineStyle);
  const manualLines = parseSchemeManualLines(workspace.manual_lines ?? workspace.manualLines);
  const normalizedDateRange = normalizeSchemeDateRange(
    parseSchemeDateInput(workspace.date_start ?? workspace.dateStart),
    parseSchemeDateInput(workspace.date_end ?? workspace.dateEnd),
  );
  const dateStart = normalizedDateRange.dateStart;
  const dateEnd = normalizedDateRange.dateEnd;
  const dateRangeTouched = parseOptionalBooleanLike(workspace.date_range_touched ?? workspace.dateRangeTouched);
  const selectedSymbol = parseSchemeSymbol(workspace.selected_symbol ?? workspace.selectedSymbol);

  return {
    defaultTimeframe,
    defaultRangeMonths,
    timeframe: currentTimeframe,
    dateStart,
    dateEnd,
    dateRangeTouched,
    waveThresholdPct: waveThreshold,
    backtestStrategy,
    backtestOptions,
    layers,
    theme,
    activePanel,
    importJobFilter,
    manualLineStyle,
    selectedSymbol,
    manualLines,
  };
}

function normalizeSchemeDateRange(
  dateStart: string | null,
  dateEnd: string | null,
): Pick<ParsedAnalysisSchemeWorkspace, "dateStart" | "dateEnd"> {
  if (dateStart && dateEnd && dateStart > dateEnd) {
    return { dateStart: dateEnd, dateEnd: dateStart };
  }
  return { dateStart, dateEnd };
}

function parseSchemeSymbol(value: unknown): SymbolRecord | null | undefined {
  if (value === null) {
    return null;
  }
  if (!isRecord(value) || typeof value.symbol !== "string") {
    return undefined;
  }
  const normalizedSymbol = value.symbol.trim().toLowerCase();
  if (!normalizedSymbol) {
    return undefined;
  }
  const fallbackMarket = normalizedSymbol.slice(0, 2);
  const fallbackCode = normalizedSymbol.slice(2);
  const firstDateCandidate = value.first_date ?? value.firstDate;
  const lastDateCandidate = value.last_date ?? value.lastDate;
  const barCountCandidate = value.bar_count ?? value.barCount;
  const barCountNumeric = Number(barCountCandidate);
  const firstDate = normalizeDateInputValue(firstDateCandidate);
  const lastDate = normalizeDateInputValue(lastDateCandidate);
  const barCount = Number.isFinite(barCountNumeric) && barCountNumeric >= 0 ? Math.floor(barCountNumeric) : 0;
  const market = typeof value.market === "string" ? value.market.trim() : "";
  const code = typeof value.code === "string" ? value.code.trim() : "";
  const name = typeof value.name === "string" ? value.name.trim() : "";
  const kind = typeof value.kind === "string" ? value.kind.trim() : "";
  return {
    symbol: normalizedSymbol,
    market: market || fallbackMarket,
    code: code || fallbackCode,
    name: name || normalizedSymbol.toUpperCase(),
    kind: kind || "stock",
    first_date: firstDate,
    last_date: lastDate,
    bar_count: barCount,
  };
}

function parseSchemeManualLines(value: unknown): StoredManualLine[] | null | undefined {
  if (value === null) {
    return null;
  }
  if (!Array.isArray(value)) {
    return undefined;
  }
  const lines: StoredManualLine[] = [];
  for (const item of value) {
    if (!isRecord(item)) {
      continue;
    }
    const id = typeof item.id === "string" ? item.id.trim() : "";
    const symbol = typeof item.symbol === "string" ? item.symbol.trim().toLowerCase() : "";
    const timeframe = parseTimeframe(item.timeframe);
    const start = parseSchemeLineAnchor(item.start);
    const end = parseSchemeLineAnchor(item.end);
    const createdAtRaw = item.created_at ?? item.createdAt;
    const createdAt = typeof createdAtRaw === "string" && createdAtRaw.trim().length > 0 ? createdAtRaw.trim() : new Date().toISOString();
    if (!id || !symbol || !timeframe || !start || !end) {
      continue;
    }
    lines.push({
      id,
      symbol,
      timeframe,
      start,
      end,
      createdAt,
    });
  }
  return lines;
}

function parseManualLineStyle(value: unknown): ManualLineStyle | null | undefined {
  if (value === null) {
    return null;
  }
  if (!isRecord(value)) {
    return undefined;
  }
  const colorRaw = value.color;
  const widthRaw = value.width;
  const fallbackColor = DEFAULT_MANUAL_LINE_STYLE.color;
  const color = normalizeManualLineColor(typeof colorRaw === "string" ? colorRaw : "", fallbackColor);
  const width = normalizeManualLineWidth(Number(widthRaw));
  return {
    color,
    width,
  };
}

function parseSchemeLineAnchor(value: unknown): ChartClickAnchor | null {
  if (!isRecord(value)) {
    return null;
  }
  const tradeDateRaw = value.trade_date ?? value.tradeDate;
  const tradeDate = typeof tradeDateRaw === "string" ? tradeDateRaw.trim() : "";
  const priceRaw = value.price;
  const price = typeof priceRaw === "number" ? priceRaw : Number(priceRaw);
  if (!tradeDate || !Number.isFinite(price)) {
    return null;
  }
  return {
    tradeDate,
    price,
  };
}

function parseSchemeDateInput(value: unknown): string | null {
  if (value === null) {
    return "";
  }
  return normalizeDateInputValue(value);
}

function normalizeDateInputValue(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim();
  return isDateInputValue(normalized) ? normalized : null;
}

function normalizeTimeframeValue(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  if (/^\d+m$/i.test(trimmed)) {
    return trimmed.toLowerCase();
  }
  if (/^[dwm]$/i.test(trimmed)) {
    return trimmed.toUpperCase();
  }
  return trimmed;
}

function parseTimeframe(value: unknown): string | null {
  const normalized = normalizeTimeframeValue(value);
  return normalized && timeframes.some((item) => item.value === normalized) ? normalized : null;
}

function parseRangeMonths(value: unknown): number | null {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) && [3, 6, 12, 24].includes(numericValue) ? numericValue : null;
}

function parseWaveThreshold(value: unknown): number | null {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) && waveLevels.some((level) => level.thresholdPct === numericValue) ? numericValue : null;
}

function normalizeBacktestStrategyValue(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim().toLowerCase();
  return normalized || null;
}

function parseBacktestStrategy(value: unknown): BacktestStrategy | null {
  const normalized = normalizeBacktestStrategyValue(value);
  return normalized && backtestStrategies.some((item) => item.value === normalized)
    ? (normalized as BacktestStrategy)
    : null;
}

function parseBacktestOptions(value: unknown): BacktestOptions | null {
  if (!isRecord(value)) {
    return null;
  }
  const feeBps = value.fee_bps ?? value.feeBps;
  const slippageBps = value.slippage_bps ?? value.slippageBps;
  const positionPct = value.position_pct ?? value.positionPct;
  const applyLimitConstraints = value.apply_limit_constraints ?? value.applyLimitConstraints;
  const limitPct = value.limit_pct ?? value.limitPct;
  return {
    feeBps: clampNumber(Number(feeBps), 0, 1000, 0),
    slippageBps: clampNumber(Number(slippageBps), 0, 1000, 0),
    positionPct: clampNumber(Number(positionPct), 0, 100, 100),
    applyLimitConstraints: parseBooleanLike(applyLimitConstraints),
    limitPct: clampNumber(Number(limitPct), 0.1, 30, 10),
  };
}

function parseBooleanLike(value: unknown): boolean {
  const parsed = parseOptionalBooleanLike(value);
  return parsed === true;
}

function parseOptionalBooleanLike(value: unknown): boolean | null {
  if (value === true || value === false) {
    return value;
  }
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "true" || normalized === "1") {
      return true;
    }
    if (normalized === "false" || normalized === "0") {
      return false;
    }
  }
  if (typeof value === "number") {
    if (value === 1) {
      return true;
    }
    if (value === 0) {
      return false;
    }
  }
  return null;
}

function parseLayerState(value: unknown): LayerState | null {
  if (!isRecord(value)) {
    return null;
  }
  const keys: Array<keyof LayerState> = ["volume", "fractals", "bi", "segments", "zhongshu", "wave", "annotations", "backtest"];
  const parsed = keys.map((key) => [key, parseOptionalBooleanLike(value[key])] as const);
  if (!parsed.some(([, parsedValue]) => parsedValue !== null)) {
    return null;
  }
  const parsedMap = Object.fromEntries(parsed) as Record<keyof LayerState, boolean | null>;
  return {
    volume: parsedMap.volume ?? true,
    fractals: parsedMap.fractals ?? true,
    bi: parsedMap.bi ?? true,
    segments: parsedMap.segments ?? true,
    zhongshu: parsedMap.zhongshu ?? true,
    wave: parsedMap.wave ?? true,
    annotations: parsedMap.annotations ?? true,
    backtest: parsedMap.backtest ?? true,
  };
}

function parseThemeValue(value: unknown): Theme | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim().toLowerCase();
  if (normalized === "dark" || normalized === "light") {
    return normalized as Theme;
  }
  return null;
}

function parseActivePanelValue(value: unknown): Panel | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim().toLowerCase();
  if (
    normalized === "workbench" ||
    normalized === "data" ||
    normalized === "layers" ||
    normalized === "review" ||
    normalized === "settings"
  ) {
    return normalized as Panel;
  }
  return null;
}

function parseImportJobFilterValue(value: unknown): ImportJobFilter | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim().toLowerCase();
  if (normalized === "all" || normalized === "pending" || normalized === "failed" || normalized === "succeeded" || normalized === "broken") {
    return normalized as ImportJobFilter;
  }
  return null;
}

function isDateInputValue(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }
  const date = new Date(`${value}T00:00:00`);
  return !Number.isNaN(date.getTime()) && toDateInputValue(date) === value;
}

function importJobStatusLabel(status: ImportJob["status"]): string {
  const labels: Record<ImportJob["status"], string> = {
    queued: "等待导入",
    running: "正在导入",
    succeeded: "导入完成",
    failed: "导入失败",
  };
  return labels[status];
}

function importJobStatusText(job: ImportJob): string {
  if (job.status === "queued") {
    return "导入任务已排队";
  }
  if (job.status === "running") {
    const filePart = job.files_seen > 0 ? `${job.files_imported}/${job.files_seen} 日线文件` : "正在扫描日线文件";
    const minuteFilePart =
      job.minute_files_seen > 0 ? `${job.minute_files_imported}/${job.minute_files_seen} 分钟文件` : "分钟文件待扫描";
    return `正在导入行情：${filePart}，${minuteFilePart}，${job.minute_bars_imported.toLocaleString()} 根分钟线`;
  }
  if (job.status === "succeeded") {
    const minuteFilePart =
      job.minute_files_seen > 0 ? `，${job.minute_files_imported}/${job.minute_files_seen} 分钟文件` : "";
    return `导入完成：${job.symbols_imported.toLocaleString()} 个标的${minuteFilePart}`;
  }
  return job.message || "导入任务失败";
}

function importResultFromJob(job: ImportJob): ImportResult {
  return {
    source_path: job.source_path ?? "",
    files_seen: job.files_seen,
    files_imported: job.files_imported,
    bars_imported: job.bars_imported,
    minute_files_seen: job.minute_files_seen,
    minute_files_imported: job.minute_files_imported,
    minute_bars_imported: job.minute_bars_imported,
    symbols_imported: job.symbols_imported,
    errors: job.errors,
  };
}

function importJobFiltersFromSelection(filter: ImportJobFilter): ImportJobQueryFilters {
  if (filter === "all") {
    return {};
  }
  if (filter === "broken") {
    return { sourcePathExists: false };
  }
  return { status: filter };
}

function importJobMatchesFilter(job: ImportJob, filter: ImportJobFilter): boolean {
  if (filter === "all") {
    return true;
  }
  if (filter === "broken") {
    return job.source_path_exists === false;
  }
  if (filter === "pending") {
    return job.status === "queued" || job.status === "running";
  }
  return job.status === filter;
}

function mergeImportJobsByFilter(current: ImportJob[], nextJob: ImportJob, filter: ImportJobFilter): ImportJob[] {
  const remaining = current.filter((item) => item.id !== nextJob.id);
  if (!importJobMatchesFilter(nextJob, filter)) {
    return remaining.slice(0, 20);
  }
  return [nextJob, ...remaining].slice(0, 20);
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN");
}

function workspaceDraftRuntimeTone(status: WorkspaceDraftRuntimeStatus): "runtime-ok" | "runtime-warn" | "runtime-info" {
  if (status.reason === "persisted" || (status.reason === "idle" && status.lastPersisted === true)) {
    return "runtime-ok";
  }
  if (status.reason === "persist_failed_retry_scheduled" || status.reason === "persist_failed_retry_waiting") {
    return "runtime-warn";
  }
  return "runtime-info";
}

function formatWorkspaceDraftRuntimeSummary(status: WorkspaceDraftRuntimeStatus): string {
  if (status.reason === "persisted") {
    return "草稿已保存到本地";
  }
  if (status.reason === "persist_failed_retry_scheduled" || status.reason === "persist_failed_retry_waiting") {
    if (status.lastErrorKind === "storage_unavailable") {
      return "草稿保存失败：当前环境存储不可用，正在自动重试";
    }
    if (status.lastErrorKind === "verify_mismatch") {
      return "草稿保存失败：写入校验不一致，正在自动重试";
    }
    if (status.lastErrorKind === "write_failed") {
      return "草稿保存失败：本地写入失败，正在自动重试";
    }
    return "草稿保存失败，正在自动重试";
  }
  if (status.reason === "draft_manual_sync") {
    return "正在手动同步草稿";
  }
  if (status.reason === "flush_attempt") {
    return "正在写入草稿";
  }
  if (status.reason === "draft_updated_debounce") {
    return "草稿待写入";
  }
  if (status.reason === "idle" && status.lastPersisted === true) {
    return "草稿已同步";
  }
  return "草稿状态初始化中";
}

function workspaceDraftRuntimeCanForceSync(status: WorkspaceDraftRuntimeStatus): boolean {
  return status.reason === "draft_updated_debounce" ||
    status.reason === "persist_failed_retry_scheduled" ||
    status.reason === "persist_failed_retry_waiting" ||
    status.reason === "draft_manual_sync";
}

function workspaceDraftRuntimeIsSyncing(status: WorkspaceDraftRuntimeStatus): boolean {
  return status.reason === "flush_attempt" || status.reason === "draft_manual_sync";
}

function formatWorkspaceDraftRuntimeDetail(status: WorkspaceDraftRuntimeStatus): string {
  const lastAttempt = formatWorkspaceDraftRuntimeTimestamp(status.lastAttemptAt);
  const lastPersisted = formatWorkspaceDraftRuntimeTimestamp(status.lastPersistedAt);
  const target = workspaceDraftPersistenceTargetLabel(status.lastPersistenceTarget);
  const error = workspaceDraftPersistErrorKindLabel(status.lastErrorKind);
  const actionHint = workspaceDraftPersistErrorActionHint(status.lastErrorKind);
  if (status.reason === "persist_failed_retry_scheduled" || status.reason === "persist_failed_retry_waiting") {
    return `待写入范围：${status.pendingScopeKey ?? "-"}；最近路径：${target}；失败类型：${error}；建议：${actionHint}；已重试 ${status.retryCount} 次；下次约 ${Math.round(status.nextRetryDelayMs / 1000)} 秒后重试；最近尝试：${lastAttempt}`;
  }
  if (status.reason === "persisted" || (status.reason === "idle" && status.lastPersisted === true)) {
    return `范围：${status.lastScopeKey ?? "-"}；落盘路径：${target}；最近保存：${lastPersisted}`;
  }
  if (status.reason === "draft_updated_debounce" || status.reason === "flush_attempt") {
    return `待写入范围：${status.pendingScopeKey ?? "-"}；最近路径：${target}；最近尝试：${lastAttempt}`;
  }
  return "草稿会在输入后自动落盘，并在失败时自动重试；可用 Ctrl/Cmd + S 立即同步，Shift + Ctrl/Cmd + S 强制同步。";
}

function workspaceDraftPersistenceTargetLabel(value: WorkspaceDraftRuntimeStatus["lastPersistenceTarget"]): string {
  if (value === "modern") {
    return "workspaceDrafts";
  }
  if (value === "legacy") {
    return "legacy_keys";
  }
  return "none";
}

function workspaceDraftPersistErrorKindLabel(value: WorkspaceDraftRuntimeStatus["lastErrorKind"]): string {
  if (!value || value === "none") {
    return "无";
  }
  if (value === "storage_unavailable") {
    return "存储不可用";
  }
  if (value === "write_failed") {
    return "写入失败";
  }
  return "写入校验不一致";
}

function workspaceDraftPersistErrorActionHint(value: WorkspaceDraftRuntimeStatus["lastErrorKind"]): string {
  if (!value || value === "none") {
    return "无";
  }
  if (value === "storage_unavailable") {
    return "检查浏览器存储权限或隐私模式限制";
  }
  if (value === "write_failed") {
    return "清理部分本地缓存后重试";
  }
  return "刷新页面后再次手动同步草稿";
}

function formatWorkspaceDraftRuntimeTimestamp(value: number | null): string {
  if (!value || !Number.isFinite(value)) {
    return "-";
  }
  return new Date(value).toLocaleTimeString("zh-CN", { hour12: false });
}

function formatRuleProfileTimestamp(value: Date): string {
  const date = toDateInputValue(value);
  const hours = String(value.getHours()).padStart(2, "0");
  const minutes = String(value.getMinutes()).padStart(2, "0");
  return `${date} ${hours}:${minutes}`;
}

function annotationNote(item: AnnotationRecord): string {
  return String(item.payload.note ?? "未命名标注");
}

function reviewNoteTitle(item: AnnotationRecord): string {
  return String(item.payload.title ?? item.payload.note ?? "复盘笔记");
}

function reviewNoteContent(item: AnnotationRecord): string {
  return String(item.payload.content ?? "");
}

function reviewNoteTags(item: AnnotationRecord): string[] {
  const tags = item.payload.tags;
  if (!Array.isArray(tags)) {
    return [];
  }
  return tags.filter((tag): tag is string => typeof tag === "string" && tag.trim().length > 0);
}

function reviewNoteRange(item: AnnotationRecord): string | null {
  const start = item.payload.loaded_window_start ?? item.payload.date_start;
  const end = item.payload.loaded_window_end ?? item.payload.date_end;
  if (typeof start !== "string" && typeof end !== "string") {
    return null;
  }
  return `${typeof start === "string" ? start : "-"} 至 ${typeof end === "string" ? end : "-"}`;
}

function parseTagInput(value: string): string[] {
  return value
    .split(/[,，、\s]+/)
    .map((tag) => tag.trim())
    .filter(Boolean)
    .slice(0, 8);
}

function annotationLocked(item: AnnotationRecord): boolean {
  return item.payload.locked === true;
}

function annotationConfirmed(item: AnnotationRecord): boolean {
  return item.payload.confirmed === true;
}

function annotationMovable(item: AnnotationRecord): boolean {
  return item.overlay_type !== "chan" && item.overlay_type !== "wave" && item.overlay_type !== "review_note";
}

function annotationAnchorText(item: AnnotationRecord): string | null {
  const tradeDate = item.payload.trade_date;
  const price = item.payload.price;
  if (typeof tradeDate !== "string" || !tradeDate) {
    return null;
  }
  if (typeof price === "number" && Number.isFinite(price)) {
    return `${tradeDate} @ ${price.toFixed(2)}`;
  }
  return tradeDate;
}

function roundPrice(value: number): number {
  return Math.round(value * 1000) / 1000;
}

function annotationNeedsReview(item: AnnotationRecord, analysis: ChanAnalysis | null, waveAnalysis: WaveAnalysis | null): boolean {
  const chanVersion = item.payload.chan_version;
  const waveVersion = item.payload.wave_version;
  return (
    (typeof chanVersion === "string" && analysis !== null && chanVersion !== analysis.version) ||
    (typeof waveVersion === "string" && waveAnalysis !== null && waveVersion !== waveAnalysis.version)
  );
}

function latestManualChanAnnotation(annotations: AnnotationRecord[]): AnnotationRecord | null {
  const manualChan = annotations
    .filter(
      (item) =>
        item.overlay_type === "chan" &&
        item.payload.active !== false &&
        (Array.isArray(item.payload.fractals) ||
          Array.isArray(item.payload.bis) ||
          Array.isArray(item.payload.segments) ||
          Array.isArray(item.payload.zhongshu)),
    )
    .sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime());
  return manualChan[0] ?? null;
}

function applyManualChanAnnotation(analysis: ChanAnalysis | null, annotation: AnnotationRecord | null): ChanAnalysis | null {
  if (!analysis || !annotation) {
    return analysis;
  }
  const fractals = parseChanFractals(annotation.payload.fractals);
  const bis = parseChanBis(annotation.payload.bis);
  const segments = parseChanSegments(annotation.payload.segments);
  const zhongshu = parseChanZhongshu(annotation.payload.zhongshu);
  if (fractals.length === 0 && bis.length === 0 && segments.length === 0 && zhongshu.length === 0) {
    return analysis;
  }
  if (analysis.algorithm === "manual-chan") {
    return {
      ...analysis,
      params: {
        ...analysis.params,
        source: "manual",
        annotation_id: annotation.id,
      },
    };
  }
  const chanVersion = typeof annotation.payload.chan_version === "string" ? annotation.payload.chan_version : analysis.version;
  const manualParams = isRecord(annotation.payload.params) ? annotation.payload.params : {};
  return {
    ...analysis,
    algorithm: "manual-chan",
    version: chanVersion,
    params: {
      ...analysis.params,
      ...manualParams,
      source: "manual",
      annotation_id: annotation.id,
    },
    generated_at: annotation.updated_at,
    fractals,
    bis,
    segments,
    zhongshu,
  };
}

function latestManualWaveAnnotation(annotations: AnnotationRecord[]): AnnotationRecord | null {
  const manualWaves = annotations
    .filter((item) => item.overlay_type === "wave" && item.payload.active !== false && Array.isArray(item.payload.pivots))
    .sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime());
  return manualWaves[0] ?? null;
}

function applyManualWaveAnnotation(waveAnalysis: WaveAnalysis | null, annotation: AnnotationRecord | null): WaveAnalysis | null {
  if (!waveAnalysis || !annotation) {
    return waveAnalysis;
  }
  const pivots = parseWavePivots(annotation.payload.pivots);
  if (pivots.length === 0) {
    return waveAnalysis;
  }
  const thresholdPct = typeof annotation.payload.threshold_pct === "number" ? annotation.payload.threshold_pct : waveAnalysis.threshold_pct;
  const waveVersion = typeof annotation.payload.wave_version === "string" ? annotation.payload.wave_version : waveAnalysis.version;
  return {
    ...waveAnalysis,
    algorithm: "manual-wave",
    version: waveVersion,
    threshold_pct: thresholdPct,
    params: {
      ...waveAnalysis.params,
      source: "manual",
      threshold_pct: thresholdPct,
      annotation_id: annotation.id,
    },
    generated_at: annotation.updated_at,
    pivots,
  };
}

function parseChanFractals(value: unknown): ChanFractalPoint[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item): ChanFractalPoint[] => {
    if (!isRecord(item)) {
      return [];
    }
    const index = item.index;
    const tradeDate = item.trade_date;
    const price = item.price;
    const kind = item.kind;
    if (typeof index !== "number" || typeof tradeDate !== "string" || typeof price !== "number" || !["top", "bottom"].includes(String(kind))) {
      return [];
    }
    return [{ index, trade_date: tradeDate, price, kind: kind as ChanFractalPoint["kind"] }];
  });
}

function renumberChanFractals(fractals: ChanFractalPoint[]): ChanFractalPoint[] {
  return [...fractals].sort((left, right) => left.index - right.index);
}

function parseChanBis(value: unknown): ChanBiPoint[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item): ChanBiPoint[] => {
    if (!isRecord(item)) {
      return [];
    }
    const index = item.index;
    const startIndex = item.start_index;
    const endIndex = item.end_index;
    const startTradeDate = item.start_trade_date;
    const endTradeDate = item.end_trade_date;
    const startPrice = item.start_price;
    const endPrice = item.end_price;
    const direction = item.direction;
    const startKind = item.start_kind;
    const endKind = item.end_kind;
    if (
      typeof index !== "number" ||
      typeof startIndex !== "number" ||
      typeof endIndex !== "number" ||
      typeof startTradeDate !== "string" ||
      typeof endTradeDate !== "string" ||
      typeof startPrice !== "number" ||
      typeof endPrice !== "number" ||
      !["up", "down"].includes(String(direction)) ||
      !["top", "bottom"].includes(String(startKind)) ||
      !["top", "bottom"].includes(String(endKind))
    ) {
      return [];
    }
    return [
      {
        index,
        start_index: startIndex,
        end_index: endIndex,
        start_trade_date: startTradeDate,
        end_trade_date: endTradeDate,
        start_price: startPrice,
        end_price: endPrice,
        direction: direction as ChanBiPoint["direction"],
        start_kind: startKind as ChanBiPoint["start_kind"],
        end_kind: endKind as ChanBiPoint["end_kind"],
      },
    ];
  });
}

function parseChanSegments(value: unknown): ChanSegmentPoint[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item): ChanSegmentPoint[] => {
    if (!isRecord(item)) {
      return [];
    }
    const index = item.index;
    const startBiIndex = item.start_bi_index;
    const endBiIndex = item.end_bi_index;
    const startIndex = item.start_index;
    const endIndex = item.end_index;
    const startTradeDate = item.start_trade_date;
    const endTradeDate = item.end_trade_date;
    const startPrice = item.start_price;
    const endPrice = item.end_price;
    const direction = item.direction;
    const biCount = item.bi_count;
    if (
      typeof index !== "number" ||
      typeof startBiIndex !== "number" ||
      typeof endBiIndex !== "number" ||
      typeof startIndex !== "number" ||
      typeof endIndex !== "number" ||
      typeof startTradeDate !== "string" ||
      typeof endTradeDate !== "string" ||
      typeof startPrice !== "number" ||
      typeof endPrice !== "number" ||
      !["up", "down"].includes(String(direction)) ||
      typeof biCount !== "number"
    ) {
      return [];
    }
    return [
      {
        index,
        start_bi_index: startBiIndex,
        end_bi_index: endBiIndex,
        start_index: startIndex,
        end_index: endIndex,
        start_trade_date: startTradeDate,
        end_trade_date: endTradeDate,
        start_price: startPrice,
        end_price: endPrice,
        direction: direction as ChanSegmentPoint["direction"],
        bi_count: biCount,
      },
    ];
  });
}

function parseChanZhongshu(value: unknown): ChanZhongshuPoint[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item): ChanZhongshuPoint[] => {
    if (!isRecord(item)) {
      return [];
    }
    const index = item.index;
    const startBiIndex = item.start_bi_index;
    const endBiIndex = item.end_bi_index;
    const startIndex = item.start_index;
    const endIndex = item.end_index;
    const startTradeDate = item.start_trade_date;
    const endTradeDate = item.end_trade_date;
    const low = item.low;
    const high = item.high;
    const mid = item.mid;
    const biCount = item.bi_count;
    if (
      typeof index !== "number" ||
      typeof startBiIndex !== "number" ||
      typeof endBiIndex !== "number" ||
      typeof startIndex !== "number" ||
      typeof endIndex !== "number" ||
      typeof startTradeDate !== "string" ||
      typeof endTradeDate !== "string" ||
      typeof low !== "number" ||
      typeof high !== "number" ||
      typeof mid !== "number" ||
      typeof biCount !== "number"
    ) {
      return [];
    }
    return [
      {
        index,
        start_bi_index: startBiIndex,
        end_bi_index: endBiIndex,
        start_index: startIndex,
        end_index: endIndex,
        start_trade_date: startTradeDate,
        end_trade_date: endTradeDate,
        low,
        high,
        mid,
        bi_count: biCount,
      },
    ];
  });
}

function parseWavePivots(value: unknown): WavePivot[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item): WavePivot[] => {
    if (!isRecord(item)) {
      return [];
    }
    const index = item.index;
    const tradeDate = item.trade_date;
    const price = item.price;
    const kind = item.kind;
    const waveNo = item.wave_no;
    if (
      typeof index !== "number" ||
      typeof tradeDate !== "string" ||
      typeof price !== "number" ||
      !["start", "top", "bottom"].includes(String(kind)) ||
      typeof waveNo !== "number"
    ) {
      return [];
    }
    return [
      {
        index,
        trade_date: tradeDate,
        price,
        kind: kind as WavePivot["kind"],
        wave_no: waveNo,
      },
    ];
  });
}

function renumberWavePivots(pivots: WavePivot[]): WavePivot[] {
  return [...pivots]
    .sort((left, right) => left.index - right.index)
    .map((point, index) => ({
      ...point,
      wave_no: index + 1,
    }));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function formatParams(params: Record<string, unknown>): string {
  const entries = Object.entries(params);
  if (entries.length === 0) {
    return "-";
  }
  return entries.map(([key, value]) => `${key}=${formatParamValue(value)}`).join("，");
}

function formatParamValue(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(formatParamValue).join(", ")}]`;
  }
  if (isRecord(value)) {
    return Object.entries(value)
      .map(([key, nestedValue]) => `${key}:${formatParamValue(nestedValue)}`)
      .join("|");
  }
  return String(value);
}

function backtestStrategyCondition(backtest: BacktestResult): string {
  const value = backtest.params.strategy_condition;
  return typeof value === "string" && value.length > 0 ? value : backtestStrategyDetail(backtest.strategy);
}

function formatBacktestSignalEvidence(backtest: BacktestResult): string {
  const signalCount = numericBacktestParam(backtest.params.signal_count);
  const entryCount = numericBacktestParam(backtest.params.entry_signal_count);
  const exitCount = numericBacktestParam(backtest.params.exit_signal_count);
  if (signalCount === null && entryCount === null && exitCount === null) {
    return "-";
  }
  return [
    signalCount !== null ? `候选 ${signalCount.toLocaleString()}` : null,
    entryCount !== null ? `买点 ${entryCount.toLocaleString()}` : null,
    exitCount !== null ? `卖点 ${exitCount.toLocaleString()}` : null,
  ]
    .filter(Boolean)
    .join("，");
}

function formatBacktestStructureCounts(backtest: BacktestResult): string {
  const counts = backtest.params.structure_counts;
  if (!isRecord(counts)) {
    return "-";
  }
  const labels: Record<string, string> = {
    fractals: "分型",
    bis: "笔",
    segments: "线段",
    zhongshu: "中枢",
    wave_pivots: "浪点",
    wave_tops: "高点",
    wave_bottoms: "低点",
  };
  const parts = Object.entries(labels)
    .map(([key, label]) => {
      const value = numericBacktestParam(counts[key]);
      return value === null ? null : `${label} ${value.toLocaleString()}`;
    })
    .filter(Boolean);
  return parts.length > 0 ? parts.join("，") : "-";
}

function formatBacktestExecutionParams(params: Record<string, unknown>): string {
  const skippedLimitUpEntries = numericBacktestParam(params.skipped_limit_up_entries);
  const skippedLimitDownExits = numericBacktestParam(params.skipped_limit_down_exits);
  const limitPct = formatPercentParam(params.limit_pct);
  const limitRule = typeof params.limit_rule === "string" ? params.limit_rule : null;
  const openPosition = formatOpenPositionParam(params.open_position);
  const entries = [
    ["执行", params.execution_price === "next_bar_close" ? "下一根收盘" : params.execution_price],
    ["手续费", formatBpsParam(params.fee_bps)],
    ["滑点", formatBpsParam(params.slippage_bps)],
    ["仓位", formatPositionParam(params.position_pct)],
    ["浪级阈值", formatPercentParam(params.wave_threshold_pct)],
    [
      "涨跌停",
      params.apply_limit_constraints === true
        ? `启用，幅度 ${limitPct ?? "10%"}，跳过买入 ${skippedLimitUpEntries ?? 0}，跳过卖出 ${skippedLimitDownExits ?? 0}`
        : `关闭，跳过买入 ${skippedLimitUpEntries ?? 0}，跳过卖出 ${skippedLimitDownExits ?? 0}`,
    ],
    ["规则", limitRule],
    ["未闭合", openPosition],
  ].filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1].length > 0);
  return entries.length > 0 ? entries.map(([label, value]) => `${label} ${value}`).join("，") : "-";
}

function formatOpenPositionParam(value: unknown): string | null {
  if (!isRecord(value)) {
    return null;
  }
  const entryDate = typeof value.entry_trade_date === "string" ? value.entry_trade_date : "-";
  const latestDate = typeof value.latest_trade_date === "string" ? value.latest_trade_date : "-";
  const entryPrice = numericBacktestParam(value.entry_price);
  const latestClose = numericBacktestParam(value.latest_close);
  const holdingBars = numericBacktestParam(value.holding_bars);
  const reason = typeof value.reason === "string" ? openPositionReasonLabel(value.reason) : "原因未知";
  return `${entryDate} ${formatPrice(entryPrice ?? Number.NaN)} -> ${latestDate} ${formatPrice(latestClose ?? Number.NaN)}，持仓 ${holdingBars ?? 0} 根，${reason}`;
}

function openPositionReasonLabel(value: string): string {
  const labels: Record<string, string> = {
    limit_down_exit_blocked: "跌停无法卖出",
    no_exit_bar: "没有可执行卖出 K 线",
  };
  return labels[value] ?? value;
}

function numericBacktestParam(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function csvNumberParam(value: unknown): string | number {
  const numeric = numericBacktestParam(value);
  return numeric === null ? "" : numeric;
}

function stringParam(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function formatBpsParam(value: unknown): string | null {
  const numeric = numericBacktestParam(value);
  return numeric === null ? null : `${numeric.toLocaleString()} bps`;
}

function formatPositionParam(value: unknown): string | null {
  const numeric = numericBacktestParam(value);
  return numeric === null ? null : `${numeric.toLocaleString()}%`;
}

function formatPercentParam(value: unknown): string | null {
  const numeric = numericBacktestParam(value);
  return numeric === null ? null : `${numeric.toLocaleString()}%`;
}

function overlayTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    note: "笔记",
    chan: "人工缠论",
    wave: "人工浪型",
    review_note: "复盘笔记",
  };
  return labels[value] ?? value;
}

function waveKindLabel(value: string): string {
  const labels: Record<string, string> = {
    start: "起点",
    top: "高点",
    bottom: "低点",
  };
  return labels[value] ?? value;
}

function chanFractalKindLabel(value: string): string {
  const labels: Record<string, string> = {
    top: "顶分型",
    bottom: "底分型",
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

function ruleProfileSourceLabel(profile: RuleProfile | null): string {
  if (!profile) {
    return "未加载默认规则";
  }
  const defaultLabel = profile.is_default ? "默认" : "候选";
  return `${profile.name} · ${profile.version} · ${defaultLabel} · ${formatDateTime(profile.updated_at)}`;
}

function chanRuleSourceTitle(
  analysis: ChanAnalysis | null,
  annotation: AnnotationRecord | null,
  profile: RuleProfile | null,
): string {
  if (!analysis) {
    return "-";
  }
  if (analysis.algorithm === "manual-chan" && annotation) {
    return "人工缠论覆盖";
  }
  return profile ? profile.name : "自动缠论默认规则";
}

function chanRuleSourceDetail(
  analysis: ChanAnalysis | null,
  annotation: AnnotationRecord | null,
  profile: RuleProfile | null,
): string {
  if (!analysis) {
    return "等待分析结果";
  }
  if (analysis.algorithm === "manual-chan" && annotation) {
    return `标注 ${annotation.id} · 更新 ${formatDateTime(annotation.updated_at)}`;
  }
  return profile ? `${profile.version} · ${formatParams(profile.params)}` : "使用后端内置默认参数";
}

function manualChanDerivationTitle(analysis: ChanAnalysis | null, annotation: AnnotationRecord | null): string {
  if (!annotation || analysis?.algorithm !== "manual-chan") {
    return "自动结构";
  }
  return analysis.params.derived_from_manual_fractals === true ? "人工分型派生" : "人工结构覆盖";
}

function manualChanDerivationDetail(analysis: ChanAnalysis | null, annotation: AnnotationRecord | null): string {
  if (!annotation || !analysis || analysis.algorithm !== "manual-chan") {
    return "未启用人工缠论覆盖";
  }
  const counts = `分型 ${analysis.fractals.length}，笔 ${analysis.bis.length}，线段 ${analysis.segments.length}，中枢 ${analysis.zhongshu.length}`;
  if (analysis.params.derived_from_manual_fractals === true) {
    return `后端已按人工分型重新派生结构：${counts}`;
  }
  return `使用人工保存结构：${counts}`;
}

function waveRuleSourceTitle(
  analysis: WaveAnalysis | null,
  annotation: AnnotationRecord | null,
  profile: RuleProfile | null,
): string {
  if (!analysis) {
    return "-";
  }
  if (analysis.algorithm === "manual-wave" && annotation) {
    return "人工浪型覆盖";
  }
  return profile ? profile.name : "自动 ZigZag 默认规则";
}

function waveRuleSourceDetail(
  analysis: WaveAnalysis | null,
  annotation: AnnotationRecord | null,
  profile: RuleProfile | null,
  selectedWaveLevelLabel: string,
): string {
  if (!analysis) {
    return "等待分析结果";
  }
  if (analysis.algorithm === "manual-wave" && annotation) {
    return `标注 ${annotation.id} · 阈值 ${analysis.threshold_pct}% · 更新 ${formatDateTime(annotation.updated_at)}`;
  }
  const profileText = profile ? `${profile.version} · ${formatParams(profile.params)}` : "后端内置默认参数";
  return `${selectedWaveLevelLabel} ${analysis.threshold_pct}% · 工作台浪级优先 · ${profileText}`;
}

function ruleChangeSummaryTitle(items: RuleChangeItem[]): string {
  const changedCount = items.filter((item) => item.changed).length;
  return changedCount > 0 ? `${changedCount} 项参数将变更` : "参数与当前默认一致";
}

function chanRuleChangeItems(profile: RuleProfile | null, draft: RuleDraft): RuleChangeItem[] {
  const current = ruleDraftFromProfiles(profile ? [profile] : []);
  return [
    ruleChangeItem("包含处理", current.chanIncludeContainment ? "开启" : "关闭", draft.chanIncludeContainment ? "开启" : "关闭"),
    ruleChangeItem("成笔间隔", current.chanMinBarsForBi, draft.chanMinBarsForBi),
    ruleChangeItem("线段笔数", current.chanMinBisForSegment, draft.chanMinBisForSegment),
    ruleChangeItem("线段步长", current.chanSegmentStepBis, draft.chanSegmentStepBis),
    ruleChangeItem("中枢笔数", current.chanMinBisForZhongshu, draft.chanMinBisForZhongshu),
    ruleChangeItem("中枢步长", current.chanZhongshuStepBis, draft.chanZhongshuStepBis),
  ];
}

function waveRuleChangeItems(profile: RuleProfile | null, draft: RuleDraft): RuleChangeItem[] {
  const current = ruleDraftFromProfiles(profile ? [profile] : []);
  return [
    ruleChangeItem("ZigZag 阈值", `${current.waveThresholdPct}%`, `${draft.waveThresholdPct}%`),
    ruleChangeItem("最小摆动 K 数", current.waveMinSwingBars, draft.waveMinSwingBars),
  ];
}

function ruleChangeItem(label: string, current: string | number, next: string | number): RuleChangeItem {
  const currentText = String(current);
  const nextText = String(next);
  return {
    label,
    current: currentText,
    next: nextText,
    changed: currentText !== nextText,
  };
}

function ruleDraftNumberRange(key: RuleDraftNumberKey): [number, number] {
  if (key === "waveThresholdPct") {
    return [0.1, 50];
  }
  if (key === "waveMinSwingBars" || key === "chanMinBarsForBi") {
    return [1, 20];
  }
  return [1, 12];
}

function defaultRuleProfile(profiles: RuleProfile[], analysisType: string): RuleProfile | null {
  return profiles.find((profile) => profile.analysis_type === analysisType && profile.is_default) ?? profiles.find((profile) => profile.analysis_type === analysisType) ?? null;
}

function ruleDraftFromProfiles(profiles: RuleProfile[]): RuleDraft {
  const chanProfile = defaultRuleProfile(profiles, "chan");
  const waveProfile = defaultRuleProfile(profiles, "wave");
  const chanParams = chanProfile?.params ?? {};
  const waveParams = waveProfile?.params ?? {};
  return {
    chanIncludeContainment: booleanParam(chanParams.include_containment, defaultRuleDraft.chanIncludeContainment),
    chanMinBarsForBi: numericParam(chanParams.min_bars_for_bi, defaultRuleDraft.chanMinBarsForBi, 1, 20),
    chanMinBisForSegment: numericParam(chanParams.min_bis_for_segment, defaultRuleDraft.chanMinBisForSegment, 1, 12),
    chanSegmentStepBis: numericParam(chanParams.segment_step_bis, defaultRuleDraft.chanSegmentStepBis, 1, 12),
    chanMinBisForZhongshu: numericParam(chanParams.min_bis_for_zhongshu, defaultRuleDraft.chanMinBisForZhongshu, 1, 12),
    chanZhongshuStepBis: numericParam(chanParams.zhongshu_step_bis, defaultRuleDraft.chanZhongshuStepBis, 1, 12),
    waveThresholdPct: numericParam(waveParams.zigzag_threshold_pct ?? waveParams.threshold_pct, defaultRuleDraft.waveThresholdPct, 0.1, 50),
    waveMinSwingBars: numericParam(waveParams.min_swing_bars, defaultRuleDraft.waveMinSwingBars, 1, 20),
  };
}

function numericParam(value: unknown, fallback: number, min: number, max: number): number {
  return clampNumber(Number(value), min, max, fallback);
}

function booleanParam(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function marketLabel(value: string): string {
  const labels: Record<string, string> = {
    sh: "沪市",
    sz: "深市",
    bj: "北交所",
  };
  return labels[value] ?? value.toUpperCase();
}

function formatCount(value: number | null | undefined): string {
  return value == null ? "-" : value.toLocaleString();
}

function formatDateRange(start: string | null | undefined, end: string | null | undefined): string {
  if (!start && !end) {
    return "-";
  }
  return `${start ?? "-"} 至 ${end ?? "-"}`;
}

function formatDataStoreSummary(dataHealth: DataHealth | null): string {
  if (!dataHealth || dataHealth.daily_symbols === 0) {
    return "库内暂无日线数据";
  }
  return `${dataHealth.daily_symbols.toLocaleString()} 标的，${formatCount(dataHealth.daily_bars)} 根日线，最新 ${dataHealth.latest_trade_date ?? "-"}`;
}

function buildMinuteStatuses(source: DataSourceCandidate | null, dataHealth: DataHealth | null): MinuteDataStatus[] {
  return [
    buildMinuteStatus("1 分钟", source?.minute1_files ?? 0, dataHealth?.timeframes.find((item) => item.timeframe === "1M")),
    buildMinuteStatus("5 分钟", source?.minute5_files ?? 0, dataHealth?.timeframes.find((item) => item.timeframe === "5M")),
  ];
}

function buildMinuteStatus(
  timeframe: string,
  sourceFiles: number,
  coverage: DataHealth["timeframes"][number] | undefined,
): MinuteDataStatus {
  const dbBars = coverage?.bars ?? 0;
  const dbAvailable = Boolean(coverage?.available);
  if (dbAvailable) {
    return {
      timeframe,
      sourceFiles,
      dbBars,
      dbAvailable,
      state: "ready",
      detail: `${timeframe}数据库已导入 ${dbBars.toLocaleString()} 根 K 线。`,
      action: "可以直接切换到对应分钟周期查看。",
    };
  }
  if (sourceFiles > 0) {
    return {
      timeframe,
      sourceFiles,
      dbBars,
      dbAvailable,
      state: "downloaded",
      detail: `源目录已发现 ${sourceFiles.toLocaleString()} 个 ${timeframe}文件，但数据库还没有对应 K 线。`,
      action: "点击“重新导入行情”，把刚下载的分钟文件导入数据库。",
    };
  }
  return {
    timeframe,
    sourceFiles,
    dbBars,
    dbAvailable,
    state: "missing",
    detail: `源目录没有发现 ${timeframe}文件。`,
    action: `先在通达信盘后数据下载里勾选 ${timeframe}线，再重新导入行情。`,
  };
}

function mergeDataRecommendations(recommendations: DataRecommendation[], minuteStatuses: MinuteDataStatus[]): DataRecommendation[] {
  const minuteTitles = new Set(["缺少 1 分钟数据", "缺少 5 分钟数据"]);
  const result = recommendations.filter((item) => !minuteTitles.has(item.title));
  for (const status of minuteStatuses) {
    if (status.state === "downloaded") {
      result.push({
        severity: "warn",
        title: `${status.timeframe}已下载未导入`,
        detail: status.detail,
        action: status.action,
      });
    } else if (status.state === "missing") {
      result.push({
        severity: status.timeframe === "5 分钟" ? "warn" : "info",
        title: `缺少 ${status.timeframe}数据`,
        detail: status.detail,
        action: status.action,
      });
    }
  }
  return result;
}

function statusForTimeframe(timeframe: string, statuses: MinuteDataStatus[]): MinuteDataStatus | null {
  if (timeframe === "1m") {
    return statuses.find((item) => item.timeframe === "1 分钟") ?? null;
  }
  if (["5m", "15m", "30m", "60m"].includes(timeframe)) {
    return statuses.find((item) => item.timeframe === "5 分钟") ?? null;
  }
  return null;
}

function minuteChartEmptyMessage(timeframe: string, status: MinuteDataStatus | null): string {
  if (!status) {
    return "当前级别暂无本地分钟线数据。";
  }
  if (status.state === "downloaded") {
    return `${status.timeframe} 源目录已发现 ${status.sourceFiles.toLocaleString()} 个文件，但数据库还没有对应 K 线。`;
  }
  if (status.state === "missing" && ["15m", "30m", "60m"].includes(timeframe)) {
    return `${timeframeLabel(timeframe)} 周期需要 5 分钟数据聚合生成；当前源目录没有发现 5 分钟文件。`;
  }
  if (status.state === "missing") {
    return status.detail;
  }
  return `当前时间范围暂无 ${status.timeframe}K 线；可扩大时间范围或向左加载历史。`;
}

function minuteChartAction(timeframe: string, status: MinuteDataStatus) {
  if (status.state === "downloaded") {
    return {
      title: `${status.timeframe}已下载，尚未入库`,
      detail: "点击导入后，图表才能读取这些分钟 K 线。",
      label: "立即导入",
      primary: true,
    };
  }
  if (status.state === "missing" && ["15m", "30m", "60m"].includes(timeframe)) {
    return {
      title: "缺少 5 分钟源文件",
      detail: "15 / 30 / 60 分钟会从 5 分钟线聚合；请先在通达信下载 5 分钟线。",
      label: "查看数据健康",
      primary: false,
    };
  }
  if (status.state === "missing") {
    return {
      title: `${status.timeframe}源文件缺失`,
      detail: "先在通达信盘后数据下载里补齐该周期，再回到这里重新导入。",
      label: "查看数据健康",
      primary: false,
    };
  }
  return {
    title: `${status.timeframe}库内有数据`,
    detail: "当前日期范围没有命中分钟 K 线，可调整时间范围。",
    label: "查看数据健康",
    primary: false,
  };
}

function timeframeLabel(timeframe: string): string {
  return timeframes.find((item) => item.value === timeframe)?.label ?? timeframe.toUpperCase();
}

function chartEmptyStatus(timeframe: string, source: DataSourceCandidate | null, dataHealth: DataHealth | null): string {
  const status = statusForTimeframe(timeframe, buildMinuteStatuses(source, dataHealth));
  if (!status) {
    return "当前级别暂无本地分钟线数据";
  }
  if (status.state === "downloaded") {
    return `${status.timeframe}源目录已有文件，尚未导入数据库`;
  }
  if (status.state === "missing") {
    return `${status.timeframe}源目录未发现文件`;
  }
  return `当前范围暂无 ${status.timeframe}K 线`;
}

function mergeBars(...chunks: BarRecord[][]): BarRecord[] {
  const byTime = new Map<string, BarRecord>();
  for (const chunk of chunks) {
    for (const bar of chunk) {
      byTime.set(bar.trade_date, bar);
    }
  }
  return Array.from(byTime.values()).sort((left, right) => compareTime(left.trade_date, right.trade_date));
}

function compareTime(left: string, right: string): number {
  return left.localeCompare(right);
}

function dateOnly(value: string): string {
  return value.slice(0, 10);
}

function hasOlderHistory(oldestLoaded: string | undefined, firstAvailable: string | null | undefined): boolean {
  if (!oldestLoaded || !firstAvailable) {
    return false;
  }
  return dateOnly(oldestLoaded) > firstAvailable;
}

function isDateRangeOutsideSymbol(start: string, end: string, symbol: SymbolRecord): boolean {
  if (!start || !end || !symbol.first_date || !symbol.last_date) {
    return false;
  }
  return end < symbol.first_date || start > symbol.last_date;
}

function readStorageByKeys(...keys: string[]): string | null {
  for (const key of keys) {
    const value = safeLocalStorageGetItem(key);
    if (value !== null) {
      return value;
    }
  }
  return null;
}

function readJsonStorageByKeys(...keys: string[]): unknown | null {
  for (const key of keys) {
    const raw = safeLocalStorageGetItem(key);
    if (raw === null) {
      continue;
    }
    try {
      return JSON.parse(raw);
    } catch {
      continue;
    }
  }
  return null;
}

function readDefaultRangeMonths(): number {
  const stored = Number(readStorageByKeys("defaultRangeMonths", "default_range_months"));
  return [3, 6, 12, 24].includes(stored) ? stored : 6;
}

function readDefaultTimeframe(): string {
  const normalized = normalizeTimeframeValue(readStorageByKeys("defaultTimeframe", "default_timeframe"));
  return normalized && timeframes.some((item) => item.value === normalized) ? normalized : "D";
}

function readCurrentTimeframe(fallback: string): string {
  const normalized = normalizeTimeframeValue(readStorageByKeys("currentTimeframe", "current_timeframe"));
  return normalized && timeframes.some((item) => item.value === normalized) ? normalized : fallback;
}

function readCurrentDateEnd(selectedSymbol: SymbolRecord | null, dateRangeTouched: boolean): string {
  const today = toDateInputValue(new Date());
  if (selectedSymbol && !dateRangeTouched) {
    return normalizeDateInputValue(selectedSymbol.last_date) ?? today;
  }
  const stored = normalizeDateInputValue(readStorageByKeys("dateEnd", "date_end"));
  return stored ?? today;
}

function readCurrentDateStart(
  timeframe: string,
  defaultRangeMonths: number,
  dateEnd: string,
  selectedSymbol: SymbolRecord | null,
  dateRangeTouched: boolean,
): string {
  if (selectedSymbol && !dateRangeTouched) {
    const defaultEnd = normalizeDateInputValue(selectedSymbol.last_date) ?? dateEnd;
    return initialDateStart(timeframe, defaultRangeMonths, defaultEnd);
  }
  const stored = normalizeDateInputValue(readStorageByKeys("dateStart", "date_start"));
  if (stored && stored <= dateEnd) {
    return stored;
  }
  return initialDateStart(timeframe, defaultRangeMonths, dateEnd);
}

function readDateRangeTouched(): boolean {
  const camelCaseValue = safeLocalStorageGetItem("dateRangeTouched");
  const snakeCaseValue = safeLocalStorageGetItem("date_range_touched");
  const parsedCamelCase = parseOptionalBooleanLike(camelCaseValue);
  if (parsedCamelCase !== null) {
    return parsedCamelCase;
  }
  return parseBooleanLike(snakeCaseValue);
}

function readSelectedSymbolFromStorage(): SymbolRecord | null {
  const raw = readJsonStorageByKeys("selectedSymbol", "selected_symbol");
  if (raw === null) {
    return null;
  }
  const parsed = parseSchemeSymbol(raw);
  return parsed === undefined ? null : parsed;
}

function readWaveThresholdPct(): number {
  const stored = Number(readStorageByKeys("waveThresholdPct", "wave_threshold_pct"));
  return waveLevels.some((level) => level.thresholdPct === stored) ? stored : 5;
}

function readBacktestStrategy(): BacktestStrategy {
  const normalized = normalizeBacktestStrategyValue(readStorageByKeys("backtestStrategy", "backtest_strategy"));
  return normalized && backtestStrategies.some((item) => item.value === normalized)
    ? (normalized as BacktestStrategy)
    : "chan_fractal_reversal";
}

function readBacktestOptions(): BacktestOptions {
  const fallback = { feeBps: 0, slippageBps: 0, positionPct: 100, applyLimitConstraints: false, limitPct: 10 };
  const raw = readJsonStorageByKeys("backtestOptions", "backtest_options");
  const stored = isRecord(raw) ? (raw as Record<string, unknown>) : {};
  const feeBps = stored.fee_bps ?? stored.feeBps;
  const slippageBps = stored.slippage_bps ?? stored.slippageBps;
  const positionPct = stored.position_pct ?? stored.positionPct;
  const applyLimitConstraints = stored.apply_limit_constraints ?? stored.applyLimitConstraints;
  const limitPct = stored.limit_pct ?? stored.limitPct;
  return {
    feeBps: clampNumber(Number(feeBps), 0, 1000, fallback.feeBps),
    slippageBps: clampNumber(Number(slippageBps), 0, 1000, fallback.slippageBps),
    positionPct: clampNumber(Number(positionPct), 0, 100, fallback.positionPct),
    applyLimitConstraints: parseBooleanLike(applyLimitConstraints),
    limitPct: clampNumber(Number(limitPct), 0.1, 30, fallback.limitPct),
  };
}

function readActivePanel(): Panel {
  const storedCamelCase = safeLocalStorageGetItem("activePanel")?.trim().toLowerCase();
  const storedSnakeCase = safeLocalStorageGetItem("active_panel")?.trim().toLowerCase();
  const stored = storedCamelCase || storedSnakeCase;
  if (stored === "data" || stored === "layers" || stored === "review" || stored === "settings") {
    return stored;
  }
  return "workbench";
}

function readImportJobFilter(): ImportJobFilter {
  const storedCamelCase = safeLocalStorageGetItem("importJobFilter")?.trim().toLowerCase();
  const storedSnakeCase = safeLocalStorageGetItem("import_job_filter")?.trim().toLowerCase();
  const stored = storedCamelCase || storedSnakeCase;
  if (stored === "pending" || stored === "failed" || stored === "succeeded" || stored === "broken") {
    return stored;
  }
  return "all";
}

function readLayers(): LayerState {
  const fallback: LayerState = {
    volume: true,
    fractals: true,
    bi: true,
    segments: true,
    zhongshu: true,
    wave: true,
    annotations: true,
    backtest: true,
  };
  const raw = readJsonStorageByKeys("layers", "layer_state");
  const parsed = parseLayerState(raw);
  return parsed ?? fallback;
}

function readTheme(): Theme {
  const stored = readStorageByKeys("theme", "theme_mode")?.trim().toLowerCase();
  return stored === "dark" ? "dark" : "light";
}

function readSymbolCatalog(): Record<string, SymbolRecord> {
  const raw = readJsonStorageByKeys("symbolCatalog");
  if (!isRecord(raw)) {
    return {};
  }
  const result: Record<string, SymbolRecord> = {};
  for (const [key, value] of Object.entries(raw)) {
    const parsed = parseSchemeSymbol(value);
    if (parsed && typeof parsed.symbol === "string" && parsed.symbol.length > 0) {
      result[key] = parsed;
    }
  }
  return result;
}

function readFavoriteSymbols(): string[] {
  const raw = readJsonStorageByKeys("favoriteSymbols");
  if (!Array.isArray(raw)) {
    return [];
  }
  const dedup = new Set<string>();
  for (const item of raw) {
    if (typeof item !== "string") {
      continue;
    }
    const value = item.trim().toLowerCase();
    if (value) {
      dedup.add(value);
    }
  }
  return Array.from(dedup);
}

function readSymbolGroups(): SymbolGroup[] {
  const raw = readJsonStorageByKeys("symbolGroups");
  if (!Array.isArray(raw)) {
    return [];
  }
  const groups: SymbolGroup[] = [];
  for (const item of raw) {
    if (!isRecord(item)) {
      continue;
    }
    const id = typeof item.id === "string" ? item.id.trim() : "";
    const name = typeof item.name === "string" ? item.name.trim() : "";
    const symbolsRaw = Array.isArray(item.symbols) ? item.symbols : [];
    if (!id || !name) {
      continue;
    }
    const symbols = Array.from(
      new Set(
        symbolsRaw
          .filter((symbol): symbol is string => typeof symbol === "string")
          .map((symbol) => symbol.trim().toLowerCase())
          .filter((symbol) => symbol.length > 0),
      ),
    );
    groups.push({ id, name, symbols });
  }
  return groups;
}

function readActiveSymbolGroupId(): string {
  const value = safeLocalStorageGetItem("activeSymbolGroupId")?.trim();
  if (!value) {
    return "__all";
  }
  return value;
}

function readStoredManualLines(): StoredManualLine[] {
  const raw = readJsonStorageByKeys("manualLines");
  if (!Array.isArray(raw)) {
    return [];
  }
  const lines: StoredManualLine[] = [];
  for (const item of raw) {
    if (!isRecord(item)) {
      continue;
    }
    const id = typeof item.id === "string" ? item.id.trim() : "";
    const symbol = typeof item.symbol === "string" ? item.symbol.trim().toLowerCase() : "";
    const timeframe = typeof item.timeframe === "string" ? item.timeframe.trim() : "";
    const createdAt = typeof item.createdAt === "string" && item.createdAt.length > 0 ? item.createdAt : new Date().toISOString();
    const start = parseLineAnchor(item.start);
    const end = parseLineAnchor(item.end);
    if (!id || !symbol || !timeframe || !start || !end) {
      continue;
    }
    lines.push({ id, symbol, timeframe, start, end, createdAt });
  }
  return lines;
}

function readManualLineStyle(): ManualLineStyle {
  const raw = readJsonStorageByKeys("manualLineStyle", "manual_line_style");
  const parsed = parseManualLineStyle(raw);
  if (!parsed) {
    return DEFAULT_MANUAL_LINE_STYLE;
  }
  return parsed;
}

function normalizeManualLineColor(value: string, fallback: string): string {
  const normalized = value.trim();
  return /^#[0-9a-fA-F]{6}$/.test(normalized) ? normalized.toLowerCase() : fallback;
}

function normalizeManualLineWidth(value: number): number {
  if (!Number.isFinite(value)) {
    return DEFAULT_MANUAL_LINE_STYLE.width;
  }
  return Math.max(1, Math.min(4, Math.round(value)));
}

function parseLineAnchor(value: unknown): ChartClickAnchor | null {
  if (!isRecord(value)) {
    return null;
  }
  const tradeDate = typeof value.tradeDate === "string" ? value.tradeDate.trim() : "";
  const price = typeof value.price === "number" ? value.price : Number.NaN;
  if (!tradeDate || !Number.isFinite(price)) {
    return null;
  }
  return { tradeDate, price };
}

function readLegacyAnnotationDraft(): string {
  return readStorageByKeys("annotationDraft", "annotation_draft") ?? "";
}

function readLegacyReviewTitle(): string {
  const title = readStorageByKeys("reviewTitle", "review_title");
  return title && title.trim() ? title : "复盘笔记";
}

function readLegacyReviewDraft(): string {
  return readStorageByKeys("reviewDraft", "review_draft") ?? "";
}

function readLegacyReviewTags(): string {
  return readStorageByKeys("reviewTags", "review_tags") ?? "";
}

function clearLegacyDraftKeys(): void {
  safeLocalStorageRemoveItem("annotationDraft");
  safeLocalStorageRemoveItem("annotation_draft");
  safeLocalStorageRemoveItem("reviewTitle");
  safeLocalStorageRemoveItem("review_title");
  safeLocalStorageRemoveItem("reviewDraft");
  safeLocalStorageRemoveItem("review_draft");
  safeLocalStorageRemoveItem("reviewTags");
  safeLocalStorageRemoveItem("review_tags");
}

type WorkspaceDraftSnapshot = {
  annotationDraft: string;
  reviewTitle: string;
  reviewDraft: string;
  reviewTags: string;
};

type WorkspaceDraftEntry = WorkspaceDraftSnapshot & {
  updatedAt: number;
};

type WorkspaceDraftStore = {
  __schema_version: number;
  entries: Record<string, WorkspaceDraftEntry>;
};

type WorkspaceDraftWriteResult = {
  persisted: boolean;
  wroteModern: boolean;
  canCleanupLegacy: boolean;
  persistenceTarget: "modern" | "legacy" | "none";
  errorKind: WorkspaceDraftPersistErrorKind;
};

type WorkspaceDraftPersistErrorKind = "none" | "storage_unavailable" | "write_failed" | "verify_mismatch";

type WorkspaceDraftPersistResult = {
  persisted: boolean;
  errorKind: WorkspaceDraftPersistErrorKind;
};

type WorkspaceDraftRuntimeStatus = {
  reason: string;
  lastAttemptAt: number | null;
  lastPersistedAt: number | null;
  lastScopeKey: string | null;
  lastPersisted: boolean | null;
  lastPersistenceTarget: "modern" | "legacy" | "none";
  lastErrorKind: WorkspaceDraftPersistErrorKind | null;
  retryCount: number;
  nextRetryDelayMs: number;
  pendingScopeKey: string | null;
};

const MAX_WORKSPACE_DRAFTS = 120;
const EMERGENCY_WORKSPACE_DRAFTS = 40;
const MAX_DRAFT_TEXT_LENGTH = 20_000;
const MAX_DRAFT_TITLE_LENGTH = 120;
const MAX_DRAFT_TAGS_LENGTH = 500;
const WORKSPACE_DRAFT_STORE_SCHEMA_VERSION = 1;
const LEGACY_TIMEFRAME_ALIASES: Record<string, string> = {
  "1": "1m",
  "5": "5m",
  "15": "15m",
  "30": "30m",
  "60": "60m",
  day: "D",
  daily: "D",
  week: "W",
  weekly: "W",
  month: "M",
  monthly: "M",
};

function buildWorkspaceDraftScopeKey(symbol: string | null, timeframe: string): string {
  const normalizedSymbol = (symbol ?? "").trim().toLowerCase() || "__none__";
  const normalizedTimeframe = normalizeTimeframeValue(timeframe) ?? timeframe;
  return `${normalizedSymbol}::${normalizedTimeframe}`;
}

function readWorkspaceDraftSnapshot(scopeKey: string, useLegacyFallback: boolean): WorkspaceDraftSnapshot {
  const store = readWorkspaceDraftStore();
  const scoped = store[scopeKey];
  if (!scoped) {
    return normalizeWorkspaceDraftSnapshot({
      annotationDraft: useLegacyFallback ? readLegacyAnnotationDraft() : "",
      reviewTitle: useLegacyFallback ? readLegacyReviewTitle() : "复盘笔记",
      reviewDraft: useLegacyFallback ? readLegacyReviewDraft() : "",
      reviewTags: useLegacyFallback ? readLegacyReviewTags() : "",
    });
  }
  return normalizeWorkspaceDraftSnapshot({
    annotationDraft: scoped.annotationDraft,
    reviewTitle: scoped.reviewTitle,
    reviewDraft: scoped.reviewDraft,
    reviewTags: scoped.reviewTags,
  });
}

function readWorkspaceDraftStore(): Record<string, WorkspaceDraftEntry> {
  const modernStore = parseWorkspaceDraftStore(readJsonStorageByKeys("workspaceDrafts"));
  const legacyStore = parseWorkspaceDraftStore(readJsonStorageByKeys("workspace_drafts"));
  const entries = mergeWorkspaceDraftEntries(modernStore.entries, legacyStore.entries);
  const legacyEntryCount = Object.keys(legacyStore.entries).length;
  const shouldPersist = legacyEntryCount > 0 || modernStore.migrated || legacyStore.migrated;
  if (shouldPersist) {
    const persistResult = persistWorkspaceDraftStore(trimWorkspaceDraftStore(entries, MAX_WORKSPACE_DRAFTS));
    if (persistResult.persisted) {
      safeLocalStorageRemoveItem("workspace_drafts");
    }
  }
  return entries;
}

function writeWorkspaceDraftSnapshot(scopeKey: string, snapshot: WorkspaceDraftSnapshot): WorkspaceDraftWriteResult {
  const normalizedSnapshot = normalizeWorkspaceDraftSnapshot(snapshot);
  const store = readWorkspaceDraftStore();
  if (workspaceDraftSnapshotIsEmpty(normalizedSnapshot)) {
    if (store[scopeKey]) {
      delete store[scopeKey];
      if (Object.keys(store).length === 0) {
        const modernCleared = clearWorkspaceDraftStoreAndVerify();
        return {
          persisted: modernCleared.persisted,
          wroteModern: modernCleared.persisted,
          canCleanupLegacy: modernCleared.persisted,
          persistenceTarget: modernCleared.persisted ? "modern" : "none",
          errorKind: modernCleared.errorKind,
        };
      } else {
        const persistResult = persistWorkspaceDraftStore(trimWorkspaceDraftStore(store, MAX_WORKSPACE_DRAFTS));
        if (persistResult.persisted) {
          safeLocalStorageRemoveItem("workspace_drafts");
          return { persisted: true, wroteModern: true, canCleanupLegacy: true, persistenceTarget: "modern", errorKind: "none" };
        }
        return {
          persisted: false,
          wroteModern: false,
          canCleanupLegacy: false,
          persistenceTarget: "none",
          errorKind: persistResult.errorKind,
        };
      }
    }
    const legacyCleared = clearLegacyDraftKeysAndVerify();
    if (legacyCleared.persisted) {
      return { persisted: true, wroteModern: false, canCleanupLegacy: false, persistenceTarget: "legacy", errorKind: "none" };
    }
    return {
      persisted: false,
      wroteModern: false,
      canCleanupLegacy: false,
      persistenceTarget: "none",
      errorKind: legacyCleared.errorKind,
    };
  }
  const previous = store[scopeKey];
  if (previous && workspaceDraftSnapshotEqual(previous, normalizedSnapshot)) {
    return {
      persisted: true,
      wroteModern: false,
      canCleanupLegacy: hasModernWorkspaceDraftStore(),
      persistenceTarget: hasModernWorkspaceDraftStore() ? "modern" : "legacy",
      errorKind: "none",
    };
  }
  store[scopeKey] = {
    annotationDraft: normalizedSnapshot.annotationDraft,
    reviewTitle: normalizedSnapshot.reviewTitle,
    reviewDraft: normalizedSnapshot.reviewDraft,
    reviewTags: normalizedSnapshot.reviewTags,
    updatedAt: Date.now(),
  };
  const persistResult = persistWorkspaceDraftStore(trimWorkspaceDraftStore(store, MAX_WORKSPACE_DRAFTS));
  if (persistResult.persisted) {
    safeLocalStorageRemoveItem("workspace_drafts");
    return { persisted: true, wroteModern: true, canCleanupLegacy: true, persistenceTarget: "modern", errorKind: "none" };
  }
  const fallbackResult = persistLegacyWorkspaceDraftSnapshot(normalizedSnapshot);
  return {
    persisted: fallbackResult.persisted,
    wroteModern: false,
    canCleanupLegacy: false,
    persistenceTarget: fallbackResult.persisted ? "legacy" : "none",
    errorKind: fallbackResult.errorKind,
  };
}

function persistLegacyWorkspaceDraftSnapshot(snapshot: WorkspaceDraftSnapshot): WorkspaceDraftPersistResult {
  const title = snapshot.reviewTitle.trim() || "复盘笔记";
  const writes = [
    safeLocalStorageSetItem("annotationDraft", snapshot.annotationDraft),
    safeLocalStorageSetItem("annotation_draft", snapshot.annotationDraft),
    safeLocalStorageSetItem("reviewTitle", title),
    safeLocalStorageSetItem("review_title", title),
    safeLocalStorageSetItem("reviewDraft", snapshot.reviewDraft),
    safeLocalStorageSetItem("review_draft", snapshot.reviewDraft),
    safeLocalStorageSetItem("reviewTags", snapshot.reviewTags),
    safeLocalStorageSetItem("review_tags", snapshot.reviewTags),
  ];
  if (!writes.every(Boolean)) {
    return { persisted: false, errorKind: canReadLocalStorage() ? "write_failed" : "storage_unavailable" };
  }
  return verifyLegacyWorkspaceDraftSnapshot(snapshot, title);
}

function verifyLegacyWorkspaceDraftSnapshot(snapshot: WorkspaceDraftSnapshot, title: string): WorkspaceDraftPersistResult {
  const annotationDraft = strictLocalStorageGetItem("annotationDraft");
  const annotationDraftLegacy = strictLocalStorageGetItem("annotation_draft");
  const reviewTitle = strictLocalStorageGetItem("reviewTitle");
  const reviewTitleLegacy = strictLocalStorageGetItem("review_title");
  const reviewDraft = strictLocalStorageGetItem("reviewDraft");
  const reviewDraftLegacy = strictLocalStorageGetItem("review_draft");
  const reviewTags = strictLocalStorageGetItem("reviewTags");
  const reviewTagsLegacy = strictLocalStorageGetItem("review_tags");
  if (
    annotationDraft === undefined ||
    annotationDraftLegacy === undefined ||
    reviewTitle === undefined ||
    reviewTitleLegacy === undefined ||
    reviewDraft === undefined ||
    reviewDraftLegacy === undefined ||
    reviewTags === undefined ||
    reviewTagsLegacy === undefined
  ) {
    return { persisted: false, errorKind: "storage_unavailable" };
  }
  const matched = (
    annotationDraft === snapshot.annotationDraft &&
    annotationDraftLegacy === snapshot.annotationDraft &&
    reviewTitle === title &&
    reviewTitleLegacy === title &&
    reviewDraft === snapshot.reviewDraft &&
    reviewDraftLegacy === snapshot.reviewDraft &&
    reviewTags === snapshot.reviewTags &&
    reviewTagsLegacy === snapshot.reviewTags
  );
  return matched ? { persisted: true, errorKind: "none" } : { persisted: false, errorKind: "verify_mismatch" };
}

function hasModernWorkspaceDraftStore(): boolean {
  const rawStore = readJsonStorageByKeys("workspaceDrafts");
  if (!isRecord(rawStore)) {
    return false;
  }
  const parsedStore = parseWorkspaceDraftStore(rawStore);
  if (Object.keys(parsedStore.entries).length > 0) {
    return true;
  }
  const version = Number(rawStore.__schema_version);
  if (!Number.isFinite(version) || version < 1 || !isRecord(rawStore.entries)) {
    return false;
  }
  if (parsedStore.migrated) {
    return false;
  }
  return Object.keys(rawStore.entries).length === 0;
}

function clearLegacyDraftKeysAndVerify(): WorkspaceDraftPersistResult {
  if (!canReadLocalStorage()) {
    return { persisted: false, errorKind: "storage_unavailable" };
  }
  clearLegacyDraftKeys();
  const annotationDraft = strictLocalStorageGetItem("annotationDraft");
  const annotationDraftLegacy = strictLocalStorageGetItem("annotation_draft");
  const reviewTitle = strictLocalStorageGetItem("reviewTitle");
  const reviewTitleLegacy = strictLocalStorageGetItem("review_title");
  const reviewDraft = strictLocalStorageGetItem("reviewDraft");
  const reviewDraftLegacy = strictLocalStorageGetItem("review_draft");
  const reviewTags = strictLocalStorageGetItem("reviewTags");
  const reviewTagsLegacy = strictLocalStorageGetItem("review_tags");
  if (
    annotationDraft === undefined ||
    annotationDraftLegacy === undefined ||
    reviewTitle === undefined ||
    reviewTitleLegacy === undefined ||
    reviewDraft === undefined ||
    reviewDraftLegacy === undefined ||
    reviewTags === undefined ||
    reviewTagsLegacy === undefined
  ) {
    return { persisted: false, errorKind: "storage_unavailable" };
  }
  const cleared = (
    annotationDraft === null &&
    annotationDraftLegacy === null &&
    reviewTitle === null &&
    reviewTitleLegacy === null &&
    reviewDraft === null &&
    reviewDraftLegacy === null &&
    reviewTags === null &&
    reviewTagsLegacy === null
  );
  return cleared ? { persisted: true, errorKind: "none" } : { persisted: false, errorKind: "verify_mismatch" };
}

function clearWorkspaceDraftStoreAndVerify(): WorkspaceDraftPersistResult {
  if (!canReadLocalStorage()) {
    return { persisted: false, errorKind: "storage_unavailable" };
  }
  safeLocalStorageRemoveItem("workspaceDrafts");
  safeLocalStorageRemoveItem("workspace_drafts");
  const modernStore = strictLocalStorageGetItem("workspaceDrafts");
  const legacyStore = strictLocalStorageGetItem("workspace_drafts");
  if (modernStore === undefined || legacyStore === undefined) {
    return { persisted: false, errorKind: "storage_unavailable" };
  }
  return modernStore === null && legacyStore === null
    ? { persisted: true, errorKind: "none" }
    : { persisted: false, errorKind: "verify_mismatch" };
}

function canReadLocalStorage(): boolean {
  try {
    void localStorage.getItem("__aether_localstorage_read_probe__");
    return true;
  } catch {
    return false;
  }
}

function safeLocalStorageGetItem(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function strictLocalStorageGetItem(key: string): string | null | undefined {
  try {
    return localStorage.getItem(key);
  } catch {
    return undefined;
  }
}

function safeLocalStorageSetItem(key: string, value: string): boolean {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch {
    // 存储不可用或超限时静默降级，避免影响主工作流。
    return false;
  }
}

function safeLocalStorageRemoveItem(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // 存储不可用时忽略清理失败。
  }
}

function publishWorkspaceDraftRuntimeStatus(
  statusRef: { current: WorkspaceDraftRuntimeStatus },
  patch: Partial<WorkspaceDraftRuntimeStatus>,
  onChange?: (value: WorkspaceDraftRuntimeStatus) => void,
): void {
  const next = {
    ...statusRef.current,
    ...patch,
  };
  statusRef.current = next;
  onChange?.(next);
  try {
    (window as Window & { __aetherWorkspaceDraftRuntime?: WorkspaceDraftRuntimeStatus }).__aetherWorkspaceDraftRuntime = next;
  } catch {
    // 调试状态写入失败时忽略，避免影响主流程。
  }
}

function parseWorkspaceDraftEntry(value: unknown): WorkspaceDraftEntry | null {
  if (!isRecord(value)) {
    return null;
  }
  const normalizedSnapshot = normalizeWorkspaceDraftSnapshot({
    annotationDraft: readDraftString(value, "annotationDraft", "annotation_draft", ""),
    reviewTitle: readDraftString(value, "reviewTitle", "review_title", "复盘笔记"),
    reviewDraft: readDraftString(value, "reviewDraft", "review_draft", ""),
    reviewTags: readDraftString(value, "reviewTags", "review_tags", ""),
  });
  const updatedAtValue = Number(value.updatedAt ?? value.updated_at);
  return {
    annotationDraft: normalizedSnapshot.annotationDraft,
    reviewTitle: normalizedSnapshot.reviewTitle,
    reviewDraft: normalizedSnapshot.reviewDraft,
    reviewTags: normalizedSnapshot.reviewTags,
    updatedAt: Number.isFinite(updatedAtValue) && updatedAtValue > 0 ? updatedAtValue : 0,
  };
}

function parseWorkspaceDraftStore(value: unknown): { entries: Record<string, WorkspaceDraftEntry>; migrated: boolean } {
  if (!isRecord(value)) {
    return { entries: {}, migrated: false };
  }
  const version = Number(value.__schema_version);
  if (Number.isFinite(version) && version >= 1) {
    const parsedEntriesResult = parseWorkspaceDraftEntries(value.entries);
    const legacyRootEntriesResult = parseWorkspaceDraftEntries(value);
    const mergedEntries = mergeWorkspaceDraftEntries(parsedEntriesResult.entries, legacyRootEntriesResult.entries);
    const migrated =
      version < WORKSPACE_DRAFT_STORE_SCHEMA_VERSION ||
      parsedEntriesResult.normalized ||
      legacyRootEntriesResult.normalized ||
      (Object.keys(parsedEntriesResult.entries).length === 0 && Object.keys(legacyRootEntriesResult.entries).length > 0);
    return { entries: mergedEntries, migrated };
  }
  const parsedLegacyEntries = parseWorkspaceDraftEntries(value);
  return {
    entries: parsedLegacyEntries.entries,
    migrated: true,
  };
}

function parseWorkspaceDraftEntries(value: unknown): { entries: Record<string, WorkspaceDraftEntry>; normalized: boolean } {
  if (!isRecord(value)) {
    return { entries: {}, normalized: false };
  }
  const normalized: Record<string, WorkspaceDraftEntry> = {};
  let normalizedChanged = false;
  for (const [key, entryValue] of Object.entries(value)) {
    if (key.startsWith("__") || key === "entries") {
      continue;
    }
    const normalizedScopeKey = normalizeWorkspaceDraftScopeKey(key);
    if (!normalizedScopeKey) {
      normalizedChanged = true;
      continue;
    }
    if (normalizedScopeKey !== key) {
      normalizedChanged = true;
    }
    const parsed = parseWorkspaceDraftEntry(entryValue);
    if (parsed) {
      const previous = normalized[normalizedScopeKey];
      if (!previous || shouldPreferWorkspaceDraftEntry(parsed, previous)) {
        normalized[normalizedScopeKey] = parsed;
      }
    } else {
      normalizedChanged = true;
    }
  }
  return { entries: normalized, normalized: normalizedChanged };
}

function normalizeWorkspaceDraftScopeKey(value: string): string | null {
  const separatorIndex = value.indexOf("::");
  if (separatorIndex <= 0 || separatorIndex !== value.lastIndexOf("::")) {
    return null;
  }
  const symbolPart = value.slice(0, separatorIndex).trim().toLowerCase();
  const timeframePart = value.slice(separatorIndex + 2).trim();
  if (symbolPart.length === 0 || timeframePart.length === 0) {
    return null;
  }
  if (symbolPart.length > 64 || timeframePart.length > 16) {
    return null;
  }
  if (symbolPart !== "__none__" && !/^[a-z0-9._-]+$/.test(symbolPart)) {
    return null;
  }
  const normalizedTimeframe = normalizeWorkspaceDraftTimeframe(timeframePart);
  if (!normalizedTimeframe) {
    return null;
  }
  return `${symbolPart}::${normalizedTimeframe}`;
}

function normalizeWorkspaceDraftTimeframe(value: string): string | null {
  const normalized = normalizeTimeframeValue(value);
  if (!normalized) {
    return null;
  }
  if (timeframes.some((item) => item.value === normalized)) {
    return normalized;
  }
  const alias = LEGACY_TIMEFRAME_ALIASES[normalized.toLowerCase()];
  return alias && timeframes.some((item) => item.value === alias) ? alias : null;
}

function shouldPreferWorkspaceDraftEntry(next: WorkspaceDraftEntry, current: WorkspaceDraftEntry): boolean {
  if (next.updatedAt !== current.updatedAt) {
    return next.updatedAt > current.updatedAt;
  }
  return workspaceDraftEntryScore(next) > workspaceDraftEntryScore(current);
}

function mergeWorkspaceDraftEntries(
  modernEntries: Record<string, WorkspaceDraftEntry>,
  legacyEntries: Record<string, WorkspaceDraftEntry>,
): Record<string, WorkspaceDraftEntry> {
  const merged: Record<string, WorkspaceDraftEntry> = { ...modernEntries };
  for (const [scopeKey, legacyEntry] of Object.entries(legacyEntries)) {
    const modernEntry = merged[scopeKey];
    if (!modernEntry || shouldPreferWorkspaceDraftEntry(legacyEntry, modernEntry)) {
      merged[scopeKey] = legacyEntry;
    }
  }
  return merged;
}

function workspaceDraftEntryScore(entry: WorkspaceDraftEntry): number {
  const normalizedTitle = entry.reviewTitle.trim();
  const titleScore = normalizedTitle.length > 0 && normalizedTitle !== "复盘笔记" ? normalizedTitle.length : 0;
  return (
    entry.annotationDraft.trim().length +
    entry.reviewDraft.trim().length +
    entry.reviewTags.trim().length +
    titleScore
  );
}

function trimWorkspaceDraftStore(
  store: Record<string, WorkspaceDraftEntry>,
  limit: number,
): Record<string, WorkspaceDraftEntry> {
  const entries = Object.entries(store);
  if (entries.length <= limit) {
    return store;
  }
  const sorted = entries.sort((left, right) => {
    const updatedAtDelta = right[1].updatedAt - left[1].updatedAt;
    if (updatedAtDelta !== 0) {
      return updatedAtDelta;
    }
    return left[0].localeCompare(right[0]);
  });
  return Object.fromEntries(sorted.slice(0, limit));
}

function persistWorkspaceDraftStore(store: Record<string, WorkspaceDraftEntry>): WorkspaceDraftPersistResult {
  const payload = JSON.stringify(serializeWorkspaceDraftStore(store));
  const firstTry = setWorkspaceDraftStoreAndVerify(payload);
  if (firstTry.persisted) {
    return firstTry;
  }
  const emergencyTrimmedStore = trimWorkspaceDraftStore(store, EMERGENCY_WORKSPACE_DRAFTS);
  return setWorkspaceDraftStoreAndVerify(JSON.stringify(serializeWorkspaceDraftStore(emergencyTrimmedStore)));
}

function setWorkspaceDraftStoreAndVerify(payload: string): WorkspaceDraftPersistResult {
  if (!safeLocalStorageSetItem("workspaceDrafts", payload)) {
    return { persisted: false, errorKind: canReadLocalStorage() ? "write_failed" : "storage_unavailable" };
  }
  const verified = strictLocalStorageGetItem("workspaceDrafts");
  if (verified === undefined) {
    return { persisted: false, errorKind: "storage_unavailable" };
  }
  return verified === payload ? { persisted: true, errorKind: "none" } : { persisted: false, errorKind: "verify_mismatch" };
}

function serializeWorkspaceDraftStore(store: Record<string, WorkspaceDraftEntry>): WorkspaceDraftStore {
  return {
    __schema_version: WORKSPACE_DRAFT_STORE_SCHEMA_VERSION,
    entries: store,
  };
}

function readDraftString(
  source: Record<string, unknown>,
  camelKey: string,
  snakeKey: string,
  fallback: string,
): string {
  const value = source[camelKey] ?? source[snakeKey];
  if (typeof value !== "string") {
    return fallback;
  }
  return value;
}

function normalizeWorkspaceDraftSnapshot(snapshot: WorkspaceDraftSnapshot): WorkspaceDraftSnapshot {
  const annotationDraft = truncateText(snapshot.annotationDraft, MAX_DRAFT_TEXT_LENGTH);
  const reviewTitle = truncateText(snapshot.reviewTitle, MAX_DRAFT_TITLE_LENGTH).trim() || "复盘笔记";
  const reviewDraft = truncateText(snapshot.reviewDraft, MAX_DRAFT_TEXT_LENGTH);
  const reviewTags = truncateText(snapshot.reviewTags, MAX_DRAFT_TAGS_LENGTH);
  return {
    annotationDraft,
    reviewTitle,
    reviewDraft,
    reviewTags,
  };
}

function truncateText(value: string, maxLength: number): string {
  return value.length > maxLength ? value.slice(0, maxLength) : value;
}

function workspaceDraftSnapshotEqual(
  entry: WorkspaceDraftEntry,
  snapshot: WorkspaceDraftSnapshot,
): boolean {
  return (
    entry.annotationDraft === snapshot.annotationDraft &&
    entry.reviewTitle === snapshot.reviewTitle &&
    entry.reviewDraft === snapshot.reviewDraft &&
    entry.reviewTags === snapshot.reviewTags
  );
}

function workspaceDraftSnapshotIsEmpty(snapshot: WorkspaceDraftSnapshot): boolean {
  const title = snapshot.reviewTitle.trim();
  return (
    snapshot.annotationDraft.trim().length === 0 &&
    snapshot.reviewDraft.trim().length === 0 &&
    snapshot.reviewTags.trim().length === 0 &&
    (title.length === 0 || title === "复盘笔记")
  );
}

function clampNumber(value: number, min: number, max: number, fallback: number): number {
  if (!Number.isFinite(value)) {
    return fallback;
  }
  return Math.min(Math.max(value, min), max);
}

function toDateInputValue(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
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
