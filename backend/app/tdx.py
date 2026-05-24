from __future__ import annotations

import glob
import struct
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .schemas import DataSourceCandidate

MARKETS = ("sh", "sz", "bj")
DAY_RECORD_SIZE = 32
DAY_STRUCT = struct.Struct("<IIIIIfII")
MINUTE_RECORD_SIZE = 32
MINUTE_STRUCT = struct.Struct("<HHfffffII")
TNF_RECORD_SIZE = 360
TNF_CODE_OFFSET = 50
TNF_NAME_OFFSET = 80
TNF_NAME_SIZE = 40
TNF_FILES = {
    "shs.tnf": "sh",
    "szs.tnf": "sz",
    "bjs.tnf": "bj",
}


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    market: str
    code: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    amount: float
    volume: int


@dataclass(frozen=True)
class MinuteBar:
    symbol: str
    market: str
    code: str
    trade_time: datetime
    interval_minutes: int
    open: float
    high: float
    low: float
    close: float
    amount: float
    volume: int


def default_candidate_paths() -> list[tuple[str, Path]]:
    home = Path.home()
    paths: list[tuple[str, Path]] = []

    for match in glob.glob(
        str(home / "Library/Application Support/CrossOver/Bottles/*/drive_c/new_tdx/vipdoc")
    ):
        paths.append(("CrossOver 通达信", Path(match)))

    paths.extend(
        [
            ("CrossOver TDX_win", home / "Library/Application Support/CrossOver/Bottles/TDX_win/drive_c/new_tdx/vipdoc"),
            ("Windows C 盘通达信", Path("C:/new_tdx/vipdoc")),
            ("Windows Program Files 通达信", Path("C:/Program Files (x86)/new_tdx/vipdoc")),
            ("macOS 通达信容器", home / "Library/Containers/com.tdx.mac2022/Data/Documents/vipdoc"),
        ]
    )

    seen: set[str] = set()
    unique: list[tuple[str, Path]] = []
    for label, path in paths:
        key = str(path)
        if key not in seen:
            unique.append((label, path))
            seen.add(key)
    return unique


def inspect_source(path: Path, label: str = "手动数据源") -> DataSourceCandidate:
    expanded = path.expanduser()
    exists = expanded.exists()
    markets: list[str] = []
    daily_files = 0
    minute1_files = 0
    minute5_files = 0
    size_bytes = 0
    latest_modified: datetime | None = None

    if exists:
        for market in MARKETS:
            market_dir = expanded / market
            if market_dir.exists():
                markets.append(market)
            daily_paths = _market_files(market_dir / "lday", f"{market}*.day")
            minute1_paths = _market_files(market_dir / "minline", f"{market}*.lc1")
            minute5_paths = _market_files(market_dir / "fzline", f"{market}*.lc5")
            daily_files += len(daily_paths)
            minute1_files += len(minute1_paths)
            minute5_files += len(minute5_paths)
            size_bytes, latest_modified = _accumulate_file_stats(
                [*daily_paths, *minute1_paths, *minute5_paths],
                size_bytes,
                latest_modified,
            )

        tnf_paths = [
            cache_dir / filename
            for cache_dir in _candidate_hq_cache_dirs(expanded)
            for filename in TNF_FILES
        ]
        size_bytes, latest_modified = _accumulate_file_stats(tnf_paths, size_bytes, latest_modified)

    return DataSourceCandidate(
        path=str(expanded),
        exists=exists,
        valid=exists and daily_files > 0,
        label=label,
        markets=markets,
        daily_files=daily_files,
        minute1_files=minute1_files,
        minute5_files=minute5_files,
        size_bytes=size_bytes,
        latest_modified=latest_modified.isoformat(timespec="seconds") if latest_modified else None,
    )


def detect_sources() -> list[DataSourceCandidate]:
    return [inspect_source(path, label) for label, path in default_candidate_paths()]


def iter_daily_files(source_path: Path, markets: list[str]) -> list[Path]:
    files: list[Path] = []
    for market in markets:
        files.extend(sorted((source_path / market / "lday").glob(f"{market}*.day")))
    return files


def iter_minute_files(source_path: Path, markets: list[str]) -> list[Path]:
    files: list[Path] = []
    for market in markets:
        files.extend(sorted((source_path / market / "minline").glob(f"{market}*.lc1")))
        files.extend(sorted((source_path / market / "fzline").glob(f"{market}*.lc5")))
    return files


def parse_daily_file(file_path: Path) -> list[DailyBar]:
    stem = file_path.stem.lower()
    market = stem[:2]
    code = stem[2:]
    symbol = f"{market}{code}"
    bars: list[DailyBar] = []

    data = file_path.read_bytes()
    usable_length = len(data) - (len(data) % DAY_RECORD_SIZE)
    for offset in range(0, usable_length, DAY_RECORD_SIZE):
        raw_date, open_, high, low, close, amount, volume, _reserved = DAY_STRUCT.unpack_from(data, offset)
        try:
            trade_date = _parse_yyyymmdd(raw_date)
        except ValueError:
            continue
        bars.append(
            DailyBar(
                symbol=symbol,
                market=market,
                code=code,
                trade_date=trade_date,
                open=open_ / 100.0,
                high=high / 100.0,
                low=low / 100.0,
                close=close / 100.0,
                amount=float(amount),
                volume=int(volume),
            )
        )
    return bars


def parse_minute_file(file_path: Path) -> list[MinuteBar]:
    stem = file_path.stem.lower()
    market = stem[:2]
    code = stem[2:]
    symbol = f"{market}{code}"
    interval_minutes = 1 if file_path.suffix.lower() == ".lc1" else 5
    bars: list[MinuteBar] = []

    data = file_path.read_bytes()
    usable_length = len(data) - (len(data) % MINUTE_RECORD_SIZE)
    for offset in range(0, usable_length, MINUTE_RECORD_SIZE):
        raw_date, raw_time, open_, high, low, close, amount, volume, _reserved = MINUTE_STRUCT.unpack_from(data, offset)
        try:
            trade_time = _parse_minute_datetime(raw_date, raw_time)
        except ValueError:
            continue
        bars.append(
            MinuteBar(
                symbol=symbol,
                market=market,
                code=code,
                trade_time=trade_time,
                interval_minutes=interval_minutes,
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                amount=float(amount),
                volume=int(volume),
            )
        )
    return bars


def infer_kind(market: str, code: str) -> str:
    if market == "sh" and code.startswith("000"):
        return "index"
    if market == "sz" and code.startswith("399"):
        return "index"
    if code.startswith(("510", "511", "512", "513", "515", "516", "517", "518", "159")):
        return "etf"
    return "stock"


def infer_name(market: str, code: str) -> str:
    return f"{market.upper()}{code}"


def load_symbol_name_map(source_path: Path) -> dict[str, str]:
    """Read stock names from 通达信 T0002/hq_cache/*.tnf files."""
    names: dict[str, str] = {}
    for cache_dir in _candidate_hq_cache_dirs(source_path.expanduser()):
        if not cache_dir.exists():
            continue
        for filename, market in TNF_FILES.items():
            names.update(parse_tnf_symbol_names(cache_dir / filename, market))
    return names


def parse_tnf_symbol_names(file_path: Path, market: str) -> dict[str, str]:
    if not file_path.exists():
        return {}

    data = file_path.read_bytes()
    names: dict[str, str] = {}
    for record_start in range(0, len(data) - TNF_RECORD_SIZE + 1, TNF_RECORD_SIZE):
        code = _decode_ascii_field(data[record_start + TNF_CODE_OFFSET : record_start + TNF_NAME_OFFSET])
        if len(code) != 6 or not code.isdigit():
            continue

        name = _decode_gbk_field(
            data[record_start + TNF_NAME_OFFSET : record_start + TNF_NAME_OFFSET + TNF_NAME_SIZE]
        )
        if name:
            names[f"{market}{code}"] = name
    return names


def _market_files(path: Path, pattern: str) -> list[Path]:
    if not path.exists():
        return []
    return [item for item in path.glob(pattern) if item.is_file()]


def _accumulate_file_stats(
    paths: list[Path],
    size_bytes: int,
    latest_modified: datetime | None,
) -> tuple[int, datetime | None]:
    for file_path in paths:
        try:
            stat = file_path.stat()
        except OSError:
            continue
        size_bytes += stat.st_size
        modified = datetime.fromtimestamp(stat.st_mtime)
        if latest_modified is None or modified > latest_modified:
            latest_modified = modified
    return size_bytes, latest_modified


def _candidate_hq_cache_dirs(source_path: Path) -> list[Path]:
    candidates: list[Path] = []
    if source_path.name.lower() == "vipdoc":
        candidates.append(source_path.parent / "T0002" / "hq_cache")
    candidates.append(source_path / "T0002" / "hq_cache")
    candidates.append(source_path.parent / "T0002" / "hq_cache")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def _decode_ascii_field(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("ascii", errors="ignore").strip()


def _decode_gbk_field(raw: bytes) -> str:
    return raw.strip(b"\0").decode("gb18030", errors="ignore").strip()


def _parse_yyyymmdd(raw: int) -> date:
    text = str(raw)
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def _parse_minute_datetime(raw_date: int, raw_time: int) -> datetime:
    year = raw_date // 2048 + 2004
    month_day = raw_date % 2048
    month = month_day // 100
    day = month_day % 100
    hour = raw_time // 60
    minute = raw_time % 60
    return datetime(year, month, day, hour, minute)
