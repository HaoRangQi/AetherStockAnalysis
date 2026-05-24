from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

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


class ImportRequest(BaseModel):
    path: str | None = None
    markets: list[str] = Field(default_factory=lambda: ["sh", "sz", "bj"])
    limit_files: int | None = None


class ImportResult(BaseModel):
    source_path: str
    files_seen: int
    files_imported: int
    bars_imported: int
    minute_bars_imported: int = 0
    symbols_imported: int
    errors: list[str] = Field(default_factory=list)


class ImportJob(BaseModel):
    id: str
    status: str
    source_path: str | None = None
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


class ChanAnalysisResponse(BaseModel):
    symbol: str
    timeframe: str
    algorithm: str
    version: str
    fractals: list[AnalysisPoint]


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
    threshold_pct: float
    pivots: list[WavePoint]


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


class ChartDataResponse(BaseModel):
    bars: list[BarRecord]
    chan: ChanAnalysisResponse
    wave: WaveAnalysisResponse
    annotations: list[AnnotationRecord]


class RuleProfile(BaseModel):
    id: str
    name: str
    analysis_type: str
    version: str
    params: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    created_at: datetime
    updated_at: datetime


class RuleProfileCreate(BaseModel):
    name: str
    analysis_type: str
    version: str = "0.1.0"
    params: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
