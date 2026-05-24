from __future__ import annotations

from pathlib import Path
import struct

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app


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
    minute_records = [
        struct.pack("<HHfffffII", raw_date, 9 * 60 + 35, 10.0, 10.5, 9.9, 10.3, 1000.0, 100, 0),
        struct.pack("<HHfffffII", raw_date, 9 * 60 + 40, 10.3, 10.8, 10.2, 10.7, 1200.0, 120, 0),
    ]
    (source / "sh" / "fzline" / "sh600000.lc5").write_bytes(b"".join(minute_records))
    (source / "sz" / "fzline" / "sz000001.lc5").write_bytes(minute_records[0])
    tnf_record = bytearray(360)
    tnf_record[50:56] = b"600000"
    name = "浦发银行".encode("gb18030")
    tnf_record[80 : 80 + len(name)] = name
    (cache / "shs.tnf").write_bytes(tnf_record)

    client = TestClient(app)
    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert imported.status_code == 200
    assert imported.json()["bars_imported"] == 6
    assert imported.json()["minute_bars_imported"] == 2

    symbols = client.get("/api/symbols?q=600000&limit=5")
    assert symbols.status_code == 200
    assert symbols.json()[0]["name"] == "浦发银行"

    chart = client.get("/api/chart?symbol=sh600000&timeframe=5m&start_date=2026-05-22&end_date=2026-05-22")
    assert chart.status_code == 200
    payload = chart.json()
    assert len(payload["bars"]) == 2
    assert payload["bars"][0]["trade_date"] == "2026-05-22T09:35"
    assert payload["chan"]["timeframe"] == "5M"

    aggregated = client.get("/api/chart?symbol=sh600000&timeframe=15m&start_date=2026-05-22&end_date=2026-05-22")
    assert aggregated.status_code == 200
    aggregated_payload = aggregated.json()
    assert len(aggregated_payload["bars"]) == 1
    assert aggregated_payload["bars"][0]["trade_date"] == "2026-05-22T09:45"
    assert aggregated_payload["bars"][0]["open"] == 10.0
    assert aggregated_payload["bars"][0]["close"] == pytest.approx(10.7)
    assert aggregated_payload["chan"]["timeframe"] == "15M"

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
    assert coverage["5M"]["bars"] == 2
    assert coverage["15M"]["available"] is True
    assert coverage["15M"]["derived_from"] == "5 分钟聚合"
    assert any(item["title"] == "缺少深市日线" for item in health_payload["recommendations"])


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
