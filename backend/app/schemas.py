from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class DataSourceCandidate(BaseModel):
    path: str
    exists: bool
    valid: bool
    label: str
    markets: list[str] = Field(default_factory=list)
    daily_files: int = 0
    minute1_files: int = 0
    minute5_files: int = 0
    size_bytes: int = 0
    latest_modified: str | None = None


class SourceRequest(BaseModel):
    path: str

    def normalized_path(self) -> Path:
        return Path(self.path).expanduser().resolve()


class SourceResponse(BaseModel):
    path: str | None
    valid: bool
    health: DataSourceCandidate | None = None


class HealthResponse(BaseModel):
    status: str


class DeleteResponse(BaseModel):
    deleted: bool


class ImportRequest(BaseModel):
    path: str | None = None
    markets: list[str] = Field(default_factory=lambda: ["sh", "sz", "bj"])
    limit_files: int | None = Field(default=None, ge=1)


class ImportResult(BaseModel):
    source_path: str
    files_seen: int
    files_imported: int
    bars_imported: int
    minute_files_seen: int = 0
    minute_files_imported: int = 0
    minute_bars_imported: int = 0
    symbols_imported: int
    errors: list[str] = Field(default_factory=list)


class ImportJob(BaseModel):
    id: str
    status: str
    source_path: str | None = None
    source_path_exists: bool | None = None
    files_seen: int = 0
    files_imported: int = 0
    bars_imported: int = 0
    minute_files_seen: int = 0
    minute_files_imported: int = 0
    minute_bars_imported: int = 0
    symbols_imported: int = 0
    errors: list[str] = Field(default_factory=list)
    message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class MarketCoverage(BaseModel):
    market: str
    symbols: int = 0
    bars: int = 0
    first_date: date | None = None
    last_date: date | None = None
    latest_symbols: int = 0


class TimeframeCoverage(BaseModel):
    timeframe: str
    label: str
    bars: int = 0
    symbols: int = 0
    first_time: str | None = None
    last_time: str | None = None
    available: bool = False
    derived_from: str | None = None


class DataRecommendation(BaseModel):
    severity: str
    title: str
    detail: str
    action: str


class DataHealthResponse(BaseModel):
    generated_at: datetime
    latest_trade_date: date | None = None
    days_since_latest: int | None = None
    daily_symbols: int = 0
    daily_bars: int = 0
    first_trade_date: date | None = None
    markets: list[MarketCoverage] = Field(default_factory=list)
    timeframes: list[TimeframeCoverage] = Field(default_factory=list)
    recommendations: list[DataRecommendation] = Field(default_factory=list)


class SymbolRecord(BaseModel):
    symbol: str
    market: str
    code: str
    name: str
    kind: str
    first_date: date | None = None
    last_date: date | None = None
    bar_count: int = 0


class BarRecord(BaseModel):
    symbol: str
    timeframe: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    amount: float
    volume: int


class AnalysisPoint(BaseModel):
    index: int
    trade_date: str
    price: float
    kind: str


class ChanBiSegment(BaseModel):
    index: int
    start_index: int
    end_index: int
    start_trade_date: str
    end_trade_date: str
    start_price: float
    end_price: float
    direction: str
    start_kind: str
    end_kind: str


class ChanLineSegment(BaseModel):
    index: int
    start_bi_index: int
    end_bi_index: int
    start_index: int
    end_index: int
    start_trade_date: str
    end_trade_date: str
    start_price: float
    end_price: float
    direction: str
    bi_count: int


class ChanZhongshu(BaseModel):
    index: int
    start_bi_index: int
    end_bi_index: int
    start_index: int
    end_index: int
    start_trade_date: str
    end_trade_date: str
    low: float
    high: float
    mid: float
    bi_count: int


class ChanAnalysisResponse(BaseModel):
    symbol: str
    timeframe: str
    algorithm: str
    version: str
    params: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime
    fractals: list[AnalysisPoint]
    bis: list[ChanBiSegment] = Field(default_factory=list)
    segments: list[ChanLineSegment] = Field(default_factory=list)
    zhongshu: list[ChanZhongshu] = Field(default_factory=list)


class WavePoint(BaseModel):
    index: int
    trade_date: str
    price: float
    kind: str
    wave_no: int


class WaveAnalysisResponse(BaseModel):
    symbol: str
    timeframe: str
    algorithm: str
    version: str
    params: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime
    threshold_pct: float
    pivots: list[WavePoint]


class BacktestTrade(BaseModel):
    index: int
    entry_index: int
    exit_index: int
    entry_trade_date: str
    exit_trade_date: str
    entry_price: float
    exit_price: float
    return_pct: float
    holding_bars: int
    entry_signal: str
    exit_signal: str
    exit_reason: str


class BacktestSummary(BaseModel):
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0
    total_return_pct: float = 0
    average_return_pct: float = 0
    max_drawdown_pct: float = 0
    average_holding_bars: float = 0
    min_holding_bars: int = 0
    max_holding_bars: int = 0
    median_holding_bars: float = 0


class BacktestEquityPoint(BaseModel):
    trade_index: int
    trade_date: str
    equity: float
    equity_return_pct: float
    drawdown_pct: float


class BacktestResponse(BaseModel):
    symbol: str
    timeframe: str
    algorithm: str
    version: str
    strategy: str
    structure_source: str = "auto"
    manual_annotation_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime
    bars_tested: int
    trades: list[BacktestTrade] = Field(default_factory=list)
    equity_curve: list[BacktestEquityPoint] = Field(default_factory=list)
    summary: BacktestSummary = Field(default_factory=BacktestSummary)


class AnnotationCreate(BaseModel):
    symbol: str
    timeframe: str
    overlay_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AnnotationUpdate(BaseModel):
    overlay_type: str | None = None
    payload: dict[str, Any] | None = None


class AnnotationRecord(BaseModel):
    id: str
    symbol: str
    timeframe: str
    overlay_type: str
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ReviewNoteSave(BaseModel):
    symbol: str
    timeframe: str
    content: str
    title: str = "复盘笔记"
    tags: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class ChartDataResponse(BaseModel):
    bars: list[BarRecord]
    chan: ChanAnalysisResponse
    wave: WaveAnalysisResponse
    annotations: list[AnnotationRecord]


class RuleProfile(BaseModel):
    id: str
    name: str
    analysis_type: Literal["chan", "wave"]
    version: str
    params: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    created_at: datetime
    updated_at: datetime


class RuleProfileCreate(BaseModel):
    name: str
    analysis_type: Literal["chan", "wave"]
    version: str = "0.1.0"
    params: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False


class UserBackupPayload(BaseModel):
    schema_version: int = 1
    exported_at: datetime | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    annotations: list[AnnotationRecord] = Field(default_factory=list)
    rule_profiles: list[RuleProfile] = Field(default_factory=list)


class UserBackupImportResult(BaseModel):
    config_imported: bool = False
    annotations_imported: int = 0
    rule_profiles_imported: int = 0


class AnalysisSchemePayload(BaseModel):
    schema_version: int = 1
    exported_at: datetime | None = None
    name: str = "AetherStock 分析方案"
    description: str = ""
    workspace: dict[str, Any] = Field(default_factory=dict)
    rule_profiles: list[RuleProfile] = Field(default_factory=list)


class AnalysisSchemeImportResult(BaseModel):
    rule_profiles_imported: int = 0
