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

export type ImportResult = {
  source_path: string;
  files_seen: number;
  files_imported: number;
  bars_imported: number;
  minute_bars_imported: number;
  symbols_imported: number;
  errors: string[];
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
  fractals: Array<{
    index: number;
    trade_date: string;
    price: number;
    kind: "top" | "bottom";
  }>;
};

export type WaveAnalysis = {
  symbol: string;
  timeframe: string;
  algorithm: string;
  version: string;
  threshold_pct: number;
  pivots: Array<{
    index: number;
    trade_date: string;
    price: number;
    kind: "start" | "top" | "bottom";
    wave_no: number;
  }>;
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

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000/api";

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
  return request(`/bars?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}${rangeQuery(range)}`);
}

export async function getChanAnalysis(symbol: string, timeframe: string, range: DateRange = {}): Promise<ChanAnalysis> {
  return request(`/analysis/chan?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}${rangeQuery(range)}`);
}

export async function getWaveAnalysis(symbol: string, timeframe: string, range: DateRange = {}): Promise<WaveAnalysis> {
  return request(
    `/analysis/wave?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}${rangeQuery(range)}&threshold_pct=5`,
  );
}

export async function getChartData(symbol: string, timeframe: string, range: DateRange = {}): Promise<ChartData> {
  return request(`/chart?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}${rangeQuery(range)}&threshold_pct=5`);
}

export async function getAnnotations(symbol: string, timeframe: string): Promise<AnnotationRecord[]> {
  return request(`/annotations?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}`);
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

export async function deleteAnnotation(id: string): Promise<{ deleted: boolean }> {
  return request(`/annotations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function getRuleProfiles(analysisType?: string): Promise<RuleProfile[]> {
  const suffix = analysisType ? `?analysis_type=${encodeURIComponent(analysisType)}` : "";
  return request(`/rule-profiles${suffix}`);
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

function rangeQuery(range: DateRange): string {
  const params = new URLSearchParams();
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
  return `&${params.toString()}`;
}
