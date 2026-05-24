from __future__ import annotations

import struct
from pathlib import Path

import pytest

from app.tdx import (
    DAY_RECORD_SIZE,
    MINUTE_RECORD_SIZE,
    TNF_RECORD_SIZE,
    inspect_source,
    load_symbol_name_map,
    parse_daily_file,
    parse_minute_file,
    parse_tnf_symbol_names,
)


def test_parse_daily_file(tmp_path: Path) -> None:
    day_file = tmp_path / "sh600000.day"
    record = struct.pack(
        "<IIIIIfII",
        20260522,
        1000,
        1050,
        990,
        1030,
        123456.0,
        7890,
        0,
    )
    day_file.write_bytes(record)

    bars = parse_daily_file(day_file)

    assert len(bars) == 1
    assert len(day_file.read_bytes()) == DAY_RECORD_SIZE
    assert bars[0].symbol == "sh600000"
    assert bars[0].open == 10.0
    assert bars[0].high == 10.5
    assert bars[0].low == 9.9
    assert bars[0].close == pytest.approx(10.3)


def test_parse_tnf_symbol_names(tmp_path: Path) -> None:
    tnf_file = tmp_path / "shs.tnf"
    record = bytearray(TNF_RECORD_SIZE * 2)
    record[50:56] = b"600000"
    record[80:88] = "浦发银行".encode("gb18030")
    record[TNF_RECORD_SIZE + 50 : TNF_RECORD_SIZE + 56] = b"600519"
    record[TNF_RECORD_SIZE + 80 : TNF_RECORD_SIZE + 88] = "贵州茅台".encode("gb18030")
    tnf_file.write_bytes(record)

    names = parse_tnf_symbol_names(tnf_file, "sh")

    assert names == {"sh600000": "浦发银行", "sh600519": "贵州茅台"}


def test_parse_minute_file(tmp_path: Path) -> None:
    minute_file = tmp_path / "sh600000.lc5"
    raw_date = (2026 - 2004) * 2048 + 5 * 100 + 22
    raw_time = 9 * 60 + 35
    record = struct.pack(
        "<HHfffffII",
        raw_date,
        raw_time,
        10.0,
        10.5,
        9.9,
        10.3,
        123456.0,
        7890,
        0,
    )
    minute_file.write_bytes(record)

    bars = parse_minute_file(minute_file)

    assert len(bars) == 1
    assert len(minute_file.read_bytes()) == MINUTE_RECORD_SIZE
    assert bars[0].symbol == "sh600000"
    assert bars[0].interval_minutes == 5
    assert bars[0].trade_time.isoformat(timespec="minutes") == "2026-05-22T09:35"
    assert bars[0].close == pytest.approx(10.3)


def test_load_symbol_name_map_from_vipdoc_sibling_cache(tmp_path: Path) -> None:
    vipdoc = tmp_path / "new_tdx" / "vipdoc"
    cache = tmp_path / "new_tdx" / "T0002" / "hq_cache"
    cache.mkdir(parents=True)
    vipdoc.mkdir()
    record = bytearray(TNF_RECORD_SIZE)
    record[50:56] = b"000001"
    name = "平安银行".encode("gb18030")
    record[80 : 80 + len(name)] = name
    (cache / "szs.tnf").write_bytes(record)

    names = load_symbol_name_map(vipdoc)

    assert names["sz000001"] == "平安银行"


def test_inspect_source_scans_only_known_market_files(tmp_path: Path) -> None:
    vipdoc = tmp_path / "new_tdx" / "vipdoc"
    lday = vipdoc / "sh" / "lday"
    minline = vipdoc / "sh" / "minline"
    fzline = vipdoc / "sh" / "fzline"
    unrelated = vipdoc / "T0002" / "cache"
    cache = tmp_path / "new_tdx" / "T0002" / "hq_cache"
    for directory in [lday, minline, fzline, unrelated, cache]:
        directory.mkdir(parents=True)

    daily = lday / "sh600000.day"
    minute1 = minline / "sh600000.lc1"
    minute5 = fzline / "sh600000.lc5"
    tnf = cache / "shs.tnf"
    ignored_extension = minline / "sh600001.tmp"
    ignored_nested = unrelated / "large-cache.bin"

    daily.write_bytes(b"d" * 10)
    minute1.write_bytes(b"1" * 20)
    minute5.write_bytes(b"5" * 30)
    tnf.write_bytes(b"t" * 40)
    ignored_extension.write_bytes(b"x" * 100)
    ignored_nested.write_bytes(b"z" * 1000)

    health = inspect_source(vipdoc)

    assert health.valid is True
    assert health.markets == ["sh"]
    assert health.daily_files == 1
    assert health.minute1_files == 1
    assert health.minute5_files == 1
    assert health.size_bytes == 100
