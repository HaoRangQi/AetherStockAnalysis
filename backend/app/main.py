from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .analysis import detect_fractals, detect_zigzag_waves
from .config import load_config, save_config
from .schemas import (
    AnnotationCreate,
    AnnotationRecord,
    AnnotationUpdate,
    ChartDataResponse,
    ChanAnalysisResponse,
    DataSourceCandidate,
    ImportRequest,
    ImportResult,
    RuleProfile,
    RuleProfileCreate,
    SourceRequest,
    SourceResponse,
    WaveAnalysisResponse,
)
from .storage import (
    apply_symbol_names,
    connect,
    create_annotation,
    create_rule_profile,
    delete_annotation,
    get_bars,
    import_daily_files,
    list_annotations,
    list_rule_profiles,
    search_symbols,
    update_annotation,
)
from .tdx import detect_sources, inspect_source, iter_daily_files, load_symbol_name_map

app = FastAPI(title="AetherStockAnalysis API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/sources/detect", response_model=list[DataSourceCandidate])
def api_detect_sources() -> list[DataSourceCandidate]:
    return detect_sources()


@app.get("/api/sources/current", response_model=SourceResponse)
def api_current_source() -> SourceResponse:
    config = load_config()
    path = config.get("source_path")
    if not path:
        detected = [candidate for candidate in detect_sources() if candidate.valid]
        if detected:
            return SourceResponse(path=detected[0].path, valid=True, health=detected[0])
        return SourceResponse(path=None, valid=False)
    health = inspect_source(Path(path), "当前数据源")
    return SourceResponse(path=path, valid=health.valid, health=health)


@app.post("/api/sources", response_model=SourceResponse)
def api_save_source(request: SourceRequest) -> SourceResponse:
    path = request.normalized_path()
    health = inspect_source(path, "当前数据源")
    if not health.valid:
        raise HTTPException(status_code=400, detail="数据源无效：没有找到通达信日线数据。")
    config = load_config()
    config["source_path"] = str(path)
    save_config(config)
    return SourceResponse(path=str(path), valid=True, health=health)


@app.post("/api/imports/daily", response_model=ImportResult)
def api_import_daily(request: ImportRequest) -> ImportResult:
    source_path = _resolve_source_path(request.path)
    health = inspect_source(source_path, "导入数据源")
    if not health.valid:
        raise HTTPException(status_code=400, detail="数据源无效：没有找到可导入的日线文件。")

    files = iter_daily_files(source_path, request.markets)
    if request.limit_files is not None:
        files = files[: request.limit_files]
    files_imported, bars_imported, minute_bars_imported, errors = import_daily_files(
        source_path,
        files,
        request.markets,
        request.limit_files,
    )
    symbols_imported = 0
    with connect() as conn:
        apply_symbol_names(conn, load_symbol_name_map(source_path))
        symbols_imported = conn.execute("SELECT count(*) FROM symbols").fetchone()[0]
    return ImportResult(
        source_path=str(source_path),
        files_seen=len(files),
        files_imported=files_imported,
        bars_imported=bars_imported,
        minute_bars_imported=minute_bars_imported,
        symbols_imported=symbols_imported,
        errors=errors[:50],
    )


@app.get("/api/symbols")
def api_symbols(
    q: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
):
    with connect() as conn:
        return search_symbols(conn, q, limit)


@app.get("/api/bars")
def api_bars(
    symbol: str,
    timeframe: str = Query(default="D"),
    limit: int = Query(default=260, ge=1, le=2000),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    before: str | None = Query(default=None),
):
    before_query = _parse_before_query(before)
    with connect() as conn:
        return get_bars(conn, symbol.lower(), timeframe, limit, _parse_date_query(start_date), _parse_date_query(end_date), before_query)


@app.get("/api/chart", response_model=ChartDataResponse)
def api_chart_data(
    symbol: str,
    timeframe: str = Query(default="D"),
    limit: int = Query(default=260, ge=1, le=2000),
    threshold_pct: float = Query(default=5.0, ge=0.1, le=50.0),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    before: str | None = Query(default=None),
) -> ChartDataResponse:
    normalized_symbol = symbol.lower()
    normalized_timeframe = timeframe.upper()
    before_query = _parse_before_query(before)
    with connect() as conn:
        bars = get_bars(
            conn,
            normalized_symbol,
            normalized_timeframe,
            limit,
            _parse_date_query(start_date),
            _parse_date_query(end_date),
            before_query,
        )
        annotations = list_annotations(conn, normalized_symbol, normalized_timeframe)
    return ChartDataResponse(
        bars=bars,
        chan=detect_fractals(normalized_symbol, normalized_timeframe, bars),
        wave=detect_zigzag_waves(normalized_symbol, normalized_timeframe, bars, threshold_pct),
        annotations=annotations,
    )


@app.get("/api/analysis/chan", response_model=ChanAnalysisResponse)
def api_chan_analysis(
    symbol: str,
    timeframe: str = Query(default="D"),
    limit: int = Query(default=260, ge=20, le=2000),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    before: str | None = Query(default=None),
) -> ChanAnalysisResponse:
    before_query = _parse_before_query(before)
    with connect() as conn:
        bars = get_bars(conn, symbol.lower(), timeframe, limit, _parse_date_query(start_date), _parse_date_query(end_date), before_query)
    return detect_fractals(symbol.lower(), timeframe.upper(), bars)


@app.get("/api/analysis/wave", response_model=WaveAnalysisResponse)
def api_wave_analysis(
    symbol: str,
    timeframe: str = Query(default="D"),
    limit: int = Query(default=260, ge=20, le=2000),
    threshold_pct: float = Query(default=5.0, ge=0.1, le=50.0),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    before: str | None = Query(default=None),
) -> WaveAnalysisResponse:
    before_query = _parse_before_query(before)
    with connect() as conn:
        bars = get_bars(conn, symbol.lower(), timeframe, limit, _parse_date_query(start_date), _parse_date_query(end_date), before_query)
    return detect_zigzag_waves(symbol.lower(), timeframe.upper(), bars, threshold_pct)


@app.get("/api/annotations", response_model=list[AnnotationRecord])
def api_list_annotations(symbol: str, timeframe: str = Query(default="D")) -> list[AnnotationRecord]:
    with connect() as conn:
        return list_annotations(conn, symbol.lower(), timeframe.upper())


@app.post("/api/annotations", response_model=AnnotationRecord)
def api_create_annotation(request: AnnotationCreate) -> AnnotationRecord:
    with connect() as conn:
        return create_annotation(conn, request)


@app.patch("/api/annotations/{annotation_id}", response_model=AnnotationRecord)
def api_update_annotation(annotation_id: str, request: AnnotationUpdate) -> AnnotationRecord:
    with connect() as conn:
        result = update_annotation(conn, annotation_id, request)
    if result is None:
        raise HTTPException(status_code=404, detail="标注不存在。")
    return result


@app.delete("/api/annotations/{annotation_id}")
def api_delete_annotation(annotation_id: str) -> dict[str, bool]:
    with connect() as conn:
        deleted = delete_annotation(conn, annotation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="标注不存在。")
    return {"deleted": True}


@app.get("/api/rule-profiles", response_model=list[RuleProfile])
def api_list_rule_profiles(analysis_type: str | None = None) -> list[RuleProfile]:
    with connect() as conn:
        return list_rule_profiles(conn, analysis_type)


@app.post("/api/rule-profiles", response_model=RuleProfile)
def api_create_rule_profile(request: RuleProfileCreate) -> RuleProfile:
    with connect() as conn:
        return create_rule_profile(conn, request)


def _resolve_source_path(request_path: str | None) -> Path:
    if request_path:
        return Path(request_path).expanduser().resolve()
    config = load_config()
    if config.get("source_path"):
        return Path(config["source_path"]).expanduser().resolve()
    detected = [candidate for candidate in detect_sources() if candidate.valid]
    if detected:
        return Path(detected[0].path)
    raise HTTPException(status_code=400, detail="没有配置数据源，也没有自动探测到通达信数据。")


def _parse_date_query(value: str | None):
    if not value:
        return None
    from datetime import date

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"日期格式无效：{value}") from exc


def _parse_before_query(value: str | None) -> str | None:
    if not value:
        return None
    from datetime import date, datetime

    normalized = value.strip()
    try:
        if "T" in normalized or " " in normalized:
            parsed = datetime.fromisoformat(normalized.replace("T", " "))
            return parsed.isoformat(timespec="minutes")
        return date.fromisoformat(normalized).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"before 格式无效：{value}") from exc
