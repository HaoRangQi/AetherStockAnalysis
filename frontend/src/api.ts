export type DataSourceCandidate = {
  path: string;
  exists: boolean;
  valid: boolean;
  label: string;
  markets: string[];
  daily_files: number;
  minute1_files: number;
  minute5_files: number;
  size_bytes: number;
  latest_modified: string | null;
};

export type SourceResponse = {
  path: string | null;
  valid: boolean;
  health: DataSourceCandidate | null;
};

export type HealthResponse = {
  status: string;
};

export type DeleteResponse = {
  deleted: boolean;
};

export type ImportResult = {
  source_path: string;
  files_seen: number;
  files_imported: number;
  bars_imported: number;
  minute_files_seen: number;
  minute_files_imported: number;
  minute_bars_imported: number;
  symbols_imported: number;
  errors: string[];
};

export type ImportJobStatus = "queued" | "running" | "succeeded" | "failed";
export type ImportJobListStatus = ImportJobStatus | "pending";

export type ImportJob = {
  id: string;
  status: ImportJobStatus;
  source_path: string | null;
  source_path_exists: boolean | null;
  files_seen: number;
  files_imported: number;
  bars_imported: number;
  minute_files_seen: number;
  minute_files_imported: number;
  minute_bars_imported: number;
  symbols_imported: number;
  errors: string[];
  message: string;
  started_at: string | null;
  finished_at: string | null;
};

export type MarketCoverage = {
  market: string;
  symbols: number;
  bars: number;
  first_date: string | null;
  last_date: string | null;
  latest_symbols: number;
};

export type TimeframeCoverage = {
  timeframe: string;
  label: string;
  bars: number;
  symbols: number;
  first_time: string | null;
  last_time: string | null;
  available: boolean;
  derived_from: string | null;
};

export type DataRecommendation = {
  severity: "ok" | "info" | "warn" | "danger" | string;
  title: string;
  detail: string;
  action: string;
};

export type DataHealth = {
  generated_at: string;
  latest_trade_date: string | null;
  days_since_latest: number | null;
  daily_symbols: number;
  daily_bars: number;
  first_trade_date: string | null;
  markets: MarketCoverage[];
  timeframes: TimeframeCoverage[];
  recommendations: DataRecommendation[];
};

export type SymbolRecord = {
  symbol: string;
  market: string;
  code: string;
  name: string;
  kind: string;
  first_date: string | null;
  last_date: string | null;
  bar_count: number;
};

export type BarRecord = {
  symbol: string;
  timeframe: string;
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  amount: number;
  volume: number;
};

export type ChanAnalysis = {
  symbol: string;
  timeframe: string;
  algorithm: string;
  version: string;
  params: Record<string, unknown>;
  generated_at: string;
  fractals: Array<{
    index: number;
    trade_date: string;
    price: number;
    kind: "top" | "bottom";
  }>;
  bis: Array<{
    index: number;
    start_index: number;
    end_index: number;
    start_trade_date: string;
    end_trade_date: string;
    start_price: number;
    end_price: number;
    direction: "up" | "down";
    start_kind: "top" | "bottom";
    end_kind: "top" | "bottom";
  }>;
  segments: Array<{
    index: number;
    start_bi_index: number;
    end_bi_index: number;
    start_index: number;
    end_index: number;
    start_trade_date: string;
    end_trade_date: string;
    start_price: number;
    end_price: number;
    direction: "up" | "down";
    bi_count: number;
  }>;
  zhongshu: Array<{
    index: number;
    start_bi_index: number;
    end_bi_index: number;
    start_index: number;
    end_index: number;
    start_trade_date: string;
    end_trade_date: string;
    low: number;
    high: number;
    mid: number;
    bi_count: number;
  }>;
};

export type WaveAnalysis = {
  symbol: string;
  timeframe: string;
  algorithm: string;
  version: string;
  params: Record<string, unknown>;
  generated_at: string;
  threshold_pct: number;
  pivots: Array<{
    index: number;
    trade_date: string;
    price: number;
    kind: "start" | "top" | "bottom";
    wave_no: number;
  }>;
};

export type BacktestTrade = {
  index: number;
  entry_index: number;
  exit_index: number;
  entry_trade_date: string;
  exit_trade_date: string;
  entry_price: number;
  exit_price: number;
  return_pct: number;
  holding_bars: number;
  entry_signal: string;
  exit_signal: string;
  exit_reason: string;
};

export type BacktestSummary = {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_return_pct: number;
  average_return_pct: number;
  max_drawdown_pct: number;
  average_holding_bars: number;
  min_holding_bars: number;
  max_holding_bars: number;
  median_holding_bars: number;
};

export type BacktestEquityPoint = {
  trade_index: number;
  trade_date: string;
  equity: number;
  equity_return_pct: number;
  drawdown_pct: number;
};

export type BacktestResult = {
  symbol: string;
  timeframe: string;
  algorithm: string;
  version: string;
  strategy: string;
  structure_source: "auto" | "manual" | string;
  manual_annotation_id: string | null;
  params: Record<string, unknown>;
  generated_at: string;
  bars_tested: number;
  trades: BacktestTrade[];
  equity_curve: BacktestEquityPoint[];
  summary: BacktestSummary;
};

export type BacktestStrategy =
  | "chan_fractal_reversal"
  | "chan_bi_reversal"
  | "chan_zhongshu_breakout"
  | "wave_zigzag_reversal";

export type BacktestOptions = {
  feeBps: number;
  slippageBps: number;
  positionPct: number;
  applyLimitConstraints: boolean;
  limitPct: number;
  thresholdPct?: number;
};

export type AnnotationRecord = {
  id: string;
  symbol: string;
  timeframe: string;
  overlay_type: string;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ChartData = {
  bars: BarRecord[];
  chan: ChanAnalysis;
  wave: WaveAnalysis;
  annotations: AnnotationRecord[];
};

export type RuleProfile = {
  id: string;
  name: string;
  analysis_type: string;
  version: string;
  params: Record<string, unknown>;
  is_default: boolean;
  created_at: string;
  updated_at: string;
};

export type RuleProfileCreate = {
  name: string;
  analysis_type: "chan" | "wave" | string;
  version: string;
  params: Record<string, unknown>;
  is_default: boolean;
};

export type UserBackupPayload = {
  schema_version: number;
  exported_at: string | null;
  config: Record<string, unknown>;
  annotations: AnnotationRecord[];
  rule_profiles: RuleProfile[];
};

export type UserBackupImportResult = {
  config_imported: boolean;
  annotations_imported: number;
  rule_profiles_imported: number;
};

export type ReviewNoteSave = {
  symbol: string;
  timeframe: string;
  title: string;
  content: string;
  tags: string[];
  payload: Record<string, unknown>;
};

export type AnalysisSchemePayload = {
  schema_version: number;
  exported_at: string | null;
  name: string;
  description: string;
  workspace: Record<string, unknown>;
  rule_profiles: RuleProfile[];
};

export type AnalysisSchemeImportResult = {
  rule_profiles_imported: number;
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000/api";

export async function getHealth(): Promise<HealthResponse> {
  return request("/health");
}

export async function getCurrentSource(): Promise<SourceResponse> {
  return request("/sources/current");
}

export async function detectSources(): Promise<DataSourceCandidate[]> {
  return request("/sources/detect");
}

export async function getDataHealth(): Promise<DataHealth> {
  return request("/data/health");
}

export async function saveSource(path: string): Promise<SourceResponse> {
  return request("/sources", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export async function importDaily(path?: string): Promise<ImportResult> {
  return request("/imports/daily", {
    method: "POST",
    body: JSON.stringify({ path: path || null }),
  });
}

export async function startImportJob(path?: string): Promise<ImportJob> {
  return request("/imports/jobs", {
    method: "POST",
    body: JSON.stringify({ path: path || null }),
  });
}

export async function getImportJob(jobId: string): Promise<ImportJob> {
  return request(`/imports/jobs/${encodeURIComponent(jobId)}`);
}

export async function listImportJobs(limit = 20, status?: ImportJobListStatus): Promise<ImportJob[]> {
  return listImportJobsWithFilters(limit, { status });
}

type ImportJobListFilters = {
  status?: ImportJobListStatus;
  sourcePathExists?: boolean;
};

export async function listImportJobsWithFilters(limit = 20, filters: ImportJobListFilters = {}): Promise<ImportJob[]> {
  const normalizedLimit = Math.min(Math.max(Math.floor(limit), 1), 200);
  const params = new URLSearchParams();
  params.set("limit", String(normalizedLimit));
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.sourcePathExists !== undefined) {
    params.set("source_path_exists", String(filters.sourcePathExists));
  }
  return request(`/imports/jobs?${params.toString()}`);
}

export async function searchSymbols(query: string): Promise<SymbolRecord[]> {
  return request(`/symbols?q=${encodeURIComponent(query)}&limit=80`);
}

export type DateRange = {
  startDate?: string;
  endDate?: string;
  before?: string;
  limit?: number;
};

export async function getBars(symbol: string, timeframe: string, range: DateRange = {}): Promise<BarRecord[]> {
  const query = marketDataQuery(symbol, timeframe, range);
  return request(`/bars?${query}`);
}

export async function getChanAnalysis(symbol: string, timeframe: string, range: DateRange = {}): Promise<ChanAnalysis> {
  const query = marketDataQuery(symbol, timeframe, range);
  return request(`/analysis/chan?${query}`);
}

export async function getWaveAnalysis(
  symbol: string,
  timeframe: string,
  range: DateRange = {},
  thresholdPct = 5,
): Promise<WaveAnalysis> {
  const params = baseMarketDataParams(symbol, timeframe);
  params.set("threshold_pct", String(thresholdPct));
  const query = mergeQueryParams(params, range);
  return request(`/analysis/wave?${query}`);
}

export async function getStructureBacktest(
  symbol: string,
  timeframe: string,
  range: DateRange = {},
  strategy: BacktestStrategy = "chan_fractal_reversal",
  options: BacktestOptions = { feeBps: 0, slippageBps: 0, positionPct: 100, applyLimitConstraints: false, limitPct: 10 },
): Promise<BacktestResult> {
  const params = new URLSearchParams();
  params.set("symbol", symbol);
  params.set("timeframe", timeframe);
  params.set("strategy", strategy);
  params.set("fee_bps", String(options.feeBps));
  params.set("slippage_bps", String(options.slippageBps));
  params.set("position_pct", String(options.positionPct));
  params.set("apply_limit_constraints", String(options.applyLimitConstraints));
  params.set("limit_pct", String(options.limitPct));
  if (options.thresholdPct !== undefined) {
    params.set("threshold_pct", String(options.thresholdPct));
  }
  const query = mergeQueryParams(params, range);
  return request(
    `/backtests/structure?${query}`,
  );
}

export async function getChartData(
  symbol: string,
  timeframe: string,
  range: DateRange = {},
  thresholdPct = 5,
): Promise<ChartData> {
  const params = baseMarketDataParams(symbol, timeframe);
  params.set("threshold_pct", String(thresholdPct));
  const query = mergeQueryParams(params, range);
  return request(`/chart?${query}`);
}

export async function getAnnotations(symbol: string, timeframe: string): Promise<AnnotationRecord[]> {
  return request(`/annotations?${baseMarketDataParams(symbol, timeframe).toString()}`);
}

export async function createAnnotation(
  symbol: string,
  timeframe: string,
  overlayType: string,
  payload: Record<string, unknown>,
): Promise<AnnotationRecord> {
  return request("/annotations", {
    method: "POST",
    body: JSON.stringify({
      symbol,
      timeframe,
      overlay_type: overlayType,
      payload,
    }),
  });
}

export async function updateAnnotation(
  id: string,
  overlayType: string | null,
  payload: Record<string, unknown> | null,
): Promise<AnnotationRecord> {
  return request(`/annotations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({
      overlay_type: overlayType,
      payload,
    }),
  });
}

export async function deleteAnnotation(id: string): Promise<DeleteResponse> {
  return request(`/annotations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function getReviewNotes(symbol: string, timeframe: string): Promise<AnnotationRecord[]> {
  return request(`/review-notes?${baseMarketDataParams(symbol, timeframe).toString()}`);
}

export async function saveReviewNote(payload: ReviewNoteSave): Promise<AnnotationRecord> {
  return request("/review-notes", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getRuleProfiles(analysisType?: string): Promise<RuleProfile[]> {
  const suffix = analysisType ? `?analysis_type=${encodeURIComponent(analysisType)}` : "";
  return request(`/rule-profiles${suffix}`);
}

export async function createRuleProfile(payload: RuleProfileCreate): Promise<RuleProfile> {
  return request("/rule-profiles", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function exportUserBackup(): Promise<UserBackupPayload> {
  return request("/backups/user");
}

export async function importUserBackup(payload: UserBackupPayload): Promise<UserBackupImportResult> {
  return request("/backups/user", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function exportAnalysisScheme(
  name = "AetherStock 分析方案",
  description = "",
): Promise<AnalysisSchemePayload> {
  const params = new URLSearchParams();
  params.set("name", name);
  params.set("description", description);
  return request(`/schemes/analysis?${params.toString()}`);
}

export async function importAnalysisScheme(payload: AnalysisSchemePayload): Promise<AnalysisSchemeImportResult> {
  return request("/schemes/analysis", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
    },
    ...init,
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `请求失败：${response.status}`);
  }
  return response.json() as Promise<T>;
}

function marketDataQuery(symbol: string, timeframe: string, range: DateRange): string {
  return mergeQueryParams(baseMarketDataParams(symbol, timeframe), range);
}

function baseMarketDataParams(symbol: string, timeframe: string): URLSearchParams {
  const params = new URLSearchParams();
  params.set("symbol", symbol);
  params.set("timeframe", timeframe);
  return params;
}

function mergeQueryParams(params: URLSearchParams, range: DateRange): string {
  addRangeParams(params, range);
  return params.toString();
}

function addRangeParams(params: URLSearchParams, range: DateRange) {
  params.set("limit", String(range.limit ?? 520));
  if (range.startDate) {
    params.set("start_date", range.startDate);
  }
  if (range.endDate) {
    params.set("end_date", range.endDate);
  }
  if (range.before) {
    params.set("before", range.before);
  }
}
