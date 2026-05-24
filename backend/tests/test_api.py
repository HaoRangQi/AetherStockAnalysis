from __future__ import annotations

from pathlib import Path
import struct
import time

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app


def _create_tdx_fixture(tmp_path: Path) -> Path:
    source = tmp_path / "tdx" / "vipdoc"
    (source / "sh" / "lday").mkdir(parents=True)
    (source / "sh" / "fzline").mkdir(parents=True)
    (source / "sz" / "fzline").mkdir(parents=True)
    cache = source.parent / "T0002" / "hq_cache"
    cache.mkdir(parents=True)

    day_records = [
        struct.pack("<IIIIIfII", 20260511, 850, 900, 840, 890, 90000.0, 6800, 0),
        struct.pack("<IIIIIfII", 20260518, 900, 950, 890, 930, 100000.0, 7000, 0),
        struct.pack("<IIIIIfII", 20260519, 930, 980, 920, 970, 110000.0, 7200, 0),
        struct.pack("<IIIIIfII", 20260520, 970, 1010, 960, 1000, 120000.0, 7400, 0),
        struct.pack("<IIIIIfII", 20260521, 1000, 1040, 990, 1020, 130000.0, 7600, 0),
        struct.pack("<IIIIIfII", 20260522, 1000, 1050, 990, 1030, 123456.0, 7890, 0),
    ]
    (source / "sh" / "lday" / "sh600000.day").write_bytes(b"".join(day_records))
    raw_date = (2026 - 2004) * 2048 + 5 * 100 + 22
    _write_full_day_minute_file(source / "sh" / "fzline" / "sh600000.lc5")
    (source / "sz" / "fzline" / "sz000001.lc5").write_bytes(_minute_record(raw_date, 9 * 60 + 35, 0))
    tnf_record = bytearray(360)
    tnf_record[50:56] = b"600000"
    name = "浦发银行".encode("gb18030")
    tnf_record[80 : 80 + len(name)] = name
    (cache / "shs.tnf").write_bytes(tnf_record)
    return source


def _minute_record(raw_date: int, minutes: int, index: int) -> bytes:
    open_ = 10.0 + index / 100
    high = open_ + 0.2
    low = open_ - 0.1
    close = open_ + 0.05
    amount = 1000.0 + index
    volume = 100 + index
    return struct.pack("<HHfffffII", raw_date, minutes, open_, high, low, close, amount, volume, 0)


def _write_full_day_minute_file(path: Path) -> None:
    raw_date = (2026 - 2004) * 2048 + 5 * 100 + 22
    records: list[bytes] = []
    index = 0
    for start, end in [(9 * 60 + 35, 11 * 60 + 30), (13 * 60 + 5, 15 * 60)]:
        for minutes in range(start, end + 1, 5):
            records.append(_minute_record(raw_date, minutes, index))
            index += 1
    path.write_bytes(b"".join(records))


def _write_partial_and_offsession_minute_file(path: Path) -> None:
    raw_date = (2026 - 2004) * 2048 + 5 * 100 + 22
    records = [
        _minute_record(raw_date, 9 * 60 + 35, 0),
        _minute_record(raw_date, 9 * 60 + 40, 1),
        _minute_record(raw_date, 11 * 60 + 35, 2),
        _minute_record(raw_date, 12 * 60, 3),
        _minute_record(raw_date, 13 * 60, 4),
    ]
    path.write_bytes(b"".join(records))


def test_rule_profiles_and_annotations(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)

    profiles = client.get("/api/rule-profiles")
    assert profiles.status_code == 200
    assert {item["analysis_type"] for item in profiles.json()} == {"chan", "wave"}

    wave = client.get("/api/analysis/wave?symbol=sh000001&timeframe=D")
    assert wave.status_code == 200
    assert wave.json()["algorithm"] == "wave-zigzag"

    created = client.post(
        "/api/annotations",
        json={
            "symbol": "sh000001",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "测试标注"},
        },
    )
    assert created.status_code == 200
    annotation = created.json()
    assert annotation["payload"]["note"] == "测试标注"

    listed = client.get("/api/annotations?symbol=sh000001&timeframe=D")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == annotation["id"]

    updated = client.patch(
        f"/api/annotations/{annotation['id']}",
        json={"payload": {"note": "更新标注"}},
    )
    assert updated.status_code == 200
    assert updated.json()["payload"]["note"] == "更新标注"

    deleted = client.delete(f"/api/annotations/{annotation['id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}


def test_import_updates_names_and_chart_includes_minute_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert imported.status_code == 200
    assert imported.json()["bars_imported"] == 6
    assert imported.json()["minute_bars_imported"] == 48

    symbols = client.get("/api/symbols?q=600000&limit=5")
    assert symbols.status_code == 200
    assert symbols.json()[0]["name"] == "浦发银行"

    chart = client.get("/api/chart?symbol=sh600000&timeframe=5m&start_date=2026-05-22&end_date=2026-05-22")
    assert chart.status_code == 200
    payload = chart.json()
    assert len(payload["bars"]) == 48
    assert payload["bars"][0]["trade_date"] == "2026-05-22T09:35"
    assert payload["bars"][-1]["trade_date"] == "2026-05-22T15:00"
    assert payload["chan"]["timeframe"] == "5M"

    aggregated = client.get("/api/chart?symbol=sh600000&timeframe=15m&start_date=2026-05-22&end_date=2026-05-22")
    assert aggregated.status_code == 200
    aggregated_payload = aggregated.json()
    assert len(aggregated_payload["bars"]) == 16
    assert [bar["trade_date"] for bar in aggregated_payload["bars"][:2]] == ["2026-05-22T09:45", "2026-05-22T10:00"]
    assert [bar["trade_date"] for bar in aggregated_payload["bars"][-2:]] == ["2026-05-22T14:45", "2026-05-22T15:00"]
    assert aggregated_payload["bars"][0]["open"] == pytest.approx(10.0)
    assert aggregated_payload["bars"][0]["high"] == pytest.approx(10.22)
    assert aggregated_payload["bars"][0]["low"] == pytest.approx(9.9)
    assert aggregated_payload["bars"][0]["close"] == pytest.approx(10.07)
    assert aggregated_payload["bars"][0]["volume"] == 303
    assert aggregated_payload["chan"]["timeframe"] == "15M"

    aggregated30 = client.get("/api/chart?symbol=sh600000&timeframe=30m&start_date=2026-05-22&end_date=2026-05-22")
    assert aggregated30.status_code == 200
    assert [bar["trade_date"] for bar in aggregated30.json()["bars"]] == [
        "2026-05-22T10:00",
        "2026-05-22T10:30",
        "2026-05-22T11:00",
        "2026-05-22T11:30",
        "2026-05-22T13:30",
        "2026-05-22T14:00",
        "2026-05-22T14:30",
        "2026-05-22T15:00",
    ]

    aggregated60 = client.get("/api/chart?symbol=sh600000&timeframe=60m&start_date=2026-05-22&end_date=2026-05-22")
    assert aggregated60.status_code == 200
    assert [bar["trade_date"] for bar in aggregated60.json()["bars"]] == [
        "2026-05-22T10:30",
        "2026-05-22T11:30",
        "2026-05-22T14:00",
        "2026-05-22T15:00",
    ]

    skipped_market = client.get("/api/chart?symbol=sz000001&timeframe=5m&start_date=2026-05-22&end_date=2026-05-22")
    assert skipped_market.status_code == 200
    assert skipped_market.json()["bars"] == []

    latest_daily = client.get("/api/chart?symbol=sh600000&timeframe=D&limit=2")
    assert latest_daily.status_code == 200
    latest_daily_bars = latest_daily.json()["bars"]
    assert [bar["trade_date"] for bar in latest_daily_bars] == ["2026-05-21", "2026-05-22"]

    older_daily = client.get("/api/chart?symbol=sh600000&timeframe=D&limit=2&before=2026-05-21")
    assert older_daily.status_code == 200
    assert [bar["trade_date"] for bar in older_daily.json()["bars"]] == ["2026-05-19", "2026-05-20"]

    older_minute = client.get("/api/chart?symbol=sh600000&timeframe=5m&limit=1&before=2026-05-22T09:40")
    assert older_minute.status_code == 200
    older_minute_bars = older_minute.json()["bars"]
    assert len(older_minute_bars) == 1
    assert older_minute_bars[0]["trade_date"] == "2026-05-22T09:35"

    older_aggregated = client.get("/api/chart?symbol=sh600000&timeframe=15m&limit=1&before=2026-05-22T10:00")
    assert older_aggregated.status_code == 200
    assert [bar["trade_date"] for bar in older_aggregated.json()["bars"]] == ["2026-05-22T09:45"]

    afternoon_before = client.get("/api/chart?symbol=sh600000&timeframe=15m&limit=1&before=2026-05-22T13:30")
    assert afternoon_before.status_code == 200
    assert [bar["trade_date"] for bar in afternoon_before.json()["bars"]] == ["2026-05-22T13:15"]

    older_weekly = client.get("/api/chart?symbol=sh600000&timeframe=W&limit=1&before=2026-05-22")
    assert older_weekly.status_code == 200
    assert [bar["trade_date"] for bar in older_weekly.json()["bars"]] == ["2026-05-11"]

    invalid_before = client.get("/api/chart?symbol=sh600000&timeframe=D&before=not-a-date")
    assert invalid_before.status_code == 400
    assert "before 格式无效" in invalid_before.json()["detail"]

    health = client.get("/api/data/health")
    assert health.status_code == 200
    health_payload = health.json()
    assert health_payload["latest_trade_date"] == "2026-05-22"
    assert health_payload["daily_symbols"] == 1
    assert health_payload["daily_bars"] == 6
    assert health_payload["markets"][0]["market"] == "sh"
    assert health_payload["markets"][0]["latest_symbols"] == 1
    coverage = {item["timeframe"]: item for item in health_payload["timeframes"]}
    assert coverage["D"]["available"] is True
    assert coverage["5M"]["bars"] == 48
    assert coverage["15M"]["available"] is True
    assert coverage["15M"]["derived_from"] == "5 分钟聚合"
    assert any(item["title"] == "缺少深市日线" for item in health_payload["recommendations"])


def test_aggregated_minutes_filter_incomplete_and_offsession_buckets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    _write_partial_and_offsession_minute_file(source / "sh" / "fzline" / "sh600000.lc5")

    client = TestClient(app)
    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert imported.status_code == 200
    assert imported.json()["minute_bars_imported"] == 5

    raw_5m = client.get("/api/chart?symbol=sh600000&timeframe=5m&start_date=2026-05-22&end_date=2026-05-22")
    assert raw_5m.status_code == 200
    assert [bar["trade_date"] for bar in raw_5m.json()["bars"]] == [
        "2026-05-22T09:35",
        "2026-05-22T09:40",
        "2026-05-22T11:35",
        "2026-05-22T12:00",
        "2026-05-22T13:00",
    ]

    for timeframe in ["15m", "30m", "60m"]:
        aggregated = client.get(
            f"/api/chart?symbol=sh600000&timeframe={timeframe}&start_date=2026-05-22&end_date=2026-05-22"
        )
        assert aggregated.status_code == 200
        assert aggregated.json()["bars"] == []


def test_import_job_succeeds_and_reports_minute_progress(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"path": str(source), "markets": ["sh"]})
    assert created.status_code == 200
    job = created.json()
    assert job["id"]
    assert job["status"] in {"queued", "running"}
    assert "minute_bars_imported" in job

    finished = None
    for _ in range(50):
        polled = client.get(f"/api/imports/jobs/{job['id']}")
        assert polled.status_code == 200
        payload = polled.json()
        if payload["status"] in {"succeeded", "failed"}:
            finished = payload
            break
        time.sleep(0.05)

    assert finished is not None
    assert finished["status"] == "succeeded"
    assert finished["files_seen"] == 1
    assert finished["files_imported"] == 1
    assert finished["bars_imported"] == 6
    assert finished["minute_files_seen"] == 1
    assert finished["minute_files_imported"] == 1
    assert finished["minute_bars_imported"] == 48
    assert finished["symbols_imported"] == 1
    assert finished["source_path"] == str(source)
    assert finished["started_at"] is not None
    assert finished["finished_at"] is not None


def test_import_job_invalid_path_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"path": str(tmp_path / "missing")})
    assert created.status_code == 200
    job = created.json()

    finished = None
    for _ in range(50):
        polled = client.get(f"/api/imports/jobs/{job['id']}")
        assert polled.status_code == 200
        payload = polled.json()
        if payload["status"] in {"succeeded", "failed"}:
            finished = payload
            break
        time.sleep(0.05)

    assert finished is not None
    assert finished["status"] == "failed"
    assert finished["message"] == "数据源无效：没有找到可导入的日线文件。"
    assert finished["errors"] == ["数据源无效：没有找到可导入的日线文件。"]
    assert finished["finished_at"] is not None


def test_data_health_empty_database(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "empty.duckdb")

    client = TestClient(app)
    response = client.get("/api/data/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["latest_trade_date"] is None
    assert payload["daily_symbols"] == 0
    assert payload["daily_bars"] == 0
    assert payload["timeframes"][0]["timeframe"] == "D"
    assert payload["timeframes"][0]["available"] is False
    assert payload["recommendations"][0]["title"] == "缺少日线数据"
