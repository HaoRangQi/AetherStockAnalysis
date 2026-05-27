-- DuckDB schema for AetherStockAnalysis.
-- Runtime database path: ~/.aether_stock_analysis/aether.duckdb

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
);

CREATE INDEX IF NOT EXISTS bars_daily_symbol_date_idx
ON bars_daily(symbol, trade_date);

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
);

CREATE INDEX IF NOT EXISTS bars_minute_symbol_interval_time_idx
ON bars_minute(symbol, interval_minutes, trade_time);

CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    first_date DATE,
    last_date DATE,
    bar_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS symbols_symbol_idx
ON symbols(symbol);

CREATE TABLE IF NOT EXISTS annotations (
    id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    overlay_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS annotations_symbol_timeframe_idx
ON annotations(symbol, timeframe);

CREATE TABLE IF NOT EXISTS rule_profiles (
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    analysis_type TEXT NOT NULL,
    version TEXT NOT NULL,
    params TEXT NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS rule_profiles_type_idx
ON rule_profiles(analysis_type);

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
);

CREATE INDEX IF NOT EXISTS import_jobs_id_idx
ON import_jobs(id);
