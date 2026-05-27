from __future__ import annotations

import csv
import json
import tempfile
import threading
import uuid
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from . import config
from .schemas import (
    AnnotationCreate,
    AnnotationRecord,
    AnnotationUpdate,
    AnalysisSchemeImportResult,
    AnalysisSchemePayload,
    BarRecord,
    DataHealthResponse,
    DataRecommendation,
    ImportJob,
    MarketCoverage,
    RuleProfile,
    RuleProfileCreate,
    ReviewNoteSave,
    SymbolRecord,
    TimeframeCoverage,
    UserBackupImportResult,
    UserBackupPayload,
)


_init_lock = threading.Lock()
_initialized_db_path: Path | None = None
_VALID_TIMEFRAMES = {"D", "W", "M", "1M", "5M", "15M", "30M", "60M"}
IMPORT_JOBS_RETENTION = 200


def connect() -> duckdb.DuckDBPyConnection:
    global _initialized_db_path

    config.ensure_app_dir()
    db_path = config.DB_PATH
    conn = duckdb.connect(str(db_path))
    conn.execute("PRAGMA threads=4")
    if _initialized_db_path != db_path:
        with _init_lock:
            if _initialized_db_path != db_path:
                init_db(conn)
                _initialized_db_path = db_path
    return conn


def init_db(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS symbols (
            symbol TEXT NOT NULL,
            market TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            first_date DATE,
            last_date DATE,
            bar_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    migrate_symbols_primary_key(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bars_daily (
            symbol TEXT NOT NULL,
            market TEXT NOT NULL,
            code TEXT NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE NOT NULL,
            high DOUBLE NOT NULL,
            low DOUBLE NOT NULL,
            close DOUBLE NOT NULL,
            amount DOUBLE NOT NULL,
            volume BIGINT NOT NULL
        )
        """
    )
    migrate_bars_daily_primary_key(conn)
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS bars_daily_symbol_date_idx
        ON bars_daily(symbol, trade_date)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bars_minute (
            symbol TEXT NOT NULL,
            market TEXT NOT NULL,
            code TEXT NOT NULL,
            trade_time TIMESTAMP NOT NULL,
            interval_minutes INTEGER NOT NULL,
            open DOUBLE NOT NULL,
            high DOUBLE NOT NULL,
            low DOUBLE NOT NULL,
            close DOUBLE NOT NULL,
            amount DOUBLE NOT NULL,
            volume BIGINT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS bars_minute_symbol_interval_time_idx
        ON bars_minute(symbol, interval_minutes, trade_time)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS symbols_symbol_idx
        ON symbols(symbol)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS annotations (
            id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            overlay_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        )
        """
    )
    migrate_annotations_schema(conn)
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS annotations_symbol_timeframe_idx
        ON annotations(symbol, timeframe)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rule_profiles (
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            analysis_type TEXT NOT NULL,
            version TEXT NOT NULL,
            params TEXT NOT NULL,
            is_default BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS rule_profiles_type_idx
        ON rule_profiles(analysis_type)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS import_jobs (
            id TEXT NOT NULL,
            status TEXT NOT NULL,
            source_path TEXT,
            files_seen INTEGER NOT NULL DEFAULT 0,
            files_imported INTEGER NOT NULL DEFAULT 0,
            bars_imported INTEGER NOT NULL DEFAULT 0,
            minute_files_seen INTEGER NOT NULL DEFAULT 0,
            minute_files_imported INTEGER NOT NULL DEFAULT 0,
            minute_bars_imported INTEGER NOT NULL DEFAULT 0,
            symbols_imported INTEGER NOT NULL DEFAULT 0,
            errors TEXT NOT NULL DEFAULT '[]',
            message TEXT,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS import_jobs_id_idx
        ON import_jobs(id)
        """
    )
    seed_default_profiles(conn)


def migrate_bars_daily_primary_key(conn: duckdb.DuckDBPyConnection) -> None:
    constraints = conn.execute(
        """
        SELECT count(*)
        FROM duckdb_constraints()
        WHERE table_name = 'bars_daily'
          AND constraint_type = 'PRIMARY KEY'
        """
    ).fetchone()[0]
    if constraints == 0:
        return

    conn.execute("ALTER TABLE bars_daily RENAME TO bars_daily_with_pk")
    conn.execute(
        """
        CREATE TABLE bars_daily (
            symbol TEXT NOT NULL,
            market TEXT NOT NULL,
            code TEXT NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE NOT NULL,
            high DOUBLE NOT NULL,
            low DOUBLE NOT NULL,
            close DOUBLE NOT NULL,
            amount DOUBLE NOT NULL,
            volume BIGINT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO bars_daily
        (symbol, market, code, trade_date, open, high, low, close, amount, volume)
        SELECT
            symbol,
            any_value(market) AS market,
            any_value(code) AS code,
            trade_date,
            any_value(open) AS open,
            any_value(high) AS high,
            any_value(low) AS low,
            any_value(close) AS close,
            any_value(amount) AS amount,
            any_value(volume) AS volume
        FROM bars_daily_with_pk
        GROUP BY symbol, trade_date
        """
    )
    conn.execute("DROP TABLE bars_daily_with_pk")


def migrate_symbols_primary_key(conn: duckdb.DuckDBPyConnection) -> None:
    constraints = conn.execute(
        """
        SELECT count(*)
        FROM duckdb_constraints()
        WHERE table_name = 'symbols'
          AND constraint_type = 'PRIMARY KEY'
        """
    ).fetchone()[0]
    if constraints == 0:
        return

    conn.execute("ALTER TABLE symbols RENAME TO symbols_with_pk")
    conn.execute(
        """
        CREATE TABLE symbols (
            symbol TEXT NOT NULL,
            market TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            first_date DATE,
            last_date DATE,
            bar_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO symbols
        (symbol, market, code, name, kind, first_date, last_date, bar_count)
        SELECT
            symbol,
            any_value(market) AS market,
            any_value(code) AS code,
            any_value(name) AS name,
            any_value(kind) AS kind,
            min(first_date) AS first_date,
            max(last_date) AS last_date,
            max(bar_count) AS bar_count
        FROM symbols_with_pk
        GROUP BY symbol
        """
    )
    conn.execute("DROP TABLE symbols_with_pk")


def migrate_annotations_schema(conn: duckdb.DuckDBPyConnection) -> None:
    columns = conn.execute("DESCRIBE annotations").fetchall()
    id_type = next((row[1] for row in columns if row[0] == "id"), "")
    payload_type = next((row[1] for row in columns if row[0] == "payload"), "")
    has_primary_key = conn.execute(
        """
        SELECT count(*)
        FROM duckdb_constraints()
        WHERE table_name = 'annotations'
          AND constraint_type = 'PRIMARY KEY'
        """
    ).fetchone()[0] > 0
    if id_type.upper() == "VARCHAR" and payload_type.upper() == "VARCHAR" and not has_primary_key:
        return

    existing_rows = conn.execute(
        """
        SELECT
            id::TEXT AS id,
            symbol,
            timeframe,
            overlay_type,
            payload::TEXT AS payload,
            created_at,
            updated_at
        FROM annotations
        """
    ).fetchall()
    conn.execute("DROP TABLE annotations")
    conn.execute(
        """
        CREATE TABLE annotations (
            id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            overlay_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        )
        """
    )
    if existing_rows:
        conn.executemany(
            """
            INSERT INTO annotations
            (id, symbol, timeframe, overlay_type, payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            existing_rows,
        )


def refresh_symbols(conn: duckdb.DuckDBPyConnection) -> int:
    conn.execute("DELETE FROM symbols")
    conn.execute(
        """
        INSERT INTO symbols (symbol, market, code, name, kind, first_date, last_date, bar_count)
        SELECT
            symbol,
            any_value(market) AS market,
            any_value(code) AS code,
            upper(symbol) AS name,
            CASE
                WHEN any_value(market) = 'sh' AND any_value(code) LIKE '000%' THEN 'index'
                WHEN any_value(market) = 'sz' AND any_value(code) LIKE '399%' THEN 'index'
                WHEN any_value(code) LIKE '510%' OR any_value(code) LIKE '511%'
                    OR any_value(code) LIKE '512%' OR any_value(code) LIKE '513%'
                    OR any_value(code) LIKE '515%' OR any_value(code) LIKE '516%'
                    OR any_value(code) LIKE '517%' OR any_value(code) LIKE '518%'
                    OR any_value(code) LIKE '159%' THEN 'etf'
                ELSE 'stock'
            END AS kind,
            min(trade_date) AS first_date,
            max(trade_date) AS last_date,
            count(*) AS bar_count
        FROM bars_daily
        GROUP BY symbol
        """
    )
    return conn.execute("SELECT count(*) FROM symbols").fetchone()[0]


def apply_symbol_names(conn: duckdb.DuckDBPyConnection, names: dict[str, str]) -> int:
    if not names:
        return 0
    rows = [(symbol, name) for symbol, name in names.items() if name]
    if not rows:
        return 0

    conn.execute("CREATE TEMP TABLE symbol_name_import (symbol TEXT, name TEXT)")
    conn.executemany("INSERT INTO symbol_name_import VALUES (?, ?)", rows)
    conn.execute(
        """
        UPDATE symbols
        SET name = symbol_name_import.name
        FROM symbol_name_import
        WHERE symbols.symbol = symbol_name_import.symbol
        """
    )
    updated = conn.execute(
        """
        SELECT count(*)
        FROM symbols
        JOIN symbol_name_import USING (symbol)
        """
    ).fetchone()[0]
    conn.execute("DROP TABLE symbol_name_import")
    return updated


def search_symbols(conn: duckdb.DuckDBPyConnection, query: str = "", limit: int = 50) -> list[SymbolRecord]:
    pattern = f"%{query.lower()}%"
    rows = conn.execute(
        """
        SELECT symbol, market, code, name, kind, first_date, last_date, bar_count
        FROM symbols
        WHERE lower(symbol) LIKE ? OR lower(code) LIKE ? OR lower(name) LIKE ?
        ORDER BY
            CASE WHEN lower(symbol) = lower(?) THEN 0
                 WHEN lower(code) = lower(?) THEN 1
                 ELSE 2 END,
            bar_count DESC,
            symbol ASC
        LIMIT ?
        """,
        [pattern, pattern, pattern, query, query, limit],
    ).fetchall()
    return [SymbolRecord(**_symbol_row(row)) for row in rows]


def get_data_health(conn: duckdb.DuckDBPyConnection) -> DataHealthResponse:
    latest_trade_date = conn.execute("SELECT max(trade_date) FROM bars_daily").fetchone()[0]
    first_trade_date = conn.execute("SELECT min(trade_date) FROM bars_daily").fetchone()[0]
    daily_bars = conn.execute("SELECT count(*) FROM bars_daily").fetchone()[0]
    daily_symbols = conn.execute("SELECT count(*) FROM symbols").fetchone()[0]
    market_rows = conn.execute(
        """
        SELECT
            market,
            count(DISTINCT symbol) AS symbols,
            count(*) AS bars,
            min(trade_date) AS first_date,
            max(trade_date) AS last_date,
            count(DISTINCT CASE WHEN trade_date = ? THEN symbol END) AS latest_symbols
        FROM bars_daily
        GROUP BY market
        ORDER BY market
        """,
        [latest_trade_date],
    ).fetchall()
    markets = [
        MarketCoverage(
            market=row[0],
            symbols=row[1] or 0,
            bars=row[2] or 0,
            first_date=row[3],
            last_date=row[4],
            latest_symbols=row[5] or 0,
        )
        for row in market_rows
    ]
    timeframes = _timeframe_coverages(conn)
    recommendations = _data_health_recommendations(latest_trade_date, daily_symbols, markets, timeframes)
    days_since_latest = (date.today() - latest_trade_date).days if latest_trade_date else None
    return DataHealthResponse(
        generated_at=datetime.now(timezone.utc),
        latest_trade_date=latest_trade_date,
        days_since_latest=days_since_latest,
        daily_symbols=daily_symbols,
        daily_bars=daily_bars,
        first_trade_date=first_trade_date,
        markets=markets,
        timeframes=timeframes,
        recommendations=recommendations,
    )


def _timeframe_coverages(conn: duckdb.DuckDBPyConnection) -> list[TimeframeCoverage]:
    daily = conn.execute(
        """
        SELECT count(*) AS bars, count(DISTINCT symbol) AS symbols, min(trade_date) AS first_time, max(trade_date) AS last_time
        FROM bars_daily
        """
    ).fetchone()
    minute_rows = conn.execute(
        """
        SELECT
            interval_minutes,
            count(*) AS bars,
            count(DISTINCT symbol) AS symbols,
            min(trade_time) AS first_time,
            max(trade_time) AS last_time
        FROM bars_minute
        GROUP BY interval_minutes
        """
    ).fetchall()
    minute_by_interval = {row[0]: row[1:] for row in minute_rows}
    daily_available = (daily[0] or 0) > 0
    minute5 = minute_by_interval.get(5)
    minute5_available = bool(minute5 and minute5[1] > 0)
    result = [
        _coverage_from_row("D", "日线", daily, daily_available),
        _coverage_from_row("W", "周线", daily, daily_available, "日线聚合"),
        _coverage_from_row("M", "月线", daily, daily_available, "日线聚合"),
        _coverage_from_row("1M", "1 分钟", minute_by_interval.get(1), bool(minute_by_interval.get(1))),
        _coverage_from_row("5M", "5 分钟", minute5, minute5_available),
        _coverage_from_row("15M", "15 分钟", minute5, minute5_available, "5 分钟聚合"),
        _coverage_from_row("30M", "30 分钟", minute5, minute5_available, "5 分钟聚合"),
        _coverage_from_row("60M", "60 分钟", minute5, minute5_available, "5 分钟聚合"),
    ]
    return result


def _coverage_from_row(
    timeframe: str,
    label: str,
    row: tuple | None,
    available: bool,
    derived_from: str | None = None,
) -> TimeframeCoverage:
    if row is None:
        return TimeframeCoverage(timeframe=timeframe, label=label, available=False, derived_from=derived_from)
    return TimeframeCoverage(
        timeframe=timeframe,
        label=label,
        bars=row[0] or 0,
        symbols=row[1] or 0,
        first_time=_as_time_value(row[2]),
        last_time=_as_time_value(row[3]),
        available=available,
        derived_from=derived_from,
    )


def _data_health_recommendations(
    latest_trade_date: date | None,
    daily_symbols: int,
    markets: list[MarketCoverage],
    timeframes: list[TimeframeCoverage],
) -> list[DataRecommendation]:
    recommendations: list[DataRecommendation] = []
    if daily_symbols == 0:
        recommendations.append(
            DataRecommendation(
                severity="danger",
                title="缺少日线数据",
                detail="本地库还没有导入任何日线 K 线，无法判断股票覆盖和最近交易日。",
                action="先在通达信下载日线数据，再执行导入行情数据。",
            )
        )
        return recommendations

    if latest_trade_date and (date.today() - latest_trade_date).days > 4:
        recommendations.append(
            DataRecommendation(
                severity="warn",
                title="日线数据可能落后",
                detail=f"本地最新日线停在 {latest_trade_date.isoformat()}，已经超过 4 个自然日没有更新。",
                action="打开通达信补充最近日线数据后重新导入。",
            )
        )

    market_by_name = {item.market: item for item in markets}
    for market, label in [("sh", "沪市"), ("sz", "深市")]:
        item = market_by_name.get(market)
        if not item:
            recommendations.append(
                DataRecommendation(
                    severity="warn",
                    title=f"缺少{label}日线",
                    detail=f"本地库没有发现 {market.upper()} 市场日线记录。",
                    action=f"确认通达信 {market}/lday 目录已下载，再重新导入。",
                )
            )
        elif latest_trade_date and item.last_date and item.last_date < latest_trade_date:
            recommendations.append(
                DataRecommendation(
                    severity="warn",
                    title=f"{label}日线未同步到最新日",
                    detail=f"{label}最新为 {item.last_date.isoformat()}，全库最新为 {latest_trade_date.isoformat()}。",
                    action=f"补充 {market.upper()} 市场日线数据后重新导入。",
                )
            )

    timeframe_by_name = {item.timeframe: item for item in timeframes}
    if not timeframe_by_name.get("1M", TimeframeCoverage(timeframe="1M", label="1 分钟")).available:
        recommendations.append(
            DataRecommendation(
                severity="info",
                title="缺少 1 分钟数据",
                detail="1 分钟周期没有可用记录，短线回放和细粒度分析会为空。",
                action="在通达信下载 1 分钟线后重新导入。",
            )
        )
    if not timeframe_by_name.get("5M", TimeframeCoverage(timeframe="5M", label="5 分钟")).available:
        recommendations.append(
            DataRecommendation(
                severity="warn",
                title="缺少 5 分钟数据",
                detail="5 分钟数据为空，15 / 30 / 60 分钟聚合周期也无法生成。",
                action="在通达信下载 5 分钟线后重新导入。",
            )
        )

    if not recommendations:
        recommendations.append(
            DataRecommendation(
                severity="ok",
                title="暂无明显补数项",
                detail="日线、市场和分钟基础数据都有可用记录。",
                action="保持通达信每日更新后定期重新导入。",
            )
        )
    return recommendations


def get_bars(
    conn: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: str = "D",
    limit: int = 260,
    start_date: date | None = None,
    end_date: date | None = None,
    before: str | None = None,
) -> list[BarRecord]:
    timeframe = timeframe.upper()
    date_filters, date_params = _date_filter_sql(start_date, end_date, before)
    minute_map = {"1M": 1, "5M": 5, "15M": 15, "30M": 30, "60M": 60}
    if timeframe in minute_map:
        return get_minute_bars(conn, symbol, timeframe, minute_map[timeframe], limit, start_date, end_date, before)

    if timeframe == "D":
        query = """
            WITH daily AS (
                SELECT
                    symbol,
                    trade_date,
                    any_value(open) AS open,
                    any_value(high) AS high,
                    any_value(low) AS low,
                    any_value(close) AS close,
                    any_value(amount) AS amount,
                    any_value(volume) AS volume
                FROM bars_daily
                WHERE symbol = ?
                {date_filters}
                GROUP BY symbol, trade_date
            )
            SELECT symbol, 'D' AS timeframe, trade_date, open, high, low, close, amount, volume
            FROM daily
            ORDER BY trade_date DESC
            LIMIT ?
        """.format(date_filters=date_filters)
        rows = conn.execute(query, [symbol.lower(), *date_params, limit]).fetchall()
        rows.reverse()
        return [BarRecord(**_bar_row(row)) for row in rows]

    if timeframe in {"W", "M"}:
        bucket = "time_bucket(INTERVAL '1 week', trade_date)" if timeframe == "W" else "time_bucket(INTERVAL '1 month', trade_date)"
        grouped_date_filters, grouped_date_params = _date_filter_sql(start_date, end_date)
        before_date = _parse_before_date(before) if before else None
        rows = conn.execute(
            """
            WITH base AS (
                SELECT
                    symbol,
                    trade_date,
                    any_value(open) AS open,
                    any_value(high) AS high,
                    any_value(low) AS low,
                    any_value(close) AS close,
                    any_value(amount) AS amount,
                    any_value(volume) AS volume,
                    {bucket} AS bucket_date
                FROM bars_daily
                WHERE symbol = ?
                {date_filters}
                GROUP BY symbol, trade_date
            ),
            grouped AS (
                SELECT
                    symbol,
                    bucket_date,
                    first(open ORDER BY trade_date ASC) AS open,
                    max(high) AS high,
                    min(low) AS low,
                    last(close ORDER BY trade_date ASC) AS close,
                    sum(amount) AS amount,
                    sum(volume) AS volume,
                    max(trade_date) AS trade_date
                FROM base
                GROUP BY symbol, bucket_date
            )
            SELECT symbol, ? AS timeframe, trade_date, open, high, low, close, amount, volume
            FROM grouped
            WHERE (? IS NULL OR trade_date < ?::DATE)
            ORDER BY trade_date DESC
            LIMIT ?
            """.format(bucket=bucket, date_filters=grouped_date_filters),
            [symbol.lower(), *grouped_date_params, timeframe, before_date, before_date, limit],
        ).fetchall()
        rows.reverse()
        return [BarRecord(**_bar_row(row)) for row in rows]

    return []


def get_minute_bars(
    conn: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: str,
    interval_minutes: int,
    limit: int = 260,
    start_date: date | None = None,
    end_date: date | None = None,
    before: str | None = None,
) -> list[BarRecord]:
    date_filters, date_params = _minute_date_filter_sql(start_date, end_date, before)
    if interval_minutes in {1, 5}:
        rows = conn.execute(
            """
            WITH minute AS (
                SELECT
                    symbol,
                    trade_time,
                    any_value(open) AS open,
                    any_value(high) AS high,
                    any_value(low) AS low,
                    any_value(close) AS close,
                    any_value(amount) AS amount,
                    any_value(volume) AS volume
                FROM bars_minute
                WHERE symbol = ?
                  AND interval_minutes = ?
                {date_filters}
                GROUP BY symbol, trade_time
            )
            SELECT symbol, ? AS timeframe, trade_time, open, high, low, close, amount, volume
            FROM minute
            ORDER BY trade_time DESC
            LIMIT ?
            """.format(date_filters=date_filters),
            [symbol.lower(), interval_minutes, *date_params, timeframe, limit],
        ).fetchall()
        rows.reverse()
        return [BarRecord(**_bar_row(row)) for row in rows]

    grouped_date_filters, grouped_date_params = _minute_date_filter_sql(start_date, end_date)
    normalized_before = _normalize_before_timestamp(before)
    rows = conn.execute(
        """
        WITH base AS (
            SELECT
                symbol,
                trade_time,
                any_value(open) AS open,
                any_value(high) AS high,
                any_value(low) AS low,
                any_value(close) AS close,
                any_value(amount) AS amount,
                any_value(volume) AS volume,
                CASE
                    WHEN CAST(trade_time AS TIME) > TIME '09:30:00'
                     AND CAST(trade_time AS TIME) <= TIME '11:30:00'
                        THEN CAST(CAST(trade_time AS DATE) AS TIMESTAMP) + INTERVAL '9 hours 30 minutes'
                    WHEN CAST(trade_time AS TIME) > TIME '13:00:00'
                     AND CAST(trade_time AS TIME) <= TIME '15:00:00'
                        THEN CAST(CAST(trade_time AS DATE) AS TIMESTAMP) + INTERVAL '13 hours'
                    ELSE NULL
                END AS session_start
            FROM bars_minute
            WHERE symbol = ?
              AND interval_minutes = 5
            {date_filters}
            GROUP BY symbol, trade_time
        ),
        bucketed AS (
            SELECT
                *,
                CASE
                    WHEN session_start IS NULL THEN NULL
                    ELSE session_start
                        + CAST(
                            CEIL(date_diff('minute', session_start, trade_time)::DOUBLE / ?) * ?
                            AS BIGINT
                          ) * INTERVAL '1 minute'
                END AS bucket_time
            FROM base
            WHERE session_start IS NOT NULL
              AND date_diff('minute', session_start, trade_time) > 0
        ),
        grouped AS (
            SELECT
                symbol,
                bucket_time,
                first(open ORDER BY trade_time ASC) AS open,
                max(high) AS high,
                min(low) AS low,
                last(close ORDER BY trade_time ASC) AS close,
                sum(amount) AS amount,
                sum(volume) AS volume,
                count(*) AS bar_count
            FROM bucketed
            GROUP BY symbol, bucket_time
        )
        SELECT symbol, ? AS timeframe, bucket_time, open, high, low, close, amount, volume
        FROM grouped
        WHERE bar_count = ?
          AND (? IS NULL OR bucket_time < ?::TIMESTAMP)
        ORDER BY bucket_time DESC
        LIMIT ?
        """.format(date_filters=grouped_date_filters),
        [
            symbol.lower(),
            *grouped_date_params,
            interval_minutes,
            interval_minutes,
            timeframe,
            interval_minutes // 5,
            normalized_before,
            normalized_before,
            limit,
        ],
    ).fetchall()
    rows.reverse()
    return [BarRecord(**_bar_row(row)) for row in rows]


def list_annotations(
    conn: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: str,
) -> list[AnnotationRecord]:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_timeframe = _normalize_timeframe(timeframe)
    rows = conn.execute(
        """
        SELECT id, symbol, timeframe, overlay_type, payload, created_at, updated_at
        FROM annotations
        WHERE symbol = ? AND timeframe = ?
        ORDER BY updated_at DESC, id DESC
        """,
        [normalized_symbol, normalized_timeframe],
    ).fetchall()
    return [AnnotationRecord(**_annotation_row(row)) for row in rows]


def list_review_notes(
    conn: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: str,
) -> list[AnnotationRecord]:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_timeframe = _normalize_timeframe(timeframe)
    rows = conn.execute(
        """
        SELECT id, symbol, timeframe, overlay_type, payload, created_at, updated_at
        FROM annotations
        WHERE symbol = ? AND timeframe = ? AND overlay_type = 'review_note'
        ORDER BY updated_at DESC, id DESC
        """,
        [normalized_symbol, normalized_timeframe],
    ).fetchall()
    return [AnnotationRecord(**_annotation_row(row)) for row in rows]


def save_review_note(conn: duckdb.DuckDBPyConnection, item: ReviewNoteSave) -> AnnotationRecord:
    normalized_title = item.title.strip() or "复盘笔记"
    normalized_content = item.content.strip()
    if not normalized_content:
        raise ValueError("复盘笔记 content 不能为空。")
    normalized_tags: list[str] = []
    seen_tags: set[str] = set()
    for tag in item.tags:
        normalized_tag = tag.strip()
        if not normalized_tag or normalized_tag in seen_tags:
            continue
        seen_tags.add(normalized_tag)
        normalized_tags.append(normalized_tag)
    payload = {
        **item.payload,
        "title": normalized_title,
        "content": normalized_content,
        "tags": normalized_tags,
        "source": item.payload.get("source", "review-panel"),
    }
    return create_annotation(
        conn,
        AnnotationCreate(
            symbol=item.symbol,
            timeframe=item.timeframe,
            overlay_type="review_note",
            payload=payload,
        ),
    )


def create_annotation(conn: duckdb.DuckDBPyConnection, item: AnnotationCreate) -> AnnotationRecord:
    annotation_id = str(uuid.uuid4())
    created_at = utc_now()
    updated_at = created_at
    normalized_symbol = _normalize_symbol(item.symbol)
    normalized_timeframe = _normalize_timeframe(item.timeframe)
    normalized_overlay_type = _normalize_overlay_type(item.overlay_type)
    if _is_active_manual_structure(normalized_overlay_type, item.payload):
        _deactivate_other_manual_structures(
            conn, normalized_symbol, normalized_timeframe, normalized_overlay_type, annotation_id, updated_at
        )
    payload = json.dumps(item.payload, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO annotations
        (id, symbol, timeframe, overlay_type, payload, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            annotation_id,
            normalized_symbol,
            normalized_timeframe,
            normalized_overlay_type,
            payload,
            created_at,
            updated_at,
        ],
    )
    return get_annotation(conn, annotation_id)


def update_annotation(
    conn: duckdb.DuckDBPyConnection,
    annotation_id: str,
    item: AnnotationUpdate,
) -> AnnotationRecord | None:
    current = get_annotation_or_none(conn, annotation_id)
    if current is None:
        return None
    overlay_type = item.overlay_type if item.overlay_type is not None else current.overlay_type
    normalized_overlay_type = _normalize_overlay_type(overlay_type)
    payload = item.payload if item.payload is not None else current.payload
    updated_at = utc_now()
    if _is_active_manual_structure(normalized_overlay_type, payload):
        _deactivate_other_manual_structures(
            conn, current.symbol, current.timeframe, normalized_overlay_type, annotation_id, updated_at
        )
    conn.execute(
        """
        UPDATE annotations
        SET overlay_type = ?, payload = ?, updated_at = ?
        WHERE id = ?
        """,
        [normalized_overlay_type, json.dumps(payload, ensure_ascii=False), updated_at, annotation_id],
    )
    return get_annotation(conn, annotation_id)


def delete_annotation(conn: duckdb.DuckDBPyConnection, annotation_id: str) -> bool:
    existing = get_annotation_or_none(conn, annotation_id)
    if existing is None:
        return False
    conn.execute("DELETE FROM annotations WHERE id = ?", [annotation_id])
    return True


def get_annotation(conn: duckdb.DuckDBPyConnection, annotation_id: str) -> AnnotationRecord:
    item = get_annotation_or_none(conn, annotation_id)
    if item is None:
        raise KeyError(annotation_id)
    return item


def get_annotation_or_none(conn: duckdb.DuckDBPyConnection, annotation_id: str) -> AnnotationRecord | None:
    row = conn.execute(
        """
        SELECT id, symbol, timeframe, overlay_type, payload, created_at, updated_at
        FROM annotations
        WHERE id = ?
        LIMIT 1
        """,
        [annotation_id],
    ).fetchone()
    return AnnotationRecord(**_annotation_row(row)) if row else None


def list_rule_profiles(conn: duckdb.DuckDBPyConnection, analysis_type: str | None = None) -> list[RuleProfile]:
    if analysis_type:
        rows = conn.execute(
            """
            SELECT id, name, analysis_type, version, params, is_default, created_at, updated_at
            FROM rule_profiles
            WHERE analysis_type = ?
            ORDER BY is_default DESC, updated_at DESC, id DESC
            """,
            [analysis_type],
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, name, analysis_type, version, params, is_default, created_at, updated_at
            FROM rule_profiles
            ORDER BY analysis_type, is_default DESC, updated_at DESC, id DESC
            """
        ).fetchall()
    return [RuleProfile(**_rule_profile_row(row)) for row in rows]


def create_rule_profile(conn: duckdb.DuckDBPyConnection, item: RuleProfileCreate) -> RuleProfile:
    profile_id = str(uuid.uuid4())
    created_at = utc_now()
    updated_at = created_at
    if item.is_default:
        conn.execute("UPDATE rule_profiles SET is_default = false WHERE analysis_type = ?", [item.analysis_type])
    conn.execute(
        """
        INSERT INTO rule_profiles
        (id, name, analysis_type, version, params, is_default, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            profile_id,
            item.name,
            item.analysis_type,
            item.version,
            json.dumps(item.params, ensure_ascii=False),
            item.is_default,
            created_at,
            updated_at,
        ],
    )
    return list_rule_profiles(conn, item.analysis_type)[0]


def save_import_job(conn: duckdb.DuckDBPyConnection, item: ImportJob) -> None:
    updated_at = utc_now()
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute("DELETE FROM import_jobs WHERE id = ?", [item.id])
        conn.execute(
            """
            INSERT INTO import_jobs
            (
                id, status, source_path, files_seen, files_imported, bars_imported,
                minute_files_seen, minute_files_imported, minute_bars_imported, symbols_imported,
                errors, message, started_at, finished_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                item.id,
                item.status,
                item.source_path,
                item.files_seen,
                item.files_imported,
                item.bars_imported,
                item.minute_files_seen,
                item.minute_files_imported,
                item.minute_bars_imported,
                item.symbols_imported,
                json.dumps(item.errors, ensure_ascii=False),
                item.message,
                item.started_at,
                item.finished_at,
                updated_at,
            ],
        )
        _prune_import_jobs(conn, IMPORT_JOBS_RETENTION)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def get_import_job(conn: duckdb.DuckDBPyConnection, job_id: str) -> ImportJob | None:
    row = conn.execute(
        """
        SELECT
            id, status, source_path, files_seen, files_imported, bars_imported,
            minute_files_seen, minute_files_imported, minute_bars_imported, symbols_imported,
            errors, message, started_at, finished_at
        FROM import_jobs
        WHERE id = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        [job_id],
    ).fetchone()
    return ImportJob(**_import_job_row(row)) if row else None


def list_import_jobs(
    conn: duckdb.DuckDBPyConnection,
    limit: int = 20,
    status: str | None = None,
    source_path_exists: bool | None = None,
) -> list[ImportJob]:
    should_apply_sql_limit = source_path_exists is None
    sql_limit_clause = "LIMIT ?" if should_apply_sql_limit else ""
    sql_limit_params = [limit] if should_apply_sql_limit else []

    if status is None:
        rows = conn.execute(
            f"""
            SELECT
                id, status, source_path, files_seen, files_imported, bars_imported,
                minute_files_seen, minute_files_imported, minute_bars_imported, symbols_imported,
                errors, message, started_at, finished_at
            FROM import_jobs
            ORDER BY updated_at DESC, id DESC
            {sql_limit_clause}
            """,
            sql_limit_params,
        ).fetchall()
    elif status == "pending":
        rows = conn.execute(
            f"""
            SELECT
                id, status, source_path, files_seen, files_imported, bars_imported,
                minute_files_seen, minute_files_imported, minute_bars_imported, symbols_imported,
                errors, message, started_at, finished_at
            FROM import_jobs
            WHERE status IN ('queued', 'running')
            ORDER BY updated_at DESC, id DESC
            {sql_limit_clause}
            """,
            sql_limit_params,
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT
                id, status, source_path, files_seen, files_imported, bars_imported,
                minute_files_seen, minute_files_imported, minute_bars_imported, symbols_imported,
                errors, message, started_at, finished_at
            FROM import_jobs
            WHERE status = ?
            ORDER BY updated_at DESC, id DESC
            {sql_limit_clause}
            """,
            [status, *sql_limit_params],
        ).fetchall()
    items = [ImportJob(**_import_job_row(row)) for row in rows]
    if source_path_exists is None:
        return items
    return [item for item in items if item.source_path_exists is source_path_exists][:limit]


def update_import_job(conn: duckdb.DuckDBPyConnection, job_id: str, **changes) -> ImportJob | None:
    current = get_import_job(conn, job_id)
    if current is None:
        return None
    updated = current.model_copy(update=changes)
    save_import_job(conn, updated)
    return updated


def fail_inactive_import_jobs(
    conn: duckdb.DuckDBPyConnection,
    active_job_ids: set[str],
    reason: str,
) -> int:
    rows = conn.execute(
        """
        SELECT id, errors
        FROM import_jobs
        WHERE status IN ('queued', 'running')
        ORDER BY updated_at DESC, id DESC
        """
    ).fetchall()
    stale_rows = [(job_id, raw_errors) for job_id, raw_errors in rows if job_id not in active_job_ids]
    if not stale_rows:
        return 0
    now = utc_now()
    conn.execute("BEGIN TRANSACTION")
    try:
        for job_id, raw_errors in stale_rows:
            parsed_errors = json.loads(raw_errors) if raw_errors else []
            if reason not in parsed_errors:
                parsed_errors.append(reason)
            conn.execute(
                """
                UPDATE import_jobs
                SET status = 'failed', errors = ?, message = ?, finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                [json.dumps(parsed_errors, ensure_ascii=False), reason, now, now, job_id],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(stale_rows)


def export_user_backup(conn: duckdb.DuckDBPyConnection, app_config: dict) -> UserBackupPayload:
    annotations = _list_all_annotations(conn)
    rule_profiles = list_rule_profiles(conn)
    return UserBackupPayload(
        schema_version=1,
        exported_at=utc_now(),
        config=dict(app_config),
        annotations=annotations,
        rule_profiles=rule_profiles,
    )


def import_user_backup(
    conn: duckdb.DuckDBPyConnection,
    payload: UserBackupPayload,
) -> UserBackupImportResult:
    _validate_rule_profile_ids_unique_per_analysis_type(payload.rule_profiles)
    deduped_annotations = _dedupe_annotations_by_id(payload.annotations)
    _validate_annotation_ids(deduped_annotations)
    _validate_annotation_overlay_types(deduped_annotations)
    _validate_annotation_symbols(deduped_annotations)
    _validate_annotation_timeframes(deduped_annotations)
    deduped_rule_profiles = _dedupe_rule_profiles_by_id(payload.rule_profiles)
    conn.execute("BEGIN TRANSACTION")
    try:
        for item in deduped_annotations:
            conn.execute("DELETE FROM annotations WHERE id = ?", [item.id])
            normalized_symbol = _normalize_symbol(item.symbol)
            normalized_timeframe = _normalize_timeframe(item.timeframe)
            normalized_overlay_type = _normalize_overlay_type(item.overlay_type)
            conn.execute(
                """
                INSERT INTO annotations
                (id, symbol, timeframe, overlay_type, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    item.id,
                    normalized_symbol,
                    normalized_timeframe,
                    normalized_overlay_type,
                    json.dumps(item.payload, ensure_ascii=False),
                    item.created_at,
                    item.updated_at,
                ],
            )
        _normalize_active_manual_structures(conn)
        for item in deduped_rule_profiles:
            conn.execute("DELETE FROM rule_profiles WHERE id = ?", [item.id])
            if item.is_default:
                conn.execute("UPDATE rule_profiles SET is_default = false WHERE analysis_type = ?", [item.analysis_type])
            conn.execute(
                """
                INSERT INTO rule_profiles
                (id, name, analysis_type, version, params, is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    item.id,
                    item.name,
                    item.analysis_type,
                    item.version,
                    json.dumps(item.params, ensure_ascii=False),
                    item.is_default,
                    item.created_at,
                    item.updated_at,
                ],
            )
        _ensure_default_rule_profiles(conn)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return UserBackupImportResult(
        config_imported=bool(payload.config),
        annotations_imported=len(deduped_annotations),
        rule_profiles_imported=len(deduped_rule_profiles),
    )


def export_analysis_scheme(
    conn: duckdb.DuckDBPyConnection,
    name: str = "AetherStock 分析方案",
    description: str = "",
) -> AnalysisSchemePayload:
    return AnalysisSchemePayload(
        schema_version=1,
        exported_at=utc_now(),
        name=name,
        description=description,
        rule_profiles=list_rule_profiles(conn),
    )


def import_analysis_scheme(
    conn: duckdb.DuckDBPyConnection,
    payload: AnalysisSchemePayload,
) -> AnalysisSchemeImportResult:
    _validate_rule_profile_ids_unique_per_analysis_type(payload.rule_profiles)
    deduped_rule_profiles = _dedupe_rule_profiles_by_id(payload.rule_profiles)
    conn.execute("BEGIN TRANSACTION")
    try:
        imported_analysis_types = sorted({item.analysis_type for item in deduped_rule_profiles})
        for analysis_type in imported_analysis_types:
            conn.execute("DELETE FROM rule_profiles WHERE analysis_type = ?", [analysis_type])

        for item in deduped_rule_profiles:
            if item.is_default:
                conn.execute("UPDATE rule_profiles SET is_default = false WHERE analysis_type = ?", [item.analysis_type])
            conn.execute(
                """
                INSERT INTO rule_profiles
                (id, name, analysis_type, version, params, is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    item.id,
                    item.name,
                    item.analysis_type,
                    item.version,
                    json.dumps(item.params, ensure_ascii=False),
                    item.is_default,
                    item.created_at,
                    item.updated_at,
                ],
            )
        _ensure_default_rule_profiles(conn)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return AnalysisSchemeImportResult(rule_profiles_imported=len(deduped_rule_profiles))


def _dedupe_rule_profiles_by_id(items: list[RuleProfile]) -> list[RuleProfile]:
    seen_ids: set[str] = set()
    deduped_reversed: list[RuleProfile] = []
    for item in reversed(items):
        if item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        deduped_reversed.append(item)
    deduped_reversed.reverse()
    return deduped_reversed


def _validate_rule_profile_ids_unique_per_analysis_type(items: list[RuleProfile]) -> None:
    seen_types_by_id: dict[str, str] = {}
    for item in items:
        if not item.id.strip():
            raise ValueError("规则 ID 不能为空。")
        previous_type = seen_types_by_id.get(item.id)
        if previous_type is None:
            seen_types_by_id[item.id] = item.analysis_type
            continue
        if previous_type != item.analysis_type:
            raise ValueError(f"规则 ID 冲突：{item.id} 同时用于 {previous_type} 和 {item.analysis_type}。")


def _dedupe_annotations_by_id(items: list[AnnotationRecord]) -> list[AnnotationRecord]:
    seen_ids: set[str] = set()
    deduped_reversed: list[AnnotationRecord] = []
    for item in reversed(items):
        if item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        deduped_reversed.append(item)
    deduped_reversed.reverse()
    return deduped_reversed


def _validate_annotation_timeframes(items: list[AnnotationRecord]) -> None:
    for item in items:
        try:
            _normalize_timeframe(item.timeframe)
        except ValueError:
            raise ValueError(f"标注 timeframe 不支持：{item.timeframe}")


def _validate_annotation_ids(items: list[AnnotationRecord]) -> None:
    for item in items:
        if not item.id.strip():
            raise ValueError("标注 ID 不能为空。")


def _validate_annotation_overlay_types(items: list[AnnotationRecord]) -> None:
    for item in items:
        try:
            _normalize_overlay_type(item.overlay_type)
        except ValueError:
            raise ValueError("标注 overlay_type 不能为空。")


def _validate_annotation_symbols(items: list[AnnotationRecord]) -> None:
    for item in items:
        try:
            _normalize_symbol(item.symbol)
        except ValueError:
            raise ValueError("标注 symbol 不能为空。")


def _normalize_timeframe(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in _VALID_TIMEFRAMES:
        raise ValueError(f"timeframe 不支持：{value}")
    return normalized


def _normalize_symbol(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("标注 symbol 不能为空。")
    return normalized


def _normalize_overlay_type(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("标注 overlay_type 不能为空。")
    return normalized


def _list_all_annotations(conn: duckdb.DuckDBPyConnection) -> list[AnnotationRecord]:
    rows = conn.execute(
        """
        SELECT id, symbol, timeframe, overlay_type, payload, created_at, updated_at
        FROM annotations
        ORDER BY symbol, timeframe, updated_at DESC, id DESC
        """
    ).fetchall()
    return [AnnotationRecord(**_annotation_row(row)) for row in rows]


def _is_active_manual_structure(overlay_type: str, payload: dict) -> bool:
    return overlay_type in {"chan", "wave"} and payload.get("active") is not False


def _deactivate_other_manual_structures(
    conn: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: str,
    overlay_type: str,
    active_annotation_id: str,
    updated_at: datetime,
) -> None:
    rows = conn.execute(
        """
        SELECT id, payload
        FROM annotations
        WHERE symbol = ? AND timeframe = ? AND overlay_type = ? AND id != ?
        """,
        [symbol.lower(), timeframe.upper(), overlay_type, active_annotation_id],
    ).fetchall()
    for annotation_id, raw_payload in rows:
        payload = json.loads(raw_payload) if raw_payload else {}
        if payload.get("active") is False:
            continue
        payload["active"] = False
        payload["deactivated_at"] = updated_at.isoformat()
        payload["deactivated_reason"] = "superseded_by_new_manual_structure"
        conn.execute(
            """
            UPDATE annotations
            SET payload = ?, updated_at = ?
            WHERE id = ?
            """,
            [json.dumps(payload, ensure_ascii=False), updated_at, annotation_id],
        )


def _normalize_active_manual_structures(conn: duckdb.DuckDBPyConnection) -> None:
    rows = conn.execute(
        """
        SELECT id, symbol, timeframe, overlay_type, payload, updated_at
        FROM annotations
        WHERE overlay_type IN ('chan', 'wave')
        ORDER BY symbol, timeframe, overlay_type, updated_at DESC, id DESC
        """
    ).fetchall()
    active_keys: set[tuple[str, str, str]] = set()
    for annotation_id, symbol, timeframe, overlay_type, raw_payload, updated_at in rows:
        payload = json.loads(raw_payload) if raw_payload else {}
        if not _is_active_manual_structure(overlay_type, payload):
            continue
        key = (symbol, timeframe, overlay_type)
        if key not in active_keys:
            active_keys.add(key)
            continue
        payload["active"] = False
        payload["deactivated_at"] = updated_at.isoformat()
        payload["deactivated_reason"] = "superseded_during_backup_import"
        conn.execute(
            """
            UPDATE annotations
            SET payload = ?
            WHERE id = ?
            """,
            [json.dumps(payload, ensure_ascii=False), annotation_id],
        )


def _ensure_default_rule_profiles(conn: duckdb.DuckDBPyConnection) -> None:
    analysis_types = conn.execute("SELECT DISTINCT analysis_type FROM rule_profiles").fetchall()
    for (analysis_type,) in analysis_types:
        default_count = conn.execute(
            "SELECT count(*) FROM rule_profiles WHERE analysis_type = ? AND is_default = true",
            [analysis_type],
        ).fetchone()[0]
        if default_count > 0:
            continue
        latest = conn.execute(
            """
            SELECT id
            FROM rule_profiles
            WHERE analysis_type = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            [analysis_type],
        ).fetchone()
        if latest is None:
            continue
        conn.execute("UPDATE rule_profiles SET is_default = true WHERE id = ?", [latest[0]])


def seed_default_profiles(conn: duckdb.DuckDBPyConnection) -> None:
    count = conn.execute("SELECT count(*) FROM rule_profiles").fetchone()[0]
    if count > 0:
        return
    defaults = [
        RuleProfileCreate(
            name="缠论默认分型 / 笔 / 线段 / 中枢",
            analysis_type="chan",
            version="0.5.0",
            params={
                "strict_fractal": False,
                "include_containment": True,
                "min_bars_for_bi": 5,
                "min_bis_for_segment": 3,
                "min_bis_for_zhongshu": 3,
            },
            is_default=True,
        ),
        RuleProfileCreate(
            name="波浪 ZigZag 默认",
            analysis_type="wave",
            version="0.1.0",
            params={"zigzag_threshold_pct": 5.0, "min_swing_bars": 3},
            is_default=True,
        ),
    ]
    for item in defaults:
        profile_id = str(uuid.uuid4())
        created_at = utc_now()
        updated_at = created_at
        conn.execute(
            """
            INSERT INTO rule_profiles
            (id, name, analysis_type, version, params, is_default, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                profile_id,
                item.name,
                item.analysis_type,
                item.version,
                json.dumps(item.params, ensure_ascii=False),
                item.is_default,
                created_at,
                updated_at,
            ],
        )


def import_daily_files(
    source_path: Path,
    files: list[Path],
    markets: list[str] | None = None,
    limit_files: int | None = None,
    progress: Callable[[dict], None] | None = None,
) -> tuple[int, int, int, int, int, list[str]]:
    errors: list[str] = []
    bars_imported = 0
    minute_bars_imported = 0
    files_imported = 0
    minute_files_seen = 0
    minute_files_imported = 0
    csv_path: str | None = None
    minute_csv_path: str | None = None

    def emit_progress(message: str) -> None:
        if progress:
            progress(
                {
                    "files_imported": files_imported,
                    "bars_imported": bars_imported,
                    "minute_files_seen": minute_files_seen,
                    "minute_files_imported": minute_files_imported,
                    "minute_bars_imported": minute_bars_imported,
                    "errors": errors[:50],
                    "message": message,
                }
            )

    try:
        with tempfile.NamedTemporaryFile("w", newline="", suffix=".csv", delete=False) as csv_file:
            csv_path = csv_file.name
            writer = csv.writer(csv_file)
            writer.writerow(["symbol", "market", "code", "trade_date", "open", "high", "low", "close", "amount", "volume"])
            emit_progress("正在解析日线文件。")
            for file_path in files:
                try:
                    from .tdx import parse_daily_file

                    bars = parse_daily_file(file_path)
                    if not bars:
                        continue
                    for bar in bars:
                        writer.writerow(
                            [
                                bar.symbol,
                                bar.market,
                                bar.code,
                                bar.trade_date.isoformat(),
                                bar.open,
                                bar.high,
                                bar.low,
                                bar.close,
                                bar.amount,
                                bar.volume,
                            ]
                        )
                    bars_imported += len(bars)
                    files_imported += 1
                    emit_progress("正在解析日线文件。")
                except Exception as exc:  # noqa: BLE001
                    rel = file_path.relative_to(source_path) if file_path.is_relative_to(source_path) else file_path
                    errors.append(f"{rel}: {exc}")
                    emit_progress("解析日线文件时遇到错误。")

        from .tdx import iter_minute_files, parse_minute_file

        minute_files = iter_minute_files(source_path, markets or ["sh", "sz", "bj"])
        if limit_files is not None:
            minute_files = minute_files[:limit_files]
        minute_files_seen = len(minute_files)
        emit_progress("正在解析分钟线文件。")
        with tempfile.NamedTemporaryFile("w", newline="", suffix=".csv", delete=False) as minute_csv_file:
            minute_csv_path = minute_csv_file.name
            writer = csv.writer(minute_csv_file)
            writer.writerow(
                ["symbol", "market", "code", "trade_time", "interval_minutes", "open", "high", "low", "close", "amount", "volume"]
            )
            for file_path in minute_files:
                try:
                    bars = parse_minute_file(file_path)
                    if not bars:
                        continue
                    for bar in bars:
                        writer.writerow(
                            [
                                bar.symbol,
                                bar.market,
                                bar.code,
                                bar.trade_time.isoformat(sep=" ", timespec="minutes"),
                                bar.interval_minutes,
                                bar.open,
                                bar.high,
                                bar.low,
                                bar.close,
                                bar.amount,
                                bar.volume,
                            ]
                        )
                    minute_bars_imported += len(bars)
                    minute_files_imported += 1
                    emit_progress("正在解析分钟线文件。")
                except Exception as exc:  # noqa: BLE001
                    rel = file_path.relative_to(source_path) if file_path.is_relative_to(source_path) else file_path
                    errors.append(f"{rel}: {exc}")
                    emit_progress("解析分钟线文件时遇到错误。")

        if bars_imported == 0 and minute_bars_imported == 0:
            return files_imported, bars_imported, minute_files_seen, minute_files_imported, minute_bars_imported, errors

        with connect() as conn:
            emit_progress("正在写入本地数据库。")
            conn.execute("BEGIN TRANSACTION")
            try:
                if bars_imported > 0:
                    conn.execute(
                        """
                        CREATE TEMP TABLE import_daily AS
                        SELECT
                            symbol::TEXT AS symbol,
                            market::TEXT AS market,
                            code::TEXT AS code,
                            trade_date::DATE AS trade_date,
                            open::DOUBLE AS open,
                            high::DOUBLE AS high,
                            low::DOUBLE AS low,
                            close::DOUBLE AS close,
                            amount::DOUBLE AS amount,
                            volume::BIGINT AS volume
                        FROM read_csv_auto(?, HEADER=TRUE, ALL_VARCHAR=TRUE)
                        """,
                        [csv_path],
                    )
                    conn.execute(
                        """
                        DELETE FROM bars_daily
                        USING (
                            SELECT DISTINCT symbol, trade_date
                            FROM import_daily
                        ) AS import_keys
                        WHERE bars_daily.symbol = import_keys.symbol
                          AND bars_daily.trade_date = import_keys.trade_date
                        """
                    )
                    conn.execute(
                        """
                        INSERT INTO bars_daily
                        (symbol, market, code, trade_date, open, high, low, close, amount, volume)
                        SELECT
                            symbol,
                            any_value(market) AS market,
                            any_value(code) AS code,
                            trade_date,
                            any_value(open) AS open,
                            any_value(high) AS high,
                            any_value(low) AS low,
                            any_value(close) AS close,
                            any_value(amount) AS amount,
                            any_value(volume) AS volume
                        FROM import_daily
                        GROUP BY symbol, trade_date
                        """
                    )
                    refresh_symbols(conn)
                if minute_bars_imported > 0:
                    conn.execute(
                        """
                        CREATE TEMP TABLE import_minute AS
                        SELECT
                            symbol::TEXT AS symbol,
                            market::TEXT AS market,
                            code::TEXT AS code,
                            trade_time::TIMESTAMP AS trade_time,
                            interval_minutes::INTEGER AS interval_minutes,
                            open::DOUBLE AS open,
                            high::DOUBLE AS high,
                            low::DOUBLE AS low,
                            close::DOUBLE AS close,
                            amount::DOUBLE AS amount,
                            volume::BIGINT AS volume
                        FROM read_csv_auto(?, HEADER=TRUE, ALL_VARCHAR=TRUE)
                        """,
                        [minute_csv_path],
                    )
                    conn.execute(
                        """
                        DELETE FROM bars_minute
                        USING (
                            SELECT DISTINCT symbol, interval_minutes, trade_time
                            FROM import_minute
                        ) AS import_keys
                        WHERE bars_minute.symbol = import_keys.symbol
                          AND bars_minute.interval_minutes = import_keys.interval_minutes
                          AND bars_minute.trade_time = import_keys.trade_time
                        """
                    )
                    conn.execute(
                        """
                        INSERT INTO bars_minute
                        (symbol, market, code, trade_time, interval_minutes, open, high, low, close, amount, volume)
                        SELECT
                            symbol,
                            any_value(market) AS market,
                            any_value(code) AS code,
                            trade_time,
                            interval_minutes,
                            any_value(open) AS open,
                            any_value(high) AS high,
                            any_value(low) AS low,
                            any_value(close) AS close,
                            any_value(amount) AS amount,
                            any_value(volume) AS volume
                        FROM import_minute
                        GROUP BY symbol, interval_minutes, trade_time
                        """
                    )
                from .tdx import load_symbol_name_map

                apply_symbol_names(conn, load_symbol_name_map(source_path))
                conn.execute("COMMIT")
                emit_progress("数据库写入完成。")
            except Exception:
                conn.execute("ROLLBACK")
                raise
    finally:
        if csv_path:
            Path(csv_path).unlink(missing_ok=True)
        if minute_csv_path:
            Path(minute_csv_path).unlink(missing_ok=True)
    return files_imported, bars_imported, minute_files_seen, minute_files_imported, minute_bars_imported, errors


def _symbol_row(row: tuple) -> dict:
    symbol, market, code, name, kind, first_date, last_date, bar_count = row
    return {
        "symbol": symbol,
        "market": market,
        "code": code,
        "name": name,
        "kind": kind,
        "first_date": _as_date(first_date),
        "last_date": _as_date(last_date),
        "bar_count": bar_count,
    }


def _bar_row(row: tuple) -> dict:
    symbol, timeframe, trade_date, open_, high, low, close, amount, volume = row
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "trade_date": _as_time_value(trade_date),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "amount": amount,
        "volume": volume,
    }


def _date_filter_sql(start_date: date | None, end_date: date | None, before: str | None = None) -> tuple[str, list]:
    filters: list[str] = []
    params: list = []
    if start_date is not None:
        filters.append("AND trade_date >= ?")
        params.append(start_date)
    if end_date is not None:
        filters.append("AND trade_date <= ?")
        params.append(end_date)
    if before:
        filters.append("AND trade_date < ?")
        params.append(_parse_before_date(before))
    return ("\n            " + "\n            ".join(filters) if filters else ""), params


def _minute_date_filter_sql(start_date: date | None, end_date: date | None, before: str | None = None) -> tuple[str, list]:
    filters: list[str] = []
    params: list = []
    if start_date is not None:
        filters.append("AND CAST(trade_time AS DATE) >= ?")
        params.append(start_date)
    if end_date is not None:
        filters.append("AND CAST(trade_time AS DATE) <= ?")
        params.append(end_date)
    if before:
        filters.append("AND trade_time < ?::TIMESTAMP")
        params.append(_normalize_before_timestamp(before))
    return ("\n            " + "\n            ".join(filters) if filters else ""), params


def _annotation_row(row: tuple) -> dict:
    annotation_id, symbol, timeframe, overlay_type, payload, created_at, updated_at = row
    return {
        "id": annotation_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "overlay_type": overlay_type,
        "payload": json.loads(payload),
        "created_at": _as_datetime(created_at),
        "updated_at": _as_datetime(updated_at),
    }


def _rule_profile_row(row: tuple) -> dict:
    profile_id, name, analysis_type, version, params, is_default, created_at, updated_at = row
    return {
        "id": profile_id,
        "name": name,
        "analysis_type": analysis_type,
        "version": version,
        "params": json.loads(params),
        "is_default": bool(is_default),
        "created_at": _as_datetime(created_at),
        "updated_at": _as_datetime(updated_at),
    }


def _import_job_row(row: tuple) -> dict:
    (
        job_id,
        status,
        source_path,
        files_seen,
        files_imported,
        bars_imported,
        minute_files_seen,
        minute_files_imported,
        minute_bars_imported,
        symbols_imported,
        errors,
        message,
        started_at,
        finished_at,
    ) = row
    source_path_exists = None
    if isinstance(source_path, str) and source_path.strip():
        try:
            source_path_exists = Path(source_path).expanduser().exists()
        except (OSError, RuntimeError, ValueError):
            source_path_exists = False
    return {
        "id": job_id,
        "status": status,
        "source_path": source_path,
        "source_path_exists": source_path_exists,
        "files_seen": int(files_seen),
        "files_imported": int(files_imported),
        "bars_imported": int(bars_imported),
        "minute_files_seen": int(minute_files_seen),
        "minute_files_imported": int(minute_files_imported),
        "minute_bars_imported": int(minute_bars_imported),
        "symbols_imported": int(symbols_imported),
        "errors": json.loads(errors) if errors else [],
        "message": message,
        "started_at": _as_datetime(started_at) if started_at is not None else None,
        "finished_at": _as_datetime(finished_at) if finished_at is not None else None,
    }


def _prune_import_jobs(conn: duckdb.DuckDBPyConnection, retention: int) -> None:
    if retention < 1:
        retention = 1
    conn.execute(
        """
        DELETE FROM import_jobs
        WHERE id IN (
            SELECT id
            FROM import_jobs
            ORDER BY updated_at DESC, id DESC
            OFFSET ?
        )
        """,
        [retention],
    )


def _as_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _as_time_value(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    if " " in text:
        return text.replace(" ", "T")[:16]
    return text


def _parse_before_date(value: str) -> date:
    return date.fromisoformat(value.split("T", 1)[0])


def _normalize_before_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    if "T" in value:
        return value.replace("T", " ")[:16]
    return f"{value} 00:00"


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
