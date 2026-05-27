from __future__ import annotations

from datetime import datetime
import math
import re
from pathlib import Path
from threading import Lock, Thread
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .analysis import (
    MIN_BARS_FOR_BI,
    MIN_BIS_FOR_SEGMENT,
    MIN_BIS_FOR_ZHONGSHU,
    MIN_SWING_BARS,
    SEGMENT_STEP_BIS,
    STRUCTURE_BACKTEST_WAVE_STRATEGY,
    ZHONGSHU_STEP_BIS,
    build_bi_segments,
    build_line_segments,
    build_zhongshu,
    detect_fractals,
    detect_zigzag_waves,
    run_structure_backtest,
)
from .config import load_config, save_config
from .schemas import (
    AnnotationCreate,
    AnnotationRecord,
    AnnotationUpdate,
    AnalysisSchemeImportResult,
    AnalysisSchemePayload,
    AnalysisPoint,
    BacktestResponse,
    BarRecord,
    ChartDataResponse,
    ChanBiSegment,
    ChanLineSegment,
    ChanAnalysisResponse,
    ChanZhongshu,
    DataHealthResponse,
    DataSourceCandidate,
    DeleteResponse,
    HealthResponse,
    ImportJob,
    ImportRequest,
    ImportResult,
    RuleProfile,
    RuleProfileCreate,
    ReviewNoteSave,
    SourceRequest,
    SourceResponse,
    SymbolRecord,
    UserBackupImportResult,
    UserBackupPayload,
    WaveAnalysisResponse,
    WavePoint,
)
from .storage import (
    apply_symbol_names,
    connect,
    create_annotation,
    create_rule_profile,
    delete_annotation,
    export_analysis_scheme,
    export_user_backup,
    fail_inactive_import_jobs,
    get_bars,
    get_annotation_or_none,
    get_data_health,
    get_import_job,
    import_user_backup,
    import_analysis_scheme,
    import_daily_files,
    list_annotations,
    list_import_jobs,
    list_review_notes,
    list_rule_profiles,
    save_review_note,
    save_import_job,
    search_symbols,
    update_import_job,
    update_annotation,
)
from .tdx import detect_sources, inspect_source, iter_daily_files, load_symbol_name_map

app = FastAPI(title="AetherStockAnalysis API", version="0.1.0")
_VALID_TIMEFRAMES = {"D", "W", "M", "1M", "5M", "15M", "30M", "60M"}
_VALID_MARKETS = {"sh", "sz", "bj"}
_IMPORT_JOB_INTERRUPTED_REASON = "导入任务已中断，请重新发起导入。"
_ACTIVE_IMPORT_JOB_IDS: set[str] = set()
_ACTIVE_IMPORT_JOB_IDS_LOCK = Lock()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost):517\d",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/api/sources/detect", response_model=list[DataSourceCandidate])
def api_detect_sources() -> list[DataSourceCandidate]:
    return detect_sources()


@app.get("/api/sources/current", response_model=SourceResponse)
def api_current_source() -> SourceResponse:
    config = load_config()
    path = config.get("source_path")
    normalized_path = path.strip() if isinstance(path, str) else ""
    if not normalized_path:
        detected = _resolve_detected_source_candidate()
        if detected is not None:
            candidate, resolved_path = detected
            normalized_health = candidate.model_copy(update={"path": str(resolved_path)})
            return SourceResponse(path=str(resolved_path), valid=True, health=normalized_health)
        return SourceResponse(path=None, valid=False)
    resolved_path = _resolve_source_path_or_none(normalized_path)
    if resolved_path is None:
        detected = _resolve_detected_source_candidate()
        if detected is not None:
            candidate, fallback_path = detected
            normalized_health = candidate.model_copy(update={"path": str(fallback_path)})
            return SourceResponse(path=str(fallback_path), valid=True, health=normalized_health)
        return SourceResponse(path=None, valid=False)
    health = inspect_source(resolved_path, "当前数据源")
    if not health.valid:
        detected = _resolve_detected_source_candidate()
        if detected is not None:
            candidate, fallback_path = detected
            normalized_health = candidate.model_copy(update={"path": str(fallback_path)})
            return SourceResponse(path=str(fallback_path), valid=True, health=normalized_health)
    return SourceResponse(path=str(resolved_path), valid=health.valid, health=health)


@app.get("/api/data/health", response_model=DataHealthResponse)
def api_data_health() -> DataHealthResponse:
    with connect() as conn:
        return get_data_health(conn)


@app.post("/api/sources", response_model=SourceResponse)
def api_save_source(request: SourceRequest) -> SourceResponse:
    raw_path = request.path.strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="数据源路径不能为空。")
    path = _resolve_source_path_or_none(raw_path)
    if path is None:
        raise HTTPException(status_code=400, detail="数据源路径无效。")
    health = inspect_source(path, "当前数据源")
    if not health.valid:
        raise HTTPException(status_code=400, detail="数据源无效：没有找到通达信日线数据。")
    config = load_config()
    config["source_path"] = str(path)
    save_config(config)
    return SourceResponse(path=str(path), valid=True, health=health)


@app.post("/api/imports/daily", response_model=ImportResult)
def api_import_daily(request: ImportRequest) -> ImportResult:
    return _run_import(request)


@app.post("/api/imports/jobs", response_model=ImportJob)
def api_create_import_job(request: ImportRequest) -> ImportJob:
    source_path, normalized_markets, _files = _prepare_import(request)
    normalized_request = request.model_copy(update={"path": str(source_path), "markets": normalized_markets})
    job = ImportJob(
        id=uuid4().hex,
        status="queued",
        source_path=normalized_request.path,
        source_path_exists=source_path.exists(),
        message="导入任务已排队。",
    )
    _mark_import_job_active(job.id)
    _save_import_job(job)
    Thread(target=_run_import_job, args=(job.id, normalized_request), daemon=True).start()
    return job


@app.get("/api/imports/jobs/{job_id}", response_model=ImportJob)
def api_get_import_job(job_id: str) -> ImportJob:
    job = _get_import_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="导入任务不存在。")
    return job


@app.get("/api/imports/jobs", response_model=list[ImportJob])
def api_list_import_jobs(
    limit: int = Query(default=20, ge=1, le=200),
    status: Literal["pending", "queued", "running", "succeeded", "failed"] | None = Query(default=None),
    source_path_exists: bool | None = Query(default=None),
) -> list[ImportJob]:
    with connect() as conn:
        _reconcile_inactive_import_jobs(conn)
        return list_import_jobs(conn, limit, status, source_path_exists)


@app.get("/api/symbols", response_model=list[SymbolRecord])
def api_symbols(
    q: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SymbolRecord]:
    with connect() as conn:
        return search_symbols(conn, q, limit)


@app.get("/api/bars", response_model=list[BarRecord])
def api_bars(
    symbol: str,
    timeframe: str = Query(default="D"),
    limit: int = Query(default=260, ge=1, le=2000),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    before: str | None = Query(default=None),
) -> list[BarRecord]:
    normalized_symbol = _normalize_symbol_query(symbol)
    normalized_timeframe = _normalize_timeframe_query(timeframe)
    before_query = _parse_before_query(before)
    with connect() as conn:
        return get_bars(
            conn,
            normalized_symbol,
            normalized_timeframe,
            limit,
            _parse_date_query(start_date),
            _parse_date_query(end_date),
            before_query,
        )


@app.get("/api/chart", response_model=ChartDataResponse)
def api_chart_data(
    symbol: str,
    timeframe: str = Query(default="D"),
    limit: int = Query(default=260, ge=1, le=2000),
    threshold_pct: float | None = Query(default=None, ge=0.1, le=50.0),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    before: str | None = Query(default=None),
) -> ChartDataResponse:
    normalized_symbol = _normalize_symbol_query(symbol)
    normalized_timeframe = _normalize_timeframe_query(timeframe)
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
        chan_params = _chan_rule_params(conn)
        wave_params = _wave_rule_params(conn, threshold_pct)
    _manual_chan_annotation, manual_chan_analysis = _resolve_manual_chan_analysis(
        normalized_symbol, normalized_timeframe, annotations
    )
    _manual_wave_annotation, manual_wave_analysis = _resolve_manual_wave_analysis(
        normalized_symbol,
        normalized_timeframe,
        annotations,
        wave_params["threshold_pct"],
    )
    return ChartDataResponse(
        bars=bars,
        chan=manual_chan_analysis or detect_fractals(normalized_symbol, normalized_timeframe, bars, **chan_params),
        wave=manual_wave_analysis or detect_zigzag_waves(normalized_symbol, normalized_timeframe, bars, **wave_params),
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
    normalized_symbol = _normalize_symbol_query(symbol)
    normalized_timeframe = _normalize_timeframe_query(timeframe)
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
        chan_params = _chan_rule_params(conn)
    _manual_chan_annotation, manual_chan_analysis = _resolve_manual_chan_analysis(
        normalized_symbol, normalized_timeframe, annotations
    )
    return manual_chan_analysis or detect_fractals(normalized_symbol, normalized_timeframe, bars, **chan_params)


@app.get("/api/analysis/wave", response_model=WaveAnalysisResponse)
def api_wave_analysis(
    symbol: str,
    timeframe: str = Query(default="D"),
    limit: int = Query(default=260, ge=20, le=2000),
    threshold_pct: float | None = Query(default=None, ge=0.1, le=50.0),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    before: str | None = Query(default=None),
) -> WaveAnalysisResponse:
    normalized_symbol = _normalize_symbol_query(symbol)
    normalized_timeframe = _normalize_timeframe_query(timeframe)
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
        wave_params = _wave_rule_params(conn, threshold_pct)
    _manual_wave_annotation, manual_wave_analysis = _resolve_manual_wave_analysis(
        normalized_symbol,
        normalized_timeframe,
        annotations,
        wave_params["threshold_pct"],
    )
    return manual_wave_analysis or detect_zigzag_waves(normalized_symbol, normalized_timeframe, bars, **wave_params)


@app.get("/api/backtests/structure", response_model=BacktestResponse)
def api_structure_backtest(
    symbol: str,
    timeframe: str = Query(default="D"),
    limit: int = Query(default=520, ge=20, le=2000),
    strategy: str = Query(default="chan_fractal_reversal"),
    threshold_pct: float | None = Query(default=None, ge=0.1, le=50.0),
    fee_bps: float = Query(default=0.0, ge=0.0, le=1000.0),
    slippage_bps: float = Query(default=0.0, ge=0.0, le=1000.0),
    position_pct: float = Query(default=100.0, ge=0.0, le=100.0),
    apply_limit_constraints: bool = Query(default=False),
    limit_pct: float = Query(default=10.0, ge=0.1, le=30.0),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    before: str | None = Query(default=None),
) -> BacktestResponse:
    before_query = _parse_before_query(before)
    normalized_symbol = _normalize_symbol_query(symbol)
    normalized_timeframe = _normalize_timeframe_query(timeframe)
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
        chan_params = _chan_rule_params(conn)
        wave_params = _wave_rule_params(conn, threshold_pct)
    manual_chan_annotation, manual_analysis = _resolve_manual_chan_analysis(
        normalized_symbol, normalized_timeframe, annotations
    )
    manual_wave_annotation, manual_wave_analysis = _resolve_manual_wave_analysis(
        normalized_symbol,
        normalized_timeframe,
        annotations,
        wave_params["threshold_pct"],
    )
    uses_wave_strategy = strategy == STRUCTURE_BACKTEST_WAVE_STRATEGY
    manual_annotation = manual_wave_annotation if uses_wave_strategy else manual_chan_annotation
    manual_source = manual_wave_analysis if uses_wave_strategy else manual_analysis
    auto_analysis = None if uses_wave_strategy else manual_analysis or detect_fractals(normalized_symbol, normalized_timeframe, bars, **chan_params)
    try:
        return run_structure_backtest(
            normalized_symbol,
            normalized_timeframe,
            bars,
            strategy,
            analysis=auto_analysis,
            wave_analysis=manual_wave_analysis,
            structure_source="manual" if manual_source else "auto",
            manual_annotation_id=manual_annotation.id if manual_source and manual_annotation else None,
            wave_threshold_pct=wave_params["threshold_pct"],
            wave_min_swing_bars=wave_params["min_swing_bars"],
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            position_pct=position_pct,
            apply_limit_constraints=apply_limit_constraints,
            limit_pct=limit_pct,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/annotations", response_model=list[AnnotationRecord])
def api_list_annotations(symbol: str, timeframe: str = Query(default="D")) -> list[AnnotationRecord]:
    normalized_symbol = _normalize_symbol_query(symbol)
    normalized_timeframe = _normalize_timeframe_query(timeframe)
    with connect() as conn:
        return list_annotations(conn, normalized_symbol, normalized_timeframe)


@app.post("/api/annotations", response_model=AnnotationRecord)
def api_create_annotation(request: AnnotationCreate) -> AnnotationRecord:
    normalized_symbol = _normalize_symbol_query(request.symbol)
    normalized_timeframe = _normalize_timeframe_query(request.timeframe)
    normalized_overlay_type = _normalize_overlay_type_query(request.overlay_type)
    normalized_request = AnnotationCreate(
        symbol=normalized_symbol,
        timeframe=normalized_timeframe,
        overlay_type=normalized_overlay_type,
        payload=request.payload,
    )
    try:
        with connect() as conn:
            return create_annotation(conn, normalized_request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/annotations/{annotation_id}", response_model=AnnotationRecord)
def api_update_annotation(annotation_id: str, request: AnnotationUpdate) -> AnnotationRecord:
    normalized_overlay_type = (
        _normalize_overlay_type_query(request.overlay_type) if request.overlay_type is not None else None
    )
    normalized_request = AnnotationUpdate(
        overlay_type=normalized_overlay_type,
        payload=request.payload,
    )
    try:
        with connect() as conn:
            result = update_annotation(conn, annotation_id, normalized_request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="标注不存在。")
    return result


@app.delete("/api/annotations/{annotation_id}", response_model=DeleteResponse)
def api_delete_annotation(annotation_id: str) -> DeleteResponse:
    with connect() as conn:
        annotation = get_annotation_or_none(conn, annotation_id)
        if annotation is None:
            raise HTTPException(status_code=404, detail="标注不存在。")
        if annotation.payload.get("locked") is True:
            raise HTTPException(status_code=409, detail="标注已锁定，请先解锁后再删除。")
        deleted = delete_annotation(conn, annotation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="标注不存在。")
    return DeleteResponse(deleted=True)


@app.get("/api/review-notes", response_model=list[AnnotationRecord])
def api_list_review_notes(symbol: str, timeframe: str = Query(default="D")) -> list[AnnotationRecord]:
    normalized_symbol = _normalize_symbol_query(symbol)
    normalized_timeframe = _normalize_timeframe_query(timeframe)
    with connect() as conn:
        return list_review_notes(conn, normalized_symbol, normalized_timeframe)


@app.post("/api/review-notes", response_model=AnnotationRecord)
def api_save_review_note(request: ReviewNoteSave) -> AnnotationRecord:
    normalized_symbol = _normalize_symbol_query(request.symbol)
    normalized_timeframe = _normalize_timeframe_query(request.timeframe)
    normalized_request = ReviewNoteSave(
        symbol=normalized_symbol,
        timeframe=normalized_timeframe,
        content=request.content,
        title=request.title,
        tags=request.tags,
        payload=request.payload,
    )
    try:
        with connect() as conn:
            return save_review_note(conn, normalized_request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/rule-profiles", response_model=list[RuleProfile])
def api_list_rule_profiles(analysis_type: Literal["chan", "wave"] | None = None) -> list[RuleProfile]:
    with connect() as conn:
        return list_rule_profiles(conn, analysis_type)


@app.post("/api/rule-profiles", response_model=RuleProfile)
def api_create_rule_profile(request: RuleProfileCreate) -> RuleProfile:
    with connect() as conn:
        return create_rule_profile(conn, request)


@app.get("/api/backups/user", response_model=UserBackupPayload)
def api_export_user_backup() -> UserBackupPayload:
    exportable_config = _portable_user_config(load_config())
    with connect() as conn:
        return export_user_backup(conn, exportable_config)


@app.post("/api/backups/user", response_model=UserBackupImportResult)
def api_import_user_backup(payload: UserBackupPayload) -> UserBackupImportResult:
    if payload.schema_version != 1:
        raise HTTPException(status_code=400, detail="不支持的备份文件版本。")
    try:
        with connect() as conn:
            result = import_user_backup(conn, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    imported_config = _portable_user_config(payload.config)
    if imported_config:
        save_config(imported_config)
    result.config_imported = bool(imported_config)
    return result


@app.get("/api/schemes/analysis", response_model=AnalysisSchemePayload)
def api_export_analysis_scheme(
    name: str = Query(default="AetherStock 分析方案"),
    description: str = Query(default=""),
) -> AnalysisSchemePayload:
    with connect() as conn:
        return export_analysis_scheme(conn, name=name, description=description)


@app.post("/api/schemes/analysis", response_model=AnalysisSchemeImportResult)
def api_import_analysis_scheme(payload: AnalysisSchemePayload) -> AnalysisSchemeImportResult:
    if payload.schema_version != 1:
        raise HTTPException(status_code=400, detail="不支持的分析方案版本。")
    try:
        with connect() as conn:
            return import_analysis_scheme(conn, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _default_rule_profile(conn, analysis_type: str) -> RuleProfile | None:
    profiles = list_rule_profiles(conn, analysis_type)
    return profiles[0] if profiles else None


def _chan_rule_params(conn) -> dict:
    profile = _default_rule_profile(conn, "chan")
    if profile is None:
        return {}
    params = profile.params
    return {
        "strict_fractal": _bool_param(params, "strict_fractal", False),
        "include_containment": _bool_param(params, "include_containment", True),
        "min_bars_for_bi": params.get("min_bars_for_bi", 5),
        "min_bis_for_segment": params.get("min_bis_for_segment", 3),
        "segment_step_bis": params.get("segment_step_bis", 3),
        "min_bis_for_zhongshu": params.get("min_bis_for_zhongshu", 3),
        "zhongshu_step_bis": params.get("zhongshu_step_bis", 1),
    }


def _wave_rule_params(conn, explicit_threshold_pct: float | None) -> dict:
    profile = _default_rule_profile(conn, "wave")
    params = profile.params if profile is not None else {}
    threshold_pct = params.get("threshold_pct", params.get("zigzag_threshold_pct", 5.0))
    if explicit_threshold_pct is not None:
        threshold_pct = explicit_threshold_pct
    if not isinstance(threshold_pct, (int, float)):
        threshold_pct = 5.0
    return {
        "threshold_pct": min(max(float(threshold_pct), 0.1), 50.0),
        "min_swing_bars": _positive_int_param(params.get("min_swing_bars"), MIN_SWING_BARS),
    }


def _bool_param(params: dict, key: str, fallback: bool) -> bool:
    value = params.get(key, fallback)
    return value if isinstance(value, bool) else fallback


def _run_import(request: ImportRequest, progress=None) -> ImportResult:
    source_path, normalized_markets, files = _prepare_import(request)
    files_imported, bars_imported, minute_files_seen, minute_files_imported, minute_bars_imported, errors = import_daily_files(
        source_path,
        files,
        normalized_markets,
        request.limit_files,
        progress,
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
        minute_files_seen=minute_files_seen,
        minute_files_imported=minute_files_imported,
        minute_bars_imported=minute_bars_imported,
        symbols_imported=symbols_imported,
        errors=errors[:50],
    )


def _prepare_import(request: ImportRequest) -> tuple[Path, list[str], list[Path]]:
    source_path = _resolve_source_path(request.path)
    normalized_markets = _normalize_market_query(request.markets)
    health = inspect_source(source_path, "导入数据源")
    if not health.valid:
        raise HTTPException(status_code=400, detail="数据源无效：没有找到可导入的日线文件。")

    files = iter_daily_files(source_path, normalized_markets)
    if request.limit_files is not None:
        files = files[: request.limit_files]
    return source_path, normalized_markets, files


def _run_import_job(job_id: str, request: ImportRequest) -> None:
    try:
        _update_import_job(
            job_id,
            status="running",
            started_at=datetime.now(),
            message="导入任务正在运行。",
        )
        try:
            source_path, _normalized_markets, files = _prepare_import(request)
            _update_import_job(
                job_id,
                source_path=str(source_path),
                files_seen=len(files),
                message=f"正在导入 {len(files)} 个日线文件，并同步已下载的分钟线。",
            )
            result = _run_import(request, lambda changes: _update_import_job(job_id, **changes))
        except HTTPException as exc:
            _update_import_job(
                job_id,
                status="failed",
                errors=[str(exc.detail)],
                message=str(exc.detail),
                finished_at=datetime.now(),
            )
            return
        except Exception as exc:  # noqa: BLE001
            _update_import_job(
                job_id,
                status="failed",
                errors=[str(exc)],
                message="导入任务失败。",
                finished_at=datetime.now(),
            )
            return

        _update_import_job(
            job_id,
            status="succeeded",
            source_path=result.source_path,
            files_seen=result.files_seen,
            files_imported=result.files_imported,
            bars_imported=result.bars_imported,
            minute_files_seen=result.minute_files_seen,
            minute_files_imported=result.minute_files_imported,
            minute_bars_imported=result.minute_bars_imported,
            symbols_imported=result.symbols_imported,
            errors=result.errors,
            message="导入任务已完成。",
            finished_at=datetime.now(),
        )
    finally:
        _mark_import_job_inactive(job_id)


def _save_import_job(job: ImportJob) -> None:
    with connect() as conn:
        save_import_job(conn, job)


def _get_import_job(job_id: str) -> ImportJob | None:
    with connect() as conn:
        _reconcile_inactive_import_jobs(conn)
        return get_import_job(conn, job_id)


def _update_import_job(job_id: str, **changes) -> None:
    with connect() as conn:
        update_import_job(conn, job_id, **changes)


def _mark_import_job_active(job_id: str) -> None:
    with _ACTIVE_IMPORT_JOB_IDS_LOCK:
        _ACTIVE_IMPORT_JOB_IDS.add(job_id)


def _mark_import_job_inactive(job_id: str) -> None:
    with _ACTIVE_IMPORT_JOB_IDS_LOCK:
        _ACTIVE_IMPORT_JOB_IDS.discard(job_id)


def _active_import_job_ids_snapshot() -> set[str]:
    with _ACTIVE_IMPORT_JOB_IDS_LOCK:
        return set(_ACTIVE_IMPORT_JOB_IDS)


def _reconcile_inactive_import_jobs(conn) -> None:
    fail_inactive_import_jobs(conn, _active_import_job_ids_snapshot(), _IMPORT_JOB_INTERRUPTED_REASON)


def _resolve_manual_chan_analysis(
    symbol: str,
    timeframe: str,
    annotations: list[AnnotationRecord],
) -> tuple[AnnotationRecord | None, ChanAnalysisResponse | None]:
    for annotation in annotations:
        if (
            annotation.overlay_type != "chan"
            or annotation.payload.get("active") is False
            or not (
                isinstance(annotation.payload.get("fractals"), list)
                or isinstance(annotation.payload.get("bis"), list)
                or isinstance(annotation.payload.get("segments"), list)
                or isinstance(annotation.payload.get("zhongshu"), list)
            )
        ):
            continue
        manual_analysis = _manual_chan_analysis(symbol, timeframe, annotation)
        if manual_analysis is not None:
            return annotation, manual_analysis
    return None, None


def _resolve_manual_wave_analysis(
    symbol: str,
    timeframe: str,
    annotations: list[AnnotationRecord],
    fallback_threshold_pct: float,
) -> tuple[AnnotationRecord | None, WaveAnalysisResponse | None]:
    for annotation in annotations:
        if (
            annotation.overlay_type != "wave"
            or annotation.payload.get("active") is False
            or not isinstance(annotation.payload.get("pivots"), list)
        ):
            continue
        manual_analysis = _manual_wave_analysis(symbol, timeframe, annotation, fallback_threshold_pct)
        if manual_analysis is not None:
            return annotation, manual_analysis
    return None, None


def _manual_chan_analysis(
    symbol: str,
    timeframe: str,
    annotation: AnnotationRecord | None,
) -> ChanAnalysisResponse | None:
    if annotation is None:
        return None
    fractals = _parse_analysis_points(annotation.payload.get("fractals"))
    bis = _parse_chan_bis(annotation.payload.get("bis"))
    segments = _parse_chan_segments(annotation.payload.get("segments"))
    zhongshu = _parse_chan_zhongshu(annotation.payload.get("zhongshu"))
    params = annotation.payload.get("params")
    params = params if isinstance(params, dict) else {}
    derived_from_fractals = False
    if fractals and not bis:
        min_bars_for_bi = _positive_int_param(params.get("min_bars_for_bi"), MIN_BARS_FOR_BI)
        bis = build_bi_segments(fractals, min_bars_for_bi)
        derived_from_fractals = bool(bis)
    if bis and not segments:
        min_bis_for_segment = _positive_int_param(params.get("min_bis_for_segment"), MIN_BIS_FOR_SEGMENT)
        segment_step_bis = _positive_int_param(params.get("segment_step_bis"), SEGMENT_STEP_BIS)
        segments = build_line_segments(bis, min_bis_for_segment, segment_step_bis)
    if bis and not zhongshu:
        min_bis_for_zhongshu = _positive_int_param(params.get("min_bis_for_zhongshu"), MIN_BIS_FOR_ZHONGSHU)
        zhongshu_step_bis = _positive_int_param(params.get("zhongshu_step_bis"), ZHONGSHU_STEP_BIS)
        zhongshu = build_zhongshu(bis, min_bis_for_zhongshu, zhongshu_step_bis)
    if not fractals and not bis and not segments and not zhongshu:
        return None
    version = annotation.payload.get("chan_version")
    response_params = {**params}
    if derived_from_fractals:
        response_params["derived_from_manual_fractals"] = True
    return ChanAnalysisResponse(
        symbol=symbol,
        timeframe=timeframe,
        algorithm="manual-chan",
        version=version if isinstance(version, str) else "manual",
        params=response_params,
        generated_at=annotation.updated_at,
        fractals=fractals,
        bis=bis,
        segments=segments,
        zhongshu=zhongshu,
    )


def _positive_int_param(value, fallback: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return fallback
    return normalized if normalized >= 1 else fallback


def _manual_wave_analysis(
    symbol: str,
    timeframe: str,
    annotation: AnnotationRecord | None,
    fallback_threshold_pct: float,
) -> WaveAnalysisResponse | None:
    if annotation is None:
        return None
    pivots = _parse_wave_points(annotation.payload.get("pivots"))
    if not pivots:
        return None
    version = annotation.payload.get("wave_version")
    params = annotation.payload.get("params")
    threshold_pct = _coerce_float_param(annotation.payload.get("threshold_pct"))
    normalized_threshold_pct = (
        min(max(threshold_pct, 0.1), 50.0) if threshold_pct is not None else fallback_threshold_pct
    )
    return WaveAnalysisResponse(
        symbol=symbol,
        timeframe=timeframe,
        algorithm="manual-wave",
        version=version if isinstance(version, str) else "manual",
        params=params if isinstance(params, dict) else {"source": "manual"},
        generated_at=annotation.updated_at,
        threshold_pct=normalized_threshold_pct,
        pivots=pivots,
    )


def _parse_analysis_points(value) -> list[AnalysisPoint]:
    if not isinstance(value, list):
        return []
    points: list[AnalysisPoint] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        index = _coerce_int_param(item.get("index"))
        trade_date = _normalize_manual_trade_date(item.get("trade_date"))
        price = _coerce_float_param(item.get("price"))
        kind = _normalize_turn_kind(item.get("kind"))
        if index is not None and trade_date is not None and price is not None and kind is not None:
            points.append(AnalysisPoint(index=index, trade_date=trade_date, price=price, kind=kind))
    return points


def _parse_wave_points(value) -> list[WavePoint]:
    if not isinstance(value, list):
        return []
    points: list[WavePoint] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        index = _coerce_int_param(item.get("index"))
        trade_date = _normalize_manual_trade_date(item.get("trade_date"))
        price = _coerce_float_param(item.get("price"))
        kind = _normalize_wave_kind(item.get("kind"))
        wave_no = _coerce_int_param(item.get("wave_no"))
        if (
            index is None
            or trade_date is None
            or price is None
            or kind is None
            or wave_no is None
            or wave_no < 1
        ):
            continue
        points.append(WavePoint(index=index, trade_date=trade_date, price=price, kind=kind, wave_no=wave_no))
    return points


def _normalize_manual_trade_date(value) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        from datetime import date, datetime

        return date.fromisoformat(normalized).isoformat()
    except ValueError:
        pass
    datetime_candidate = normalized
    if datetime_candidate.endswith("Z") or datetime_candidate.endswith("z"):
        datetime_candidate = f"{datetime_candidate[:-1]}+00:00"
    # Accept offsets without colon suffix, e.g. +0800 / -0530.
    datetime_candidate = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", datetime_candidate)
    # Accept hour-only offsets, e.g. +08 / -05.
    datetime_candidate = re.sub(r"([+-]\d{2})$", r"\1:00", datetime_candidate)
    try:
        parsed = datetime.fromisoformat(datetime_candidate.replace("T", " "))
    except ValueError:
        return None
    return parsed.isoformat(timespec="minutes")


def _coerce_float_param(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            numeric = float(normalized)
        except ValueError:
            return None
        return numeric if math.isfinite(numeric) else None
    return None


def _coerce_int_param(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        if value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            numeric = float(normalized)
        except ValueError:
            return None
        if not math.isfinite(numeric):
            return None
        if numeric.is_integer():
            return int(numeric)
        return None
    return None


def _normalize_wave_kind(value) -> Literal["start", "top", "bottom"] | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized == "start":
        return "start"
    if normalized in {"top", "high"}:
        return "top"
    if normalized in {"bottom", "low"}:
        return "bottom"
    return None


def _normalize_turn_kind(value) -> Literal["top", "bottom"] | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"top", "high"}:
        return "top"
    if normalized in {"bottom", "low"}:
        return "bottom"
    return None


def _parse_chan_bis(value) -> list[ChanBiSegment]:
    if not isinstance(value, list):
        return []
    bis: list[ChanBiSegment] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            bis.append(ChanBiSegment(**item))
        except Exception:
            continue
    return bis


def _parse_chan_segments(value) -> list[ChanLineSegment]:
    if not isinstance(value, list):
        return []
    segments: list[ChanLineSegment] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            segments.append(ChanLineSegment(**item))
        except Exception:
            continue
    return segments


def _parse_chan_zhongshu(value) -> list[ChanZhongshu]:
    if not isinstance(value, list):
        return []
    zones: list[ChanZhongshu] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            zones.append(ChanZhongshu(**item))
        except Exception:
            continue
    return zones


def _resolve_source_path(request_path: str | None) -> Path:
    if request_path is not None:
        normalized_request_path = request_path.strip()
        if not normalized_request_path:
            raise HTTPException(status_code=400, detail="数据源路径不能为空。")
        resolved_request_path = _resolve_source_path_or_none(normalized_request_path)
        if resolved_request_path is None:
            raise HTTPException(status_code=400, detail="数据源路径无效。")
        return resolved_request_path
    config = load_config()
    config_source_path = config.get("source_path")
    if isinstance(config_source_path, str) and config_source_path.strip():
        resolved_config_path = _resolve_source_path_or_none(config_source_path)
        if resolved_config_path is not None:
            config_health = inspect_source(resolved_config_path, "配置数据源")
            if config_health.valid:
                return resolved_config_path
    detected = _resolve_detected_source_candidate()
    if detected is not None:
        _candidate, resolved_path = detected
        return resolved_path
    raise HTTPException(status_code=400, detail="没有配置数据源，也没有自动探测到通达信数据。")


def _resolve_detected_source_candidate() -> tuple[DataSourceCandidate, Path] | None:
    for candidate in detect_sources():
        if candidate.valid is not True or candidate.exists is not True:
            continue
        raw_path = candidate.path.strip() if isinstance(candidate.path, str) else ""
        if not raw_path:
            continue
        resolved_path = _resolve_source_path_or_none(raw_path)
        if resolved_path is None:
            continue
        # Re-validate detected candidates against the current filesystem state
        # in case stale probe results report exists/valid incorrectly.
        health = inspect_source(resolved_path, candidate.label)
        if health.valid is not True:
            continue
        return health, resolved_path
    return None


def _resolve_source_path_or_none(raw_path: str) -> Path | None:
    normalized = raw_path.strip()
    if not normalized:
        return None
    try:
        return Path(normalized).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _portable_user_config(value: dict) -> dict:
    source_path = value.get("source_path")
    if isinstance(source_path, str):
        normalized_source_path = _normalize_portable_source_path(source_path)
        if normalized_source_path is not None:
            return {"source_path": normalized_source_path}
    return {}


def _normalize_portable_source_path(source_path: str) -> str | None:
    normalized = source_path.strip()
    if not normalized:
        return None
    try:
        return str(Path(normalized).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):
        return None


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


def _normalize_timeframe_query(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in _VALID_TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"timeframe 不支持：{value}")
    return normalized


def _normalize_symbol_query(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="symbol 不能为空。")
    return normalized


def _normalize_overlay_type_query(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="overlay_type 不能为空。")
    return normalized


def _normalize_market_query(values: list[str]) -> list[str]:
    normalized_values: list[str] = []
    seen_values: set[str] = set()
    invalid_values: list[str] = []
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized not in _VALID_MARKETS:
            invalid_values.append(value)
            continue
        if normalized in seen_values:
            continue
        seen_values.add(normalized)
        normalized_values.append(normalized)
    if invalid_values:
        invalid = ", ".join(repr(value) for value in invalid_values)
        raise HTTPException(status_code=400, detail=f"markets 参数不支持：{invalid}")
    if not normalized_values:
        raise HTTPException(status_code=400, detail="markets 不能为空。")
    return normalized_values
