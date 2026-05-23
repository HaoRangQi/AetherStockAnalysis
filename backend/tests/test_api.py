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

    day_record = struct.pack("<IIIIIfII", 20260522, 1000, 1050, 990, 1030, 123456.0, 7890, 0)
    (source / "sh" / "lday" / "sh600000.day").write_bytes(day_record)
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
    assert imported.json()["bars_imported"] == 1
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
