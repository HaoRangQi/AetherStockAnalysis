from __future__ import annotations

import csv
import json
import tempfile
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from . import config
from .schemas import AnnotationCreate, AnnotationRecord, AnnotationUpdate, BarRecord, RuleProfile, RuleProfileCreate, SymbolRecord


_init_lock = threading.Lock()
_initialized_db_path: Path | None = None


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
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL
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


def get_bars(
    conn: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: str = "D",
    limit: int = 260,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[BarRecord]:
    timeframe = timeframe.upper()
    date_filters, date_params = _date_filter_sql(start_date, end_date)
    minute_map = {"1M": 1, "5M": 5, "15M": 15, "30M": 30, "60M": 60}
    if timeframe in minute_map:
        return get_minute_bars(conn, symbol, timeframe, minute_map[timeframe], limit, start_date, end_date)

    if timeframe == "D":
        query = """
            SELECT symbol, 'D' AS timeframe, trade_date, open, high, low, close, amount, volume
            FROM bars_daily
            WHERE symbol = ?
            {date_filters}
            ORDER BY trade_date DESC
            LIMIT ?
        """.format(date_filters=date_filters)
        rows = conn.execute(query, [symbol.lower(), *date_params, limit]).fetchall()
        rows.reverse()
        return [BarRecord(**_bar_row(row)) for row in rows]

    if timeframe in {"W", "M"}:
        bucket = "time_bucket(INTERVAL '1 week', trade_date)" if timeframe == "W" else "time_bucket(INTERVAL '1 month', trade_date)"
        rows = conn.execute(
            f"""
            WITH base AS (
                SELECT *, {bucket} AS bucket_date
                FROM bars_daily
                WHERE symbol = ?
                {date_filters}
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
            ORDER BY trade_date DESC
            LIMIT ?
            """.format(bucket=bucket, date_filters=date_filters),
            [symbol.lower(), *date_params, timeframe, limit],
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
) -> list[BarRecord]:
    date_filters, date_params = _minute_date_filter_sql(start_date, end_date)
    if interval_minutes in {1, 5}:
        rows = conn.execute(
            """
            SELECT symbol, ? AS timeframe, trade_time, open, high, low, close, amount, volume
            FROM bars_minute
            WHERE symbol = ?
              AND interval_minutes = ?
            {date_filters}
            ORDER BY trade_time DESC
            LIMIT ?
            """.format(date_filters=date_filters),
            [timeframe, symbol.lower(), interval_minutes, *date_params, limit],
        ).fetchall()
        rows.reverse()
        return [BarRecord(**_bar_row(row)) for row in rows]

    rows = conn.execute(
        """
        WITH base AS (
            SELECT
                *,
                CASE
                    WHEN ? = 60 AND CAST(trade_time AS TIME) <= TIME '11:30:00'
                        THEN CAST(CAST(trade_time AS DATE) AS TIMESTAMP) + INTERVAL '11 hours 30 minutes'
                    WHEN ? = 60
                        THEN CAST(CAST(trade_time AS DATE) AS TIMESTAMP) + INTERVAL '15 hours'
                    ELSE
                        time_bucket(? * INTERVAL '1 minute', trade_time - INTERVAL '1 second') + ? * INTERVAL '1 minute'
                END AS bucket_time
            FROM bars_minute
            WHERE symbol = ?
              AND interval_minutes = 5
            {date_filters}
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
                sum(volume) AS volume
            FROM base
            GROUP BY symbol, bucket_time
        )
        SELECT symbol, ? AS timeframe, bucket_time, open, high, low, close, amount, volume
        FROM grouped
        ORDER BY bucket_time DESC
        LIMIT ?
        """.format(date_filters=date_filters),
        [interval_minutes, interval_minutes, interval_minutes, interval_minutes, symbol.lower(), *date_params, timeframe, limit],
    ).fetchall()
    rows.reverse()
    return [BarRecord(**_bar_row(row)) for row in rows]


def list_annotations(
    conn: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: str,
) -> list[AnnotationRecord]:
    rows = conn.execute(
        """
        SELECT id, symbol, timeframe, overlay_type, payload, created_at, updated_at
        FROM annotations
        WHERE symbol = ? AND timeframe = ?
        ORDER BY updated_at DESC
        """,
        [symbol.lower(), timeframe.upper()],
    ).fetchall()
    return [AnnotationRecord(**_annotation_row(row)) for row in rows]


def create_annotation(conn: duckdb.DuckDBPyConnection, item: AnnotationCreate) -> AnnotationRecord:
    annotation_id = str(uuid.uuid4())
    created_at = utc_now()
    updated_at = created_at
    payload = json.dumps(item.payload, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO annotations
        (id, symbol, timeframe, overlay_type, payload, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            annotation_id,
            item.symbol.lower(),
            item.timeframe.upper(),
            item.overlay_type,
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
    payload = item.payload if item.payload is not None else current.payload
    conn.execute(
        """
        UPDATE annotations
        SET overlay_type = ?, payload = ?, updated_at = ?
        WHERE id = ?
        """,
        [overlay_type, json.dumps(payload, ensure_ascii=False), utc_now(), annotation_id],
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
            ORDER BY is_default DESC, updated_at DESC
            """,
            [analysis_type],
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, name, analysis_type, version, params, is_default, created_at, updated_at
            FROM rule_profiles
            ORDER BY analysis_type, is_default DESC, updated_at DESC
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


def seed_default_profiles(conn: duckdb.DuckDBPyConnection) -> None:
    count = conn.execute("SELECT count(*) FROM rule_profiles").fetchone()[0]
    if count > 0:
        return
    defaults = [
        RuleProfileCreate(
            name="缠论默认分型",
            analysis_type="chan",
            version="0.1.0",
            params={"strict_fractal": False, "include_containment": False, "min_bars_for_bi": 5},
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
) -> tuple[int, int, int, list[str]]:
    errors: list[str] = []
    bars_imported = 0
    minute_bars_imported = 0
    files_imported = 0
    csv_path: str | None = None
    minute_csv_path: str | None = None

    try:
        with tempfile.NamedTemporaryFile("w", newline="", suffix=".csv", delete=False) as csv_file:
            csv_path = csv_file.name
            writer = csv.writer(csv_file)
            writer.writerow(["symbol", "market", "code", "trade_date", "open", "high", "low", "close", "amount", "volume"])
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
                except Exception as exc:  # noqa: BLE001
                    rel = file_path.relative_to(source_path) if file_path.is_relative_to(source_path) else file_path
                    errors.append(f"{rel}: {exc}")

        from .tdx import iter_minute_files, parse_minute_file

        minute_files = iter_minute_files(source_path, markets or ["sh", "sz", "bj"])
        if limit_files is not None:
            minute_files = minute_files[:limit_files]
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
                except Exception as exc:  # noqa: BLE001
                    rel = file_path.relative_to(source_path) if file_path.is_relative_to(source_path) else file_path
                    errors.append(f"{rel}: {exc}")

        if bars_imported == 0 and minute_bars_imported == 0:
            return files_imported, bars_imported, minute_bars_imported, errors

        with connect() as conn:
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
            except Exception:
                conn.execute("ROLLBACK")
                raise
    finally:
        if csv_path:
            Path(csv_path).unlink(missing_ok=True)
        if minute_csv_path:
            Path(minute_csv_path).unlink(missing_ok=True)
    return files_imported, bars_imported, minute_bars_imported, errors


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


def _date_filter_sql(start_date: date | None, end_date: date | None) -> tuple[str, list[date]]:
    filters: list[str] = []
    params: list[date] = []
    if start_date is not None:
        filters.append("AND trade_date >= ?")
        params.append(start_date)
    if end_date is not None:
        filters.append("AND trade_date <= ?")
        params.append(end_date)
    return ("\n            " + "\n            ".join(filters) if filters else ""), params


def _minute_date_filter_sql(start_date: date | None, end_date: date | None) -> tuple[str, list[date]]:
    filters: list[str] = []
    params: list[date] = []
    if start_date is not None:
        filters.append("AND CAST(trade_time AS DATE) >= ?")
        params.append(start_date)
    if end_date is not None:
        filters.append("AND CAST(trade_time AS DATE) <= ?")
        params.append(end_date)
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


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
