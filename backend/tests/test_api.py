from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import struct
import time

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.schemas import AnnotationRecord, DataSourceCandidate, ImportJob
from app.storage import IMPORT_JOBS_RETENTION, connect, save_import_job


def test_cors_allows_vite_fallback_ports() -> None:
    client = TestClient(app)
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:5175",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5175"


def test_cors_rejects_untrusted_origins() -> None:
    client = TestClient(app)
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    assert response.text == "Disallowed CORS origin"


def test_openapi_documents_public_response_models() -> None:
    client = TestClient(app)

    health = client.get("/api/health")
    response = client.get("/openapi.json")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert paths["/api/health"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/HealthResponse"
    )
    assert paths["/api/symbols"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["items"][
        "$ref"
    ].endswith("/SymbolRecord")
    assert paths["/api/bars"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["items"][
        "$ref"
    ].endswith("/BarRecord")
    assert paths["/api/annotations/{annotation_id}"]["delete"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/DeleteResponse")


def test_current_source_treats_blank_config_path_as_unset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setattr("app.main.detect_sources", lambda: [])
    config.save_config({"source_path": "   "})

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    assert response.json() == {"path": None, "valid": False, "health": None}


def test_current_source_returns_unset_when_detected_candidates_have_blank_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "   "})
    blank_path_candidate = DataSourceCandidate(
        path="   ",
        exists=True,
        valid=True,
        label="blank-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [blank_path_candidate])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    assert response.json() == {"path": None, "valid": False, "health": None}


def test_current_source_returns_unset_when_detected_candidates_have_exists_false(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "   "})
    missing_candidate = DataSourceCandidate(
        path=str(tmp_path / "missing-vipdoc"),
        exists=False,
        valid=True,
        label="missing-but-valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [missing_candidate])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    assert response.json() == {"path": None, "valid": False, "health": None}


def test_current_source_uses_trimmed_configured_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    config.save_config({"source_path": f"  {source}  "})

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(source.resolve())
    assert payload["valid"] is True
    assert payload["health"]["path"] == str(source.resolve())
    assert payload["health"]["valid"] is True


def test_current_source_normalizes_relative_configured_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    relative_config_path = source.parent / ".." / "tdx" / source.name
    config.save_config({"source_path": f"  {relative_config_path}  "})

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    normalized_path = str(relative_config_path.resolve())
    assert payload["path"] == normalized_path
    assert payload["valid"] is True
    assert payload["health"]["path"] == normalized_path
    assert payload["health"]["valid"] is True


def test_current_source_falls_back_to_detected_when_config_path_is_blank(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "   "})
    detected_source = _create_tdx_fixture(tmp_path)
    detected_health = DataSourceCandidate(
        path=str(detected_source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=123,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [detected_health])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(detected_source.resolve())
    assert payload["valid"] is True
    assert payload["health"]["label"] == "detected"


def test_current_source_normalizes_detected_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({})
    source = _create_tdx_fixture(tmp_path)
    relative_candidate = source.resolve().parent / ".." / "tdx" / source.resolve().name
    detected_health = DataSourceCandidate(
        path=str(relative_candidate),
        exists=True,
        valid=True,
        label="detected-relative",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=321,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [detected_health])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    normalized_path = str(relative_candidate.resolve())
    assert payload["path"] == normalized_path
    assert payload["health"]["path"] == normalized_path


def test_current_source_returns_first_valid_detected_candidate_when_unset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    invalid_candidate = DataSourceCandidate(
        path=str(tmp_path / "invalid-vipdoc"),
        exists=True,
        valid=False,
        label="invalid",
        markets=[],
        daily_files=0,
        minute1_files=0,
        minute5_files=0,
        size_bytes=0,
        latest_modified=None,
    )
    valid_path = _create_tdx_fixture(tmp_path)
    valid_candidate = DataSourceCandidate(
        path=str(valid_path),
        exists=True,
        valid=True,
        label="valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=456,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [invalid_candidate, valid_candidate])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(valid_path.resolve())
    assert payload["valid"] is True
    assert payload["health"]["label"] == "valid"


def test_current_source_skips_valid_candidate_with_blank_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    blank_path_candidate = DataSourceCandidate(
        path="   ",
        exists=True,
        valid=True,
        label="blank-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    valid_path = _create_tdx_fixture(tmp_path)
    valid_candidate = DataSourceCandidate(
        path=str(valid_path),
        exists=True,
        valid=True,
        label="valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [blank_path_candidate, valid_candidate])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(valid_path.resolve())
    assert payload["health"]["label"] == "valid"


def test_current_source_skips_detected_candidate_with_exists_false(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    invalid_candidate = DataSourceCandidate(
        path=str(tmp_path / "missing-vipdoc"),
        exists=False,
        valid=True,
        label="missing-but-valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    valid_path = _create_tdx_fixture(tmp_path)
    valid_candidate = DataSourceCandidate(
        path=str(valid_path),
        exists=True,
        valid=True,
        label="valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [invalid_candidate, valid_candidate])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(valid_path.resolve())
    assert payload["health"]["label"] == "valid"


def test_current_source_skips_detected_candidate_with_invalid_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    invalid_path_candidate = DataSourceCandidate(
        path="bad\0path",
        exists=True,
        valid=True,
        label="invalid-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    valid_path = _create_tdx_fixture(tmp_path)
    valid_candidate = DataSourceCandidate(
        path=str(valid_path),
        exists=True,
        valid=True,
        label="valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [invalid_path_candidate, valid_candidate])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(valid_path.resolve())
    assert payload["health"]["label"] == "valid"


def test_current_source_skips_stale_detected_candidate_with_no_daily_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_path = tmp_path / "stale-vipdoc"
    stale_path.mkdir(parents=True)
    stale_candidate = DataSourceCandidate(
        path=str(stale_path),
        exists=True,
        valid=True,
        label="stale-detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    valid_path = _create_tdx_fixture(tmp_path)
    valid_candidate = DataSourceCandidate(
        path=str(valid_path),
        exists=True,
        valid=True,
        label="valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [stale_candidate, valid_candidate])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(valid_path.resolve())
    assert payload["health"]["label"] == "valid"


def test_current_source_returns_unset_when_detected_candidates_are_stale(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_path = tmp_path / "stale-vipdoc"
    stale_path.mkdir(parents=True)
    stale_candidate = DataSourceCandidate(
        path=str(stale_path),
        exists=True,
        valid=True,
        label="stale-detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [stale_candidate])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    assert response.json() == {"path": None, "valid": False, "health": None}


def test_current_source_returns_unset_when_detected_candidates_have_invalid_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({})
    invalid_path_candidate = DataSourceCandidate(
        path="bad\0path",
        exists=True,
        valid=True,
        label="invalid-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [invalid_path_candidate])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    assert response.json() == {"path": None, "valid": False, "health": None}


def test_current_source_reports_health_for_path_with_daily_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = tmp_path / "daily-only" / "vipdoc"
    (source / "sh" / "lday").mkdir(parents=True)
    (source / "sh" / "lday" / "sh600000.day").write_bytes(b"\x00" * 32)
    config.save_config({"source_path": str(source)})
    monkeypatch.setattr("app.main.detect_sources", lambda: [])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(source.resolve())
    assert payload["valid"] is True
    assert payload["health"]["valid"] is True
    assert payload["health"]["daily_files"] == 1
    assert payload["health"]["minute1_files"] == 0
    assert payload["health"]["minute5_files"] == 0
    assert payload["health"]["markets"] == ["sh"]


def test_current_source_reports_invalid_configured_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    missing_source = tmp_path / "missing-vipdoc"
    config.save_config({"source_path": str(missing_source)})
    monkeypatch.setattr("app.main.detect_sources", lambda: [])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(missing_source)
    assert payload["valid"] is False
    assert payload["health"]["valid"] is False
    assert payload["health"]["exists"] is False


def test_current_source_falls_back_to_detected_when_configured_source_has_no_daily_files(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    config.save_config({"source_path": str(stale_source)})
    detected_source = _create_tdx_fixture(tmp_path)
    detected_health = DataSourceCandidate(
        path=str(detected_source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [detected_health])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(detected_source.resolve())
    assert payload["valid"] is True
    assert payload["health"]["label"] == "detected"


def test_current_source_reports_invalid_when_configured_source_has_no_daily_files_and_no_detected(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    config.save_config({"source_path": str(stale_source)})
    monkeypatch.setattr("app.main.detect_sources", lambda: [])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(stale_source.resolve())
    assert payload["valid"] is False
    assert payload["health"]["path"] == str(stale_source.resolve())
    assert payload["health"]["valid"] is False
    assert payload["health"]["exists"] is True
    assert payload["health"]["daily_files"] == 0


def test_current_source_falls_back_to_detected_when_config_path_invalid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    config.save_config({"source_path": "bad\0path"})
    detected_health = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=123,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [detected_health])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(source.resolve())
    assert payload["valid"] is True
    assert payload["health"]["label"] == "detected"


def test_current_source_uses_valid_detected_when_config_path_invalid_and_first_detected_is_stale(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "bad\0path"})
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    stale_detected = DataSourceCandidate(
        path=str(stale_source),
        exists=True,
        valid=True,
        label="stale-detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    source = _create_tdx_fixture(tmp_path)
    detected_health = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [stale_detected, detected_health])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(source.resolve())
    assert payload["valid"] is True
    assert payload["health"]["label"] == "detected"


def test_current_source_uses_valid_detected_when_config_path_invalid_and_detected_candidates_mixed_invalid(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "bad\0path"})
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    blank_path_candidate = DataSourceCandidate(
        path="   ",
        exists=True,
        valid=True,
        label="blank-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    missing_candidate = DataSourceCandidate(
        path=str(tmp_path / "missing-vipdoc"),
        exists=False,
        valid=True,
        label="missing-but-valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    stale_candidate = DataSourceCandidate(
        path=str(stale_source),
        exists=True,
        valid=True,
        label="stale-detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    source = _create_tdx_fixture(tmp_path)
    detected_health = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected-valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr(
        "app.main.detect_sources",
        lambda: [blank_path_candidate, missing_candidate, stale_candidate, detected_health],
    )

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(source.resolve())
    assert payload["valid"] is True
    assert payload["health"]["label"] == "detected-valid"


def test_current_source_returns_unset_when_config_path_invalid_and_no_detected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "bad\0path"})
    monkeypatch.setattr("app.main.detect_sources", lambda: [])

    client = TestClient(app)
    response = client.get("/api/sources/current")

    assert response.status_code == 200
    assert response.json() == {"path": None, "valid": False, "health": None}


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


def _create_tdx_day_only_fixture(tmp_path: Path) -> Path:
    source = tmp_path / "tdx" / "vipdoc"
    (source / "sh" / "lday").mkdir(parents=True)
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


def _insert_rule_profile_test_bars() -> None:
    rows = [
        ("sh600001", "sh", "600001", "2026-06-01", 9.5, 10.0, 8.0, 9.0, 1000.0, 100),
        ("sh600001", "sh", "600001", "2026-06-02", 10.5, 12.0, 9.0, 11.0, 1000.0, 100),
        ("sh600001", "sh", "600001", "2026-06-03", 8.5, 11.0, 7.0, 8.0, 1000.0, 100),
        ("sh600001", "sh", "600001", "2026-06-04", 11.5, 13.0, 9.0, 12.0, 1000.0, 100),
        ("sh600001", "sh", "600001", "2026-06-05", 9.5, 10.0, 8.0, 9.0, 1000.0, 100),
    ]
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO bars_daily
            (symbol, market, code, trade_date, open, high, low, close, amount, volume)
            VALUES (?, ?, ?, ?::DATE, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _insert_limit_backtest_test_bars() -> None:
    rows = [
        ("sh600002", "sh", "600002", "2026-07-01", 9.8, 10.0, 9.0, 10.0, 1000.0, 100),
        ("sh600002", "sh", "600002", "2026-07-02", 10.2, 11.0, 10.0, 10.5, 1000.0, 100),
        ("sh600002", "sh", "600002", "2026-07-03", 10.4, 11.0, 9.0, 10.0, 1000.0, 100),
        ("sh600002", "sh", "600002", "2026-07-04", 9.0, 10.0, 8.0, 9.0, 1000.0, 100),
        ("sh600002", "sh", "600002", "2026-07-05", 8.2, 9.0, 8.0, 8.1, 1000.0, 100),
    ]
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO bars_daily
            (symbol, market, code, trade_date, open, high, low, close, amount, volume)
            VALUES (?, ?, ?, ?::DATE, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _insert_duplicate_daily_test_bars() -> None:
    rows = [
        ("sh600003", "sh", "600003", "2026-08-03", 10.0, 10.4, 9.8, 10.2, 1000.0, 100),
        ("sh600003", "sh", "600003", "2026-08-04", 10.2, 10.8, 10.1, 10.6, 1200.0, 120),
        ("sh600003", "sh", "600003", "2026-08-04", 10.2, 10.8, 10.1, 10.6, 1200.0, 120),
        ("sh600003", "sh", "600003", "2026-08-05", 10.6, 11.0, 10.5, 10.9, 1400.0, 140),
    ]
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO bars_daily
            (symbol, market, code, trade_date, open, high, low, close, amount, volume)
            VALUES (?, ?, ?, ?::DATE, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _insert_cross_period_daily_test_bars() -> None:
    rows = [
        ("sh600005", "sh", "600005", "2026-07-30", 9.8, 10.2, 9.7, 10.0, 900.0, 90),
        ("sh600005", "sh", "600005", "2026-07-31", 10.0, 10.5, 9.9, 10.4, 950.0, 95),
        ("sh600005", "sh", "600005", "2026-08-03", 10.4, 10.8, 10.2, 10.7, 1000.0, 100),
        ("sh600005", "sh", "600005", "2026-08-04", 10.7, 11.0, 10.6, 10.9, 1100.0, 110),
        ("sh600005", "sh", "600005", "2026-08-04", 10.7, 11.0, 10.6, 10.9, 1100.0, 110),
    ]
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO bars_daily
            (symbol, market, code, trade_date, open, high, low, close, amount, volume)
            VALUES (?, ?, ?, ?::DATE, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _insert_duplicate_minute_test_bars() -> None:
    rows = [
        ("sh600004", "sh", "600004", "2026-08-06 09:35:00", 5, 10.0, 10.2, 9.9, 10.1, 1000.0, 100),
        ("sh600004", "sh", "600004", "2026-08-06 09:40:00", 5, 10.1, 10.3, 10.0, 10.2, 1100.0, 110),
        ("sh600004", "sh", "600004", "2026-08-06 09:40:00", 5, 10.1, 10.3, 10.0, 10.2, 1100.0, 110),
        ("sh600004", "sh", "600004", "2026-08-06 09:45:00", 5, 10.2, 10.4, 10.1, 10.3, 1200.0, 120),
    ]
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO bars_minute
            (symbol, market, code, trade_time, interval_minutes, open, high, low, close, amount, volume)
            VALUES (?, ?, ?, ?::TIMESTAMP, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def test_rule_profiles_and_annotations(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)

    profiles = client.get("/api/rule-profiles")
    assert profiles.status_code == 200
    assert {item["analysis_type"] for item in profiles.json()} == {"chan", "wave"}
    wave_profiles = client.get("/api/rule-profiles?analysis_type=wave")
    assert wave_profiles.status_code == 200
    assert wave_profiles.json()
    assert {item["analysis_type"] for item in wave_profiles.json()} == {"wave"}

    invalid_profiles = client.get("/api/rule-profiles?analysis_type=invalid")
    assert invalid_profiles.status_code == 422
    invalid_profile_create = client.post(
        "/api/rule-profiles",
        json={
            "name": "非法规则类型",
            "analysis_type": "invalid",
            "version": "0.1.0",
            "params": {},
            "is_default": False,
        },
    )
    assert invalid_profile_create.status_code == 422

    wave = client.get("/api/analysis/wave?symbol=sh000001&timeframe=D")
    assert wave.status_code == 200
    wave_payload = wave.json()
    assert wave_payload["algorithm"] == "wave-zigzag"
    assert wave_payload["version"] == "0.1.0"
    assert wave_payload["params"] == {"threshold_pct": 5.0, "min_swing_bars": 3}
    assert wave_payload["generated_at"] is not None

    coarse_wave = client.get("/api/analysis/wave?symbol=sh000001&timeframe=D&threshold_pct=8")
    assert coarse_wave.status_code == 200
    assert coarse_wave.json()["threshold_pct"] == 8.0
    assert coarse_wave.json()["params"] == {"threshold_pct": 8.0, "min_swing_bars": 3}

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
        json={"payload": {"note": "更新标注", "locked": True, "confirmed": True}},
    )
    assert updated.status_code == 200
    assert updated.json()["payload"]["note"] == "更新标注"
    assert updated.json()["payload"]["locked"] is True
    assert updated.json()["payload"]["confirmed"] is True

    locked_delete = client.delete(f"/api/annotations/{annotation['id']}")
    assert locked_delete.status_code == 409
    assert "标注已锁定" in locked_delete.json()["detail"]

    unlocked = client.patch(
        f"/api/annotations/{annotation['id']}",
        json={"payload": {"note": "更新标注", "locked": False, "confirmed": True}},
    )
    assert unlocked.status_code == 200
    assert unlocked.json()["payload"]["locked"] is False

    manual_wave = client.post(
        "/api/annotations",
        json={
            "symbol": "sh000001",
            "timeframe": "D",
            "overlay_type": "wave",
            "payload": {
                "active": True,
                "confirmed": True,
                "threshold_pct": 5,
                "wave_algorithm": "wave-zigzag",
                "wave_version": "0.1.0",
                "pivots": [
                    {"index": 0, "trade_date": "2026-01-01", "price": 10.0, "kind": "bottom", "wave_no": 1},
                    {"index": 3, "trade_date": "2026-01-04", "price": 13.0, "kind": "top", "wave_no": 2},
                ],
            },
        },
    )
    assert manual_wave.status_code == 200
    assert manual_wave.json()["overlay_type"] == "wave"
    assert manual_wave.json()["payload"]["pivots"][1]["wave_no"] == 2
    manual_wave_analysis = client.get("/api/analysis/wave?symbol=sh000001&timeframe=D")
    assert manual_wave_analysis.status_code == 200
    manual_wave_payload = manual_wave_analysis.json()
    assert manual_wave_payload["algorithm"] == "manual-wave"
    assert manual_wave_payload["threshold_pct"] == 5
    assert len(manual_wave_payload["pivots"]) == 2

    newer_manual_wave = client.post(
        "/api/annotations",
        json={
            "symbol": "sh000001",
            "timeframe": "D",
            "overlay_type": "wave",
            "payload": {
                "active": True,
                "threshold_pct": 8,
                "pivots": [
                    {"index": 0, "trade_date": "2026-01-01", "price": 10.0, "kind": "start", "wave_no": 1},
                    {"index": 4, "trade_date": "2026-01-05", "price": 14.0, "kind": "top", "wave_no": 2},
                ],
            },
        },
    )
    assert newer_manual_wave.status_code == 200
    newer_manual_wave_analysis = client.get("/api/analysis/wave?symbol=sh000001&timeframe=D")
    assert newer_manual_wave_analysis.status_code == 200
    newer_manual_wave_payload = newer_manual_wave_analysis.json()
    assert newer_manual_wave_payload["algorithm"] == "manual-wave"
    assert newer_manual_wave_payload["threshold_pct"] == 8
    assert newer_manual_wave_payload["pivots"][1]["trade_date"] == "2026-01-05"

    superseded_wave = client.get(f"/api/annotations?symbol=sh000001&timeframe=D")
    assert superseded_wave.status_code == 200
    wave_payloads = {
        item["id"]: item["payload"]
        for item in superseded_wave.json()
        if item["overlay_type"] == "wave"
    }
    assert wave_payloads[manual_wave.json()["id"]]["active"] is False
    assert wave_payloads[manual_wave.json()["id"]]["deactivated_reason"] == "superseded_by_new_manual_structure"
    assert wave_payloads[newer_manual_wave.json()["id"]]["active"] is True

    listed_with_wave = client.get("/api/annotations?symbol=sh000001&timeframe=D")
    assert listed_with_wave.status_code == 200
    assert any(item["overlay_type"] == "wave" for item in listed_with_wave.json())

    reactivated_wave = client.patch(
        f"/api/annotations/{manual_wave.json()['id']}",
        json={"payload": {**manual_wave.json()["payload"], "active": True}},
    )
    assert reactivated_wave.status_code == 200
    wave_items_after_reactivation = client.get("/api/annotations?symbol=sh000001&timeframe=D")
    assert wave_items_after_reactivation.status_code == 200
    wave_payloads_after_reactivation = {
        item["id"]: item["payload"]
        for item in wave_items_after_reactivation.json()
        if item["overlay_type"] == "wave"
    }
    assert wave_payloads_after_reactivation[manual_wave.json()["id"]]["active"] is True
    assert wave_payloads_after_reactivation[newer_manual_wave.json()["id"]]["active"] is False
    assert (
        wave_payloads_after_reactivation[newer_manual_wave.json()["id"]]["deactivated_reason"]
        == "superseded_by_new_manual_structure"
    )
    reactivated_manual_wave_analysis = client.get("/api/analysis/wave?symbol=sh000001&timeframe=D")
    assert reactivated_manual_wave_analysis.status_code == 200
    assert reactivated_manual_wave_analysis.json()["algorithm"] == "manual-wave"
    assert reactivated_manual_wave_analysis.json()["threshold_pct"] == 5

    disabled_wave = client.patch(
        f"/api/annotations/{manual_wave.json()['id']}",
        json={"payload": {**reactivated_wave.json()["payload"], "active": False}},
    )
    assert disabled_wave.status_code == 200
    assert disabled_wave.json()["payload"]["active"] is False
    fallback_auto_wave = client.get("/api/analysis/wave?symbol=sh000001&timeframe=D")
    assert fallback_auto_wave.status_code == 200
    assert fallback_auto_wave.json()["algorithm"] == "wave-zigzag"

    empty_notes = client.get("/api/review-notes?symbol=sh000001&timeframe=D")
    assert empty_notes.status_code == 200
    assert empty_notes.json() == []

    review_note = client.post(
        "/api/review-notes",
        json={
            "symbol": "sh000001",
            "timeframe": "D",
            "title": "上证复盘",
            "content": "中枢震荡后观察三买。",
            "tags": ["中枢", "三买"],
            "payload": {"chan_version": "0.1.0", "wave_version": "0.1.0"},
        },
    )
    assert review_note.status_code == 200
    note_payload = review_note.json()
    assert note_payload["overlay_type"] == "review_note"
    assert note_payload["payload"]["title"] == "上证复盘"
    assert note_payload["payload"]["content"] == "中枢震荡后观察三买。"
    assert note_payload["payload"]["tags"] == ["中枢", "三买"]
    assert note_payload["payload"]["source"] == "review-panel"

    listed_notes = client.get("/api/review-notes?symbol=sh000001&timeframe=D")
    assert listed_notes.status_code == 200
    assert listed_notes.json()[0]["id"] == note_payload["id"]

    deleted_note = client.delete(f"/api/annotations/{note_payload['id']}")
    assert deleted_note.status_code == 200
    assert deleted_note.json() == {"deleted": True}

    notes_after_delete = client.get("/api/review-notes?symbol=sh000001&timeframe=D")
    assert notes_after_delete.status_code == 200
    assert notes_after_delete.json() == []


def test_annotations_and_review_notes_list_order_tie_by_id_desc(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    imported = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {},
            "annotations": [
                {
                    "id": "tie-note-a",
                    "symbol": "sh600001",
                    "timeframe": "D",
                    "overlay_type": "note",
                    "payload": {"note": "A"},
                    "created_at": "2026-06-01T10:00:00Z",
                    "updated_at": "2026-06-01T10:00:00Z",
                },
                {
                    "id": "tie-note-b",
                    "symbol": "sh600001",
                    "timeframe": "D",
                    "overlay_type": "note",
                    "payload": {"note": "B"},
                    "created_at": "2026-06-01T10:00:00Z",
                    "updated_at": "2026-06-01T10:00:00Z",
                },
                {
                    "id": "tie-review-a",
                    "symbol": "sh600001",
                    "timeframe": "D",
                    "overlay_type": "review_note",
                    "payload": {"title": "A", "content": "A", "tags": []},
                    "created_at": "2026-06-01T10:00:00Z",
                    "updated_at": "2026-06-01T10:00:00Z",
                },
                {
                    "id": "tie-review-b",
                    "symbol": "sh600001",
                    "timeframe": "D",
                    "overlay_type": "review_note",
                    "payload": {"title": "B", "content": "B", "tags": []},
                    "created_at": "2026-06-01T10:00:00Z",
                    "updated_at": "2026-06-01T10:00:00Z",
                },
            ],
            "rule_profiles": [],
        },
    )
    assert imported.status_code == 200

    annotations = client.get("/api/annotations?symbol=sh600001&timeframe=D")
    assert annotations.status_code == 200
    note_ids = [item["id"] for item in annotations.json() if item["overlay_type"] == "note"]
    assert note_ids == ["tie-note-b", "tie-note-a"]

    review_notes = client.get("/api/review-notes?symbol=sh600001&timeframe=D")
    assert review_notes.status_code == 200
    review_ids = [item["id"] for item in review_notes.json()]
    assert review_ids == ["tie-review-b", "tie-review-a"]


def test_default_rule_profiles_are_applied_to_analysis(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    client = TestClient(app)

    default_chan = client.get("/api/analysis/chan?symbol=sh600001&timeframe=D")
    assert default_chan.status_code == 200
    default_chan_payload = default_chan.json()
    assert default_chan_payload["params"]["min_bars_for_bi"] == 5
    assert default_chan_payload["bis"] == []

    custom_chan_profile = client.post(
        "/api/rule-profiles",
        json={
            "name": "短笔规则",
            "analysis_type": "chan",
            "version": "0.5.0-test",
            "params": {
                "strict_fractal": False,
                "include_containment": True,
                "min_bars_for_bi": 1,
                "min_bis_for_segment": 2,
                "segment_step_bis": 1,
                "min_bis_for_zhongshu": 2,
                "zhongshu_step_bis": 1,
            },
            "is_default": True,
        },
    )
    assert custom_chan_profile.status_code == 200

    custom_chan = client.get("/api/analysis/chan?symbol=sh600001&timeframe=D")
    assert custom_chan.status_code == 200
    custom_chan_payload = custom_chan.json()
    assert custom_chan_payload["params"]["min_bars_for_bi"] == 1
    assert custom_chan_payload["params"]["min_bis_for_segment"] == 2
    assert [(item["start_index"], item["end_index"]) for item in custom_chan_payload["bis"]] == [(1, 2), (2, 3)]

    custom_wave_profile = client.post(
        "/api/rule-profiles",
        json={
            "name": "大浪默认",
            "analysis_type": "wave",
            "version": "0.1.0-test",
            "params": {"zigzag_threshold_pct": 8, "min_swing_bars": 4},
            "is_default": True,
        },
    )
    assert custom_wave_profile.status_code == 200

    default_wave = client.get("/api/analysis/wave?symbol=sh600001&timeframe=D")
    assert default_wave.status_code == 200
    assert default_wave.json()["threshold_pct"] == 8.0
    assert default_wave.json()["params"] == {"threshold_pct": 8.0, "min_swing_bars": 4}

    explicit_wave = client.get("/api/analysis/wave?symbol=sh600001&timeframe=D&threshold_pct=3")
    assert explicit_wave.status_code == 200
    assert explicit_wave.json()["threshold_pct"] == 3.0
    assert explicit_wave.json()["params"] == {"threshold_pct": 3.0, "min_swing_bars": 4}

    chart = client.get("/api/chart?symbol=sh600001&timeframe=D")
    assert chart.status_code == 200
    chart_payload = chart.json()
    assert chart_payload["chan"]["params"]["min_bars_for_bi"] == 1
    assert chart_payload["wave"]["threshold_pct"] == 8.0
    assert chart_payload["wave"]["params"]["min_swing_bars"] == 4

    explicit_chart = client.get("/api/chart?symbol=sh600001&timeframe=D&threshold_pct=3")
    assert explicit_chart.status_code == 200
    assert explicit_chart.json()["wave"]["threshold_pct"] == 3.0
    assert explicit_chart.json()["wave"]["params"] == {"threshold_pct": 3.0, "min_swing_bars": 4}

    backtest = client.get("/api/backtests/structure?symbol=sh600001&timeframe=D&strategy=wave_zigzag_reversal")
    assert backtest.status_code == 200
    assert backtest.json()["params"]["wave_threshold_pct"] == 8.0
    assert backtest.json()["params"]["wave_min_swing_bars"] == 4

    explicit_backtest = client.get(
        "/api/backtests/structure?symbol=sh600001&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=3"
    )
    assert explicit_backtest.status_code == 200
    assert explicit_backtest.json()["params"]["wave_threshold_pct"] == 3.0
    assert explicit_backtest.json()["params"]["wave_min_swing_bars"] == 4


def test_user_backup_exports_and_imports_user_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    saved = client.post("/api/sources", json={"path": str(source)})
    assert saved.status_code == 200

    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert imported.status_code == 200
    assert imported.json()["bars_imported"] == 6

    annotation = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "备份标注"},
        },
    )
    assert annotation.status_code == 200

    review_note = client.post(
        "/api/review-notes",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "title": "备份复盘",
            "content": "观察中枢震荡。",
            "tags": ["中枢"],
            "payload": {"window": {"start": "2026-05-18", "end": "2026-05-22"}},
        },
    )
    assert review_note.status_code == 200

    profile = client.post(
        "/api/rule-profiles",
        json={
            "name": "本地 ZigZag",
            "analysis_type": "wave",
            "version": "0.2.0",
            "params": {"threshold_pct": 8},
            "is_default": True,
        },
    )
    assert profile.status_code == 200

    exported = client.get("/api/backups/user")
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["schema_version"] == 1
    assert payload["config"]["source_path"] == str(source)
    assert payload["exported_at"] is not None
    assert len(payload["annotations"]) == 2
    exported_annotations = {item["overlay_type"]: item for item in payload["annotations"]}
    assert exported_annotations["note"]["payload"] == {"note": "备份标注"}
    assert exported_annotations["review_note"]["payload"]["title"] == "备份复盘"
    assert exported_annotations["review_note"]["payload"]["content"] == "观察中枢震荡。"
    assert exported_annotations["review_note"]["payload"]["tags"] == ["中枢"]
    assert any(item["name"] == "本地 ZigZag" for item in payload["rule_profiles"])
    assert "bars" not in payload
    assert "symbols" not in payload
    payload["config"]["unexpected_local_key"] = "不应导入"

    unsupported = client.post("/api/backups/user", json={**payload, "schema_version": 2})
    assert unsupported.status_code == 400
    assert unsupported.json()["detail"] == "不支持的备份文件版本。"
    invalid_backup = client.post(
        "/api/backups/user",
        json={
            **payload,
            "rule_profiles": [
                {
                    **payload["rule_profiles"][0],
                    "analysis_type": "invalid",
                }
            ],
        },
    )
    assert invalid_backup.status_code == 422

    old_manual_chan_id = "backup-manual-chan-old"
    newer_manual_chan_id = "backup-manual-chan-newer"
    old_manual_wave_id = "backup-manual-wave-old"
    newer_manual_wave_id = "backup-manual-wave-newer"
    payload["annotations"].extend(
        [
            {
                "id": old_manual_chan_id,
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "chan",
                "payload": {
                    "active": True,
                    "fractals": [
                        {"index": 1, "trade_date": "2026-05-18", "price": 8.9, "kind": "bottom"},
                        {"index": 3, "trade_date": "2026-05-20", "price": 10.1, "kind": "top"},
                    ],
                },
                "created_at": "2026-05-20T10:00:00Z",
                "updated_at": "2026-05-20T10:00:00Z",
            },
            {
                "id": newer_manual_chan_id,
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "chan",
                "payload": {
                    "active": True,
                    "fractals": [
                        {"index": 2, "trade_date": "2026-05-19", "price": 9.2, "kind": "bottom"},
                        {"index": 4, "trade_date": "2026-05-21", "price": 10.4, "kind": "top"},
                    ],
                },
                "created_at": "2026-05-21T10:00:00Z",
                "updated_at": "2026-05-21T10:00:00Z",
            },
            {
                "id": old_manual_wave_id,
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "wave",
                "payload": {
                    "active": True,
                    "threshold_pct": 5,
                    "pivots": [
                        {"index": 0, "trade_date": "2026-05-17", "price": 8.6, "kind": "start", "wave_no": 1},
                        {"index": 1, "trade_date": "2026-05-18", "price": 8.9, "kind": "bottom", "wave_no": 2},
                        {"index": 3, "trade_date": "2026-05-20", "price": 10.1, "kind": "top", "wave_no": 3},
                    ],
                },
                "created_at": "2026-05-20T11:00:00Z",
                "updated_at": "2026-05-20T11:00:00Z",
            },
            {
                "id": newer_manual_wave_id,
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "wave",
                "payload": {
                    "active": True,
                    "threshold_pct": 8,
                    "pivots": [
                        {"index": 0, "trade_date": "2026-05-17", "price": 8.6, "kind": "start", "wave_no": 1},
                        {"index": 2, "trade_date": "2026-05-19", "price": 9.2, "kind": "bottom", "wave_no": 2},
                        {"index": 4, "trade_date": "2026-05-21", "price": 10.4, "kind": "top", "wave_no": 3},
                    ],
                },
                "created_at": "2026-05-21T11:00:00Z",
                "updated_at": "2026-05-21T11:00:00Z",
            },
        ]
    )

    monkeypatch.setattr(config, "APP_DIR", tmp_path / "restored")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "restored" / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "restored" / "test.duckdb")

    restored = client.post("/api/backups/user", json=payload)
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": True,
        "annotations_imported": 6,
        "rule_profiles_imported": len(payload["rule_profiles"]),
    }
    assert config.load_config() == {"source_path": str(source)}

    ignored_config = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {"unexpected_local_key": "不应导入"},
            "annotations": [],
            "rule_profiles": [],
        },
    )
    assert ignored_config.status_code == 200
    assert ignored_config.json()["config_imported"] is False
    assert config.load_config() == {"source_path": str(source)}

    restored_annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert restored_annotations.status_code == 200
    restored_items = restored_annotations.json()
    assert any(item["payload"] == {"note": "备份标注"} for item in restored_items)
    restored_notes = client.get("/api/review-notes?symbol=sh600000&timeframe=D")
    assert restored_notes.status_code == 200
    assert restored_notes.json()[0]["payload"]["title"] == "备份复盘"
    assert restored_notes.json()[0]["payload"]["content"] == "观察中枢震荡。"
    assert restored_notes.json()[0]["payload"]["tags"] == ["中枢"]
    restored_chan_payloads = {
        item["id"]: item["payload"]
        for item in restored_items
        if item["overlay_type"] == "chan"
    }
    assert restored_chan_payloads[old_manual_chan_id]["active"] is False
    assert restored_chan_payloads[old_manual_chan_id]["deactivated_reason"] == "superseded_during_backup_import"
    assert restored_chan_payloads[newer_manual_chan_id]["active"] is True
    restored_wave_payloads = {
        item["id"]: item["payload"]
        for item in restored_items
        if item["overlay_type"] == "wave"
    }
    assert restored_wave_payloads[old_manual_wave_id]["active"] is False
    assert restored_wave_payloads[old_manual_wave_id]["deactivated_reason"] == "superseded_during_backup_import"
    assert restored_wave_payloads[newer_manual_wave_id]["active"] is True

    restored_profiles = client.get("/api/rule-profiles?analysis_type=wave")
    assert restored_profiles.status_code == 200
    assert restored_profiles.json()[0]["name"] == "本地 ZigZag"

    restored_chart = client.get("/api/chart?symbol=sh600000&timeframe=D")
    assert restored_chart.status_code == 200
    assert restored_chart.json()["bars"] == []

    restored_reimport = client.post("/api/imports/daily", json={"markets": ["sh"]})
    assert restored_reimport.status_code == 200
    restored_reimport_payload = restored_reimport.json()
    assert restored_reimport_payload["source_path"] == str(source)
    assert restored_reimport_payload["bars_imported"] == 6

    restored_job_created = client.post("/api/imports/jobs", json={"markets": ["sh"]})
    assert restored_job_created.status_code == 200
    restored_job = restored_job_created.json()

    restored_job_finished = None
    for _ in range(50):
        restored_polled = client.get(f"/api/imports/jobs/{restored_job['id']}")
        assert restored_polled.status_code == 200
        restored_job_payload = restored_polled.json()
        if restored_job_payload["status"] in {"succeeded", "failed"}:
            restored_job_finished = restored_job_payload
            break
        time.sleep(0.05)

    assert restored_job_finished is not None
    assert restored_job_finished["status"] == "succeeded"
    assert restored_job_finished["source_path"] == str(source)
    assert restored_job_finished["bars_imported"] == 6

    restored_backtest = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D")
    assert restored_backtest.status_code == 200
    restored_backtest_payload = restored_backtest.json()
    assert restored_backtest_payload["structure_source"] == "manual"
    assert restored_backtest_payload["manual_annotation_id"] == newer_manual_chan_id
    assert restored_backtest_payload["params"]["source_algorithm"] == "manual-chan"

    restored_wave_backtest = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8"
    )
    assert restored_wave_backtest.status_code == 200
    restored_wave_backtest_payload = restored_wave_backtest.json()
    assert restored_wave_backtest_payload["structure_source"] == "manual"
    assert restored_wave_backtest_payload["manual_annotation_id"] == newer_manual_wave_id
    assert restored_wave_backtest_payload["params"]["source_algorithm"] == "manual-wave"


def test_user_backup_import_fills_missing_default_profiles(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    existing_profiles = client.get("/api/rule-profiles")
    assert existing_profiles.status_code == 200
    seed_profiles = existing_profiles.json()
    seed_by_type = {item["analysis_type"]: item for item in seed_profiles}
    assert "chan" in seed_by_type
    assert "wave" in seed_by_type

    backup_payload = {
        "schema_version": 1,
        "config": {},
        "annotations": [],
        "rule_profiles": [
            {
                **seed_by_type["chan"],
                "is_default": False,
                "updated_at": "2026-05-22T10:00:00Z",
            },
            {
                **seed_by_type["wave"],
                "name": "波浪旧参数",
                "is_default": False,
                "updated_at": "2026-05-22T10:00:00Z",
            },
            {
                "id": "wave-newer-fallback",
                "name": "波浪新参数",
                "analysis_type": "wave",
                "version": "0.9.0",
                "params": {"threshold_pct": 9, "min_swing_bars": 5},
                "is_default": False,
                "created_at": "2026-05-23T10:00:00Z",
                "updated_at": "2026-05-23T10:00:00Z",
            },
        ],
    }
    restored = client.post("/api/backups/user", json=backup_payload)
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": False,
        "annotations_imported": 0,
        "rule_profiles_imported": 3,
    }

    chan_profiles = client.get("/api/rule-profiles?analysis_type=chan")
    assert chan_profiles.status_code == 200
    chan_items = chan_profiles.json()
    assert len(chan_items) == 1
    assert chan_items[0]["id"] == seed_by_type["chan"]["id"]
    assert chan_items[0]["is_default"] is True

    wave_profiles = client.get("/api/rule-profiles?analysis_type=wave")
    assert wave_profiles.status_code == 200
    wave_items = wave_profiles.json()
    assert len(wave_items) == 2
    assert wave_items[0]["id"] == "wave-newer-fallback"
    assert wave_items[0]["is_default"] is True
    assert wave_items[1]["is_default"] is False


def test_user_backup_restore_manual_chan_backtest_after_reimport(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert imported.status_code == 200
    assert imported.json()["bars_imported"] == 6

    manual_chan = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "chan",
            "payload": {
                "active": True,
                "chan_algorithm": "chan-fractal",
                "chan_version": "0.5.0",
                "fractals": [
                    {"index": 1, "trade_date": "2026-05-18", "price": 8.9, "kind": "bottom"},
                    {"index": 3, "trade_date": "2026-05-20", "price": 10.1, "kind": "top"},
                ],
            },
        },
    )
    assert manual_chan.status_code == 200
    manual_annotation_id = manual_chan.json()["id"]

    exported = client.get("/api/backups/user")
    assert exported.status_code == 200
    backup_payload = exported.json()
    assert any(item["id"] == manual_annotation_id for item in backup_payload["annotations"])

    monkeypatch.setattr(config, "APP_DIR", tmp_path / "restored")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "restored" / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "restored" / "test.duckdb")

    restored = client.post("/api/backups/user", json=backup_payload)
    assert restored.status_code == 200

    reimported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert reimported.status_code == 200
    assert reimported.json()["bars_imported"] == 6

    backtest = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D")
    assert backtest.status_code == 200
    backtest_payload = backtest.json()
    assert backtest_payload["structure_source"] == "manual"
    assert backtest_payload["manual_annotation_id"] == manual_annotation_id
    assert backtest_payload["params"]["source_algorithm"] == "manual-chan"
    assert backtest_payload["summary"]["total_trades"] == 1
    assert backtest_payload["trades"][0]["entry_trade_date"] == "2026-05-19"
    assert backtest_payload["trades"][0]["exit_trade_date"] == "2026-05-21"


def test_user_backup_restore_manual_wave_backtest_after_reimport(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert imported.status_code == 200
    assert imported.json()["bars_imported"] == 6

    manual_wave = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "wave",
            "payload": {
                "active": True,
                "wave_algorithm": "wave-zigzag",
                "wave_version": "0.1.0",
                "threshold_pct": 8,
                "pivots": [
                    {"index": 0, "trade_date": "2026-05-11", "price": 8.4, "kind": "start", "wave_no": 1},
                    {"index": 1, "trade_date": "2026-05-18", "price": 8.9, "kind": "bottom", "wave_no": 2},
                    {"index": 3, "trade_date": "2026-05-20", "price": 10.1, "kind": "top", "wave_no": 3},
                ],
            },
        },
    )
    assert manual_wave.status_code == 200
    manual_annotation_id = manual_wave.json()["id"]

    exported = client.get("/api/backups/user")
    assert exported.status_code == 200
    backup_payload = exported.json()
    assert any(item["id"] == manual_annotation_id for item in backup_payload["annotations"])

    monkeypatch.setattr(config, "APP_DIR", tmp_path / "restored")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "restored" / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "restored" / "test.duckdb")

    restored = client.post("/api/backups/user", json=backup_payload)
    assert restored.status_code == 200

    reimported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert reimported.status_code == 200
    assert reimported.json()["bars_imported"] == 6

    backtest = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=true&limit_pct=20"
    )
    assert backtest.status_code == 200
    backtest_payload = backtest.json()
    assert backtest_payload["structure_source"] == "manual"
    assert backtest_payload["manual_annotation_id"] == manual_annotation_id
    assert backtest_payload["params"]["source_algorithm"] == "manual-wave"
    assert backtest_payload["params"]["limit_pct"] == 20
    assert backtest_payload["params"]["limit_rule"] == "prev_close_20pct"
    assert backtest_payload["summary"]["total_trades"] == 1
    assert backtest_payload["trades"][0]["entry_trade_date"] == "2026-05-19"
    assert backtest_payload["trades"][0]["exit_trade_date"] == "2026-05-21"

def test_chart_daily_deduplicates_legacy_duplicate_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_duplicate_daily_test_bars()

    client = TestClient(app)
    chart = client.get("/api/chart?symbol=sh600003&timeframe=D&limit=10")

    assert chart.status_code == 200
    bars = chart.json()["bars"]
    assert [bar["trade_date"] for bar in bars] == ["2026-08-03", "2026-08-04", "2026-08-05"]


def test_chart_weekly_deduplicates_legacy_duplicate_daily_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_duplicate_daily_test_bars()

    client = TestClient(app)
    chart = client.get("/api/chart?symbol=sh600003&timeframe=W&limit=10")

    assert chart.status_code == 200
    bars = chart.json()["bars"]
    assert len(bars) == 1
    assert bars[0]["trade_date"] == "2026-08-05"
    assert bars[0]["open"] == pytest.approx(10.0)
    assert bars[0]["high"] == pytest.approx(11.0)
    assert bars[0]["low"] == pytest.approx(9.8)
    assert bars[0]["close"] == pytest.approx(10.9)
    assert bars[0]["amount"] == pytest.approx(3600.0)
    assert bars[0]["volume"] == 360


def test_chart_monthly_deduplicates_legacy_duplicate_daily_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_duplicate_daily_test_bars()

    client = TestClient(app)
    chart = client.get("/api/chart?symbol=sh600003&timeframe=M&limit=10")

    assert chart.status_code == 200
    bars = chart.json()["bars"]
    assert len(bars) == 1
    assert bars[0]["trade_date"] == "2026-08-05"
    assert bars[0]["open"] == pytest.approx(10.0)
    assert bars[0]["high"] == pytest.approx(11.0)
    assert bars[0]["low"] == pytest.approx(9.8)
    assert bars[0]["close"] == pytest.approx(10.9)
    assert bars[0]["amount"] == pytest.approx(3600.0)
    assert bars[0]["volume"] == 360


def test_bars_weekly_and_monthly_deduplicate_legacy_duplicate_daily_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_duplicate_daily_test_bars()

    client = TestClient(app)
    weekly = client.get("/api/bars?symbol=sh600003&timeframe=W&limit=10")
    assert weekly.status_code == 200
    weekly_bars = weekly.json()
    assert len(weekly_bars) == 1
    assert weekly_bars[0]["timeframe"] == "W"
    assert weekly_bars[0]["trade_date"] == "2026-08-05"
    assert weekly_bars[0]["open"] == pytest.approx(10.0)
    assert weekly_bars[0]["high"] == pytest.approx(11.0)
    assert weekly_bars[0]["low"] == pytest.approx(9.8)
    assert weekly_bars[0]["close"] == pytest.approx(10.9)
    assert weekly_bars[0]["amount"] == pytest.approx(3600.0)
    assert weekly_bars[0]["volume"] == 360

    weekly_before = client.get("/api/bars?symbol=sh600003&timeframe=W&limit=10&before=2026-08-05")
    assert weekly_before.status_code == 200
    assert weekly_before.json() == []

    monthly = client.get("/api/bars?symbol=sh600003&timeframe=M&limit=10")
    assert monthly.status_code == 200
    monthly_bars = monthly.json()
    assert len(monthly_bars) == 1
    assert monthly_bars[0]["timeframe"] == "M"
    assert monthly_bars[0]["trade_date"] == "2026-08-05"
    assert monthly_bars[0]["open"] == pytest.approx(10.0)
    assert monthly_bars[0]["high"] == pytest.approx(11.0)
    assert monthly_bars[0]["low"] == pytest.approx(9.8)
    assert monthly_bars[0]["close"] == pytest.approx(10.9)
    assert monthly_bars[0]["amount"] == pytest.approx(3600.0)
    assert monthly_bars[0]["volume"] == 360

    monthly_before = client.get("/api/bars?symbol=sh600003&timeframe=M&limit=10&before=2026-08-05")
    assert monthly_before.status_code == 200
    assert monthly_before.json() == []


def test_bars_weekly_and_monthly_before_filter_with_cross_period_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_cross_period_daily_test_bars()

    client = TestClient(app)
    weekly = client.get("/api/bars?symbol=sh600005&timeframe=W&limit=10")
    assert weekly.status_code == 200
    weekly_bars = weekly.json()
    assert [bar["trade_date"] for bar in weekly_bars] == ["2026-07-31", "2026-08-04"]
    assert weekly_bars[0]["open"] == pytest.approx(9.8)
    assert weekly_bars[0]["close"] == pytest.approx(10.4)
    assert weekly_bars[1]["open"] == pytest.approx(10.4)
    assert weekly_bars[1]["close"] == pytest.approx(10.9)

    weekly_before = client.get("/api/bars?symbol=sh600005&timeframe=W&limit=10&before=2026-08-04")
    assert weekly_before.status_code == 200
    weekly_before_bars = weekly_before.json()
    assert [bar["trade_date"] for bar in weekly_before_bars] == ["2026-07-31"]

    monthly = client.get("/api/bars?symbol=sh600005&timeframe=M&limit=10")
    assert monthly.status_code == 200
    monthly_bars = monthly.json()
    assert [bar["trade_date"] for bar in monthly_bars] == ["2026-07-31", "2026-08-04"]
    assert monthly_bars[0]["amount"] == pytest.approx(1850.0)
    assert monthly_bars[0]["volume"] == 185
    assert monthly_bars[1]["amount"] == pytest.approx(2100.0)
    assert monthly_bars[1]["volume"] == 210

    monthly_before = client.get("/api/bars?symbol=sh600005&timeframe=M&limit=10&before=2026-08-04")
    assert monthly_before.status_code == 200
    monthly_before_bars = monthly_before.json()
    assert [bar["trade_date"] for bar in monthly_before_bars] == ["2026-07-31"]


def test_chart_weekly_and_monthly_before_filter_with_cross_period_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_cross_period_daily_test_bars()

    client = TestClient(app)
    weekly = client.get("/api/chart?symbol=sh600005&timeframe=W&limit=10")
    assert weekly.status_code == 200
    weekly_bars = weekly.json()["bars"]
    assert [bar["trade_date"] for bar in weekly_bars] == ["2026-07-31", "2026-08-04"]
    assert weekly_bars[0]["open"] == pytest.approx(9.8)
    assert weekly_bars[0]["close"] == pytest.approx(10.4)
    assert weekly_bars[1]["open"] == pytest.approx(10.4)
    assert weekly_bars[1]["close"] == pytest.approx(10.9)

    weekly_before = client.get("/api/chart?symbol=sh600005&timeframe=W&limit=10&before=2026-08-04")
    assert weekly_before.status_code == 200
    assert [bar["trade_date"] for bar in weekly_before.json()["bars"]] == ["2026-07-31"]

    monthly = client.get("/api/chart?symbol=sh600005&timeframe=M&limit=10")
    assert monthly.status_code == 200
    monthly_bars = monthly.json()["bars"]
    assert [bar["trade_date"] for bar in monthly_bars] == ["2026-07-31", "2026-08-04"]
    assert monthly_bars[0]["amount"] == pytest.approx(1850.0)
    assert monthly_bars[0]["volume"] == 185
    assert monthly_bars[1]["amount"] == pytest.approx(2100.0)
    assert monthly_bars[1]["volume"] == 210

    monthly_before = client.get("/api/chart?symbol=sh600005&timeframe=M&limit=10&before=2026-08-04")
    assert monthly_before.status_code == 200
    assert [bar["trade_date"] for bar in monthly_before.json()["bars"]] == ["2026-07-31"]


def test_daily_weekly_monthly_before_timestamp_uses_date_component(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_cross_period_daily_test_bars()

    client = TestClient(app)
    for timeframe in ["D", "W", "M"]:
        bars_by_date = client.get(f"/api/bars?symbol=sh600005&timeframe={timeframe}&limit=10&before=2026-08-04")
        bars_by_timestamp = client.get(
            f"/api/bars?symbol=sh600005&timeframe={timeframe}&limit=10&before=2026-08-04T15:00"
        )
        chart_by_date = client.get(f"/api/chart?symbol=sh600005&timeframe={timeframe}&limit=10&before=2026-08-04")
        chart_by_timestamp = client.get(
            f"/api/chart?symbol=sh600005&timeframe={timeframe}&limit=10&before=2026-08-04T15:00"
        )

        assert bars_by_date.status_code == 200
        assert bars_by_timestamp.status_code == 200
        assert chart_by_date.status_code == 200
        assert chart_by_timestamp.status_code == 200
        assert bars_by_timestamp.json() == bars_by_date.json()
        assert chart_by_timestamp.json()["bars"] == chart_by_date.json()["bars"]
        assert chart_by_date.json()["bars"] == bars_by_date.json()


def test_chart_and_bars_weekly_monthly_match_with_before_filters(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_cross_period_daily_test_bars()

    client = TestClient(app)
    cases = [
        ("W", None),
        ("W", "2026-08-04"),
        ("M", None),
        ("M", "2026-08-04"),
    ]
    for timeframe, before in cases:
        url_suffix = f"&before={before}" if before else ""
        bars = client.get(f"/api/bars?symbol=sh600005&timeframe={timeframe}&limit=10{url_suffix}")
        chart = client.get(f"/api/chart?symbol=sh600005&timeframe={timeframe}&limit=10{url_suffix}")
        assert bars.status_code == 200
        assert chart.status_code == 200
        assert chart.json()["bars"] == bars.json()


def test_weekly_monthly_timeframe_accepts_lowercase_w_m(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_cross_period_daily_test_bars()

    client = TestClient(app)
    for timeframe, normalized in [("w", "W"), ("m", "M")]:
        bars = client.get(f"/api/bars?symbol=sh600005&timeframe={timeframe}&limit=10&before=2026-08-04")
        chart = client.get(f"/api/chart?symbol=sh600005&timeframe={timeframe}&limit=10&before=2026-08-04")
        assert bars.status_code == 200
        assert chart.status_code == 200
        assert bars.json()
        assert chart.json()["bars"]
        assert all(item["timeframe"] == normalized for item in bars.json())
        assert all(item["timeframe"] == normalized for item in chart.json()["bars"])
        assert chart.json()["bars"] == bars.json()


def test_structure_backtest_deduplicates_legacy_duplicate_daily_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_duplicate_daily_test_bars()

    client = TestClient(app)
    manual_chan = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600003",
            "timeframe": "D",
            "overlay_type": "chan",
            "payload": {
                "active": True,
                "chan_algorithm": "chan-fractal",
                "chan_version": "0.5.0",
                "fractals": [
                    {"index": 0, "trade_date": "2026-08-03", "price": 9.8, "kind": "bottom"},
                    {"index": 1, "trade_date": "2026-08-04", "price": 10.8, "kind": "top"},
                ],
            },
        },
    )
    assert manual_chan.status_code == 200

    backtest = client.get("/api/backtests/structure?symbol=sh600003&timeframe=D&limit=20")

    assert backtest.status_code == 200
    payload = backtest.json()
    assert payload["bars_tested"] == 3
    assert payload["structure_source"] == "manual"
    assert payload["manual_annotation_id"] == manual_chan.json()["id"]
    assert payload["summary"]["total_trades"] == 1
    assert payload["trades"][0]["entry_trade_date"] == "2026-08-04"
    assert payload["trades"][0]["exit_trade_date"] == "2026-08-05"


def test_chart_minute_deduplicates_legacy_duplicate_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_duplicate_minute_test_bars()

    client = TestClient(app)
    minute = client.get("/api/chart?symbol=sh600004&timeframe=5m&limit=10")
    aggregated = client.get("/api/chart?symbol=sh600004&timeframe=15m&limit=10")

    assert minute.status_code == 200
    assert [bar["trade_date"] for bar in minute.json()["bars"]] == [
        "2026-08-06T09:35",
        "2026-08-06T09:40",
        "2026-08-06T09:45",
    ]
    assert aggregated.status_code == 200
    assert [bar["trade_date"] for bar in aggregated.json()["bars"]] == ["2026-08-06T09:45"]


def test_analysis_scheme_exports_and_imports_rule_profiles_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    annotation = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "不进入方案"},
        },
    )
    assert annotation.status_code == 200

    profile = client.post(
        "/api/rule-profiles",
        json={
            "name": "方案 ZigZag",
            "analysis_type": "wave",
            "version": "0.3.0",
            "params": {"threshold_pct": 3},
            "is_default": True,
        },
    )
    assert profile.status_code == 200

    exported = client.get("/api/schemes/analysis?name=本地方案&description=复用参数")
    assert exported.status_code == 200
    scheme = exported.json()
    assert scheme["schema_version"] == 1
    assert scheme["name"] == "本地方案"
    assert scheme["description"] == "复用参数"
    assert scheme["exported_at"] is not None
    assert scheme["workspace"] == {}
    assert any(item["name"] == "方案 ZigZag" for item in scheme["rule_profiles"])
    assert "annotations" not in scheme
    assert "bars" not in scheme
    assert "symbols" not in scheme

    unsupported = client.post("/api/schemes/analysis", json={**scheme, "schema_version": 2})
    assert unsupported.status_code == 400
    assert unsupported.json()["detail"] == "不支持的分析方案版本。"
    invalid_scheme = client.post(
        "/api/schemes/analysis",
        json={
            **scheme,
            "rule_profiles": [
                {
                    **scheme["rule_profiles"][0],
                    "analysis_type": "invalid",
                }
            ],
        },
    )
    assert invalid_scheme.status_code == 422

    monkeypatch.setattr(config, "APP_DIR", tmp_path / "scheme-restored")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "scheme-restored" / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "scheme-restored" / "test.duckdb")

    scheme["workspace"] = {
        "selected_symbol": {"symbol": "sh600000", "market": "sh", "code": "600000", "name": "浦发银行"},
        "date_start": None,
        "date_end": None,
        "layers": {"wave": True, "backtest": True},
        "backtest_options": {"limit_pct": 20, "apply_limit_constraints": True},
    }
    restored = client.post(
        "/api/schemes/analysis",
        json={
            **scheme,
            "config": {"source_path": str(tmp_path / "should-not-import")},
            "annotations": [
                {
                    "id": "scheme-extra-annotation",
                    "symbol": "sh600000",
                    "timeframe": "D",
                    "overlay_type": "note",
                    "payload": {"note": "方案导入不应恢复标注"},
                    "created_at": "2026-05-22T10:00:00Z",
                    "updated_at": "2026-05-22T10:00:00Z",
                }
            ],
        },
    )
    assert restored.status_code == 200
    assert restored.json() == {"rule_profiles_imported": len(scheme["rule_profiles"])}
    assert config.load_config() == {}

    restored_profiles = client.get("/api/rule-profiles?analysis_type=wave")
    assert restored_profiles.status_code == 200
    assert restored_profiles.json()[0]["name"] == "方案 ZigZag"

    restored_annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert restored_annotations.status_code == 200
    assert restored_annotations.json() == []


def test_analysis_scheme_import_fills_missing_default_profiles(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    scheme_payload = {
        "schema_version": 1,
        "name": "默认兜底方案",
        "description": "导入后自动补齐默认规则",
        "workspace": {},
        "rule_profiles": [
            {
                "id": "chan-no-default",
                "name": "缠论手工参数",
                "analysis_type": "chan",
                "version": "0.5.0",
                "params": {"include_containment": True},
                "is_default": False,
                "created_at": "2026-05-22T10:00:00Z",
                "updated_at": "2026-05-22T10:00:00Z",
            },
            {
                "id": "wave-old",
                "name": "波浪旧参数",
                "analysis_type": "wave",
                "version": "0.2.0",
                "params": {"threshold_pct": 3, "min_swing_bars": 3},
                "is_default": False,
                "created_at": "2026-05-22T10:00:00Z",
                "updated_at": "2026-05-22T10:00:00Z",
            },
            {
                "id": "wave-new",
                "name": "波浪新参数",
                "analysis_type": "wave",
                "version": "0.3.0",
                "params": {"threshold_pct": 5, "min_swing_bars": 4},
                "is_default": False,
                "created_at": "2026-05-23T10:00:00Z",
                "updated_at": "2026-05-23T10:00:00Z",
            },
        ],
    }
    imported = client.post("/api/schemes/analysis", json=scheme_payload)
    assert imported.status_code == 200
    assert imported.json() == {"rule_profiles_imported": 3}

    chan_profiles = client.get("/api/rule-profiles?analysis_type=chan")
    assert chan_profiles.status_code == 200
    chan_items = chan_profiles.json()
    assert len(chan_items) == 1
    assert chan_items[0]["id"] == "chan-no-default"
    assert chan_items[0]["is_default"] is True

    wave_profiles = client.get("/api/rule-profiles?analysis_type=wave")
    assert wave_profiles.status_code == 200
    wave_items = wave_profiles.json()
    assert len(wave_items) == 2
    assert wave_items[0]["id"] == "wave-new"
    assert wave_items[0]["is_default"] is True
    assert wave_items[1]["id"] == "wave-old"
    assert wave_items[1]["is_default"] is False


def test_analysis_scheme_import_default_fallback_tie_updated_at_uses_id_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    scheme_payload = {
        "schema_version": 1,
        "name": "并列时间戳默认兜底",
        "description": "updated_at 并列时按 id 稳定选默认",
        "workspace": {},
        "rule_profiles": [
            {
                "id": "wave-a",
                "name": "波浪规则 A",
                "analysis_type": "wave",
                "version": "0.2.0",
                "params": {"threshold_pct": 3, "min_swing_bars": 3},
                "is_default": False,
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-26T10:00:00Z",
            },
            {
                "id": "wave-b",
                "name": "波浪规则 B",
                "analysis_type": "wave",
                "version": "0.3.0",
                "params": {"threshold_pct": 5, "min_swing_bars": 4},
                "is_default": False,
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-26T10:00:00Z",
            },
        ],
    }
    imported = client.post("/api/schemes/analysis", json=scheme_payload)
    assert imported.status_code == 200
    assert imported.json() == {"rule_profiles_imported": 2}

    wave_profiles = client.get("/api/rule-profiles?analysis_type=wave")
    assert wave_profiles.status_code == 200
    wave_items = wave_profiles.json()
    assert len(wave_items) == 2
    assert wave_items[0]["id"] == "wave-b"
    assert wave_items[0]["is_default"] is True
    assert wave_items[1]["id"] == "wave-a"
    assert wave_items[1]["is_default"] is False


def test_rule_profiles_list_orders_tie_by_id_desc(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    scheme_payload = {
        "schema_version": 1,
        "name": "规则顺序稳定性",
        "description": "同时间戳按 id 倒序",
        "workspace": {},
        "rule_profiles": [
            {
                "id": "wave-default",
                "name": "波浪默认",
                "analysis_type": "wave",
                "version": "0.3.0",
                "params": {"threshold_pct": 5, "min_swing_bars": 3},
                "is_default": True,
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-26T10:00:00Z",
            },
            {
                "id": "wave-a",
                "name": "波浪 A",
                "analysis_type": "wave",
                "version": "0.3.0",
                "params": {"threshold_pct": 6, "min_swing_bars": 4},
                "is_default": False,
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-26T10:00:00Z",
            },
            {
                "id": "wave-b",
                "name": "波浪 B",
                "analysis_type": "wave",
                "version": "0.3.0",
                "params": {"threshold_pct": 7, "min_swing_bars": 5},
                "is_default": False,
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-26T10:00:00Z",
            },
        ],
    }
    imported = client.post("/api/schemes/analysis", json=scheme_payload)
    assert imported.status_code == 200

    wave_profiles = client.get("/api/rule-profiles?analysis_type=wave")
    assert wave_profiles.status_code == 200
    wave_items = wave_profiles.json()
    assert [item["id"] for item in wave_items] == ["wave-default", "wave-b", "wave-a"]


def test_analysis_scheme_import_replaces_only_payload_types(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    chan_created = client.post(
        "/api/rule-profiles",
        json={
            "name": "缠论保留规则",
            "analysis_type": "chan",
            "version": "0.5.0",
            "params": {"include_containment": True, "strict_fractal": True},
            "is_default": True,
        },
    )
    assert chan_created.status_code == 200
    chan_id = chan_created.json()["id"]

    wave_created = client.post(
        "/api/rule-profiles",
        json={
            "name": "波浪旧规则",
            "analysis_type": "wave",
            "version": "0.2.0",
            "params": {"threshold_pct": 4, "min_swing_bars": 3},
            "is_default": True,
        },
    )
    assert wave_created.status_code == 200
    old_wave_id = wave_created.json()["id"]
    chan_before_import = client.get("/api/rule-profiles?analysis_type=chan")
    assert chan_before_import.status_code == 200
    chan_before_items = chan_before_import.json()
    chan_before_ids = {item["id"] for item in chan_before_items}

    scheme_payload = {
        "schema_version": 1,
        "name": "只替换 wave",
        "description": "验证按类型替换",
        "workspace": {},
        "rule_profiles": [
            {
                "id": "wave-imported-1",
                "name": "波浪新规则 1",
                "analysis_type": "wave",
                "version": "0.3.0",
                "params": {"threshold_pct": 6, "min_swing_bars": 4},
                "is_default": False,
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-24T10:00:00Z",
            },
            {
                "id": "wave-imported-2",
                "name": "波浪新规则 2",
                "analysis_type": "wave",
                "version": "0.4.0",
                "params": {"threshold_pct": 8, "min_swing_bars": 5},
                "is_default": False,
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-25T10:00:00Z",
            },
        ],
    }

    imported = client.post("/api/schemes/analysis", json=scheme_payload)
    assert imported.status_code == 200
    assert imported.json() == {"rule_profiles_imported": 2}

    chan_profiles = client.get("/api/rule-profiles?analysis_type=chan")
    assert chan_profiles.status_code == 200
    chan_items = chan_profiles.json()
    assert {item["id"] for item in chan_items} == chan_before_ids
    chan_created_item = next((item for item in chan_items if item["id"] == chan_id), None)
    assert chan_created_item is not None
    assert chan_created_item["name"] == "缠论保留规则"
    assert chan_created_item["is_default"] is True

    wave_profiles = client.get("/api/rule-profiles?analysis_type=wave")
    assert wave_profiles.status_code == 200
    wave_items = wave_profiles.json()
    assert len(wave_items) == 2
    assert {item["id"] for item in wave_items} == {"wave-imported-1", "wave-imported-2"}
    assert old_wave_id not in {item["id"] for item in wave_items}
    assert wave_items[0]["id"] == "wave-imported-2"
    assert wave_items[0]["is_default"] is True
    assert wave_items[1]["id"] == "wave-imported-1"
    assert wave_items[1]["is_default"] is False


def test_analysis_scheme_import_deduplicates_duplicate_rule_profile_ids(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    scheme_payload = {
        "schema_version": 1,
        "name": "重复 ID 去重",
        "description": "后写入覆盖前写入",
        "workspace": {},
        "rule_profiles": [
            {
                "id": "dup-wave-id",
                "name": "波浪旧值",
                "analysis_type": "wave",
                "version": "0.2.0",
                "params": {"threshold_pct": 4, "min_swing_bars": 3},
                "is_default": False,
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-24T10:00:00Z",
            },
            {
                "id": "dup-wave-id",
                "name": "波浪新值",
                "analysis_type": "wave",
                "version": "0.3.0",
                "params": {"threshold_pct": 8, "min_swing_bars": 5},
                "is_default": True,
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-25T10:00:00Z",
            },
        ],
    }
    imported = client.post("/api/schemes/analysis", json=scheme_payload)
    assert imported.status_code == 200
    assert imported.json() == {"rule_profiles_imported": 1}

    wave_profiles = client.get("/api/rule-profiles?analysis_type=wave")
    assert wave_profiles.status_code == 200
    wave_items = wave_profiles.json()
    assert len(wave_items) == 1
    assert wave_items[0]["id"] == "dup-wave-id"
    assert wave_items[0]["name"] == "波浪新值"
    assert wave_items[0]["version"] == "0.3.0"
    assert wave_items[0]["params"]["threshold_pct"] == 8
    assert wave_items[0]["is_default"] is True


def test_analysis_scheme_import_with_empty_rule_profiles_keeps_existing_profiles(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    seed_wave = client.post(
        "/api/rule-profiles",
        json={
            "name": "已有波浪规则",
            "analysis_type": "wave",
            "version": "0.3.0",
            "params": {"threshold_pct": 6, "min_swing_bars": 4},
            "is_default": True,
        },
    )
    assert seed_wave.status_code == 200
    existing_wave_id = seed_wave.json()["id"]
    before_wave_profiles = client.get("/api/rule-profiles?analysis_type=wave")
    assert before_wave_profiles.status_code == 200
    before_wave_items = before_wave_profiles.json()
    before_pairs = [(item["id"], item["is_default"]) for item in before_wave_items]
    assert existing_wave_id in {item["id"] for item in before_wave_items}

    scheme_payload = {
        "schema_version": 1,
        "name": "空规则方案",
        "description": "不携带规则时不应改动现有规则",
        "workspace": {},
        "rule_profiles": [],
    }
    imported = client.post("/api/schemes/analysis", json=scheme_payload)
    assert imported.status_code == 200
    assert imported.json() == {"rule_profiles_imported": 0}

    wave_profiles = client.get("/api/rule-profiles?analysis_type=wave")
    assert wave_profiles.status_code == 200
    wave_items = wave_profiles.json()
    after_pairs = [(item["id"], item["is_default"]) for item in wave_items]
    assert after_pairs == before_pairs
    assert any(item["id"] == existing_wave_id and item["name"] == "已有波浪规则" and item["is_default"] is True for item in wave_items)


def test_analysis_scheme_import_rejects_rule_profile_id_cross_type_conflict(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    scheme_payload = {
        "schema_version": 1,
        "name": "跨类型 ID 冲突",
        "description": "同一规则 ID 不允许跨 analysis_type 复用",
        "workspace": {},
        "rule_profiles": [
            {
                "id": "shared-id",
                "name": "缠论规则",
                "analysis_type": "chan",
                "version": "0.5.0",
                "params": {"include_containment": True},
                "is_default": True,
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-24T10:00:00Z",
            },
            {
                "id": "shared-id",
                "name": "波浪规则",
                "analysis_type": "wave",
                "version": "0.3.0",
                "params": {"threshold_pct": 5, "min_swing_bars": 3},
                "is_default": True,
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-25T10:00:00Z",
            },
        ],
    }
    imported = client.post("/api/schemes/analysis", json=scheme_payload)
    assert imported.status_code == 400
    assert imported.json()["detail"] == "规则 ID 冲突：shared-id 同时用于 chan 和 wave。"


def test_analysis_scheme_import_rejects_empty_rule_profile_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    imported = client.post(
        "/api/schemes/analysis",
        json={
            "schema_version": 1,
            "name": "空 ID 方案",
            "description": "规则 ID 不能为空",
            "workspace": {},
            "rule_profiles": [
                {
                    "id": "   ",
                    "name": "无效规则",
                    "analysis_type": "chan",
                    "version": "0.5.0",
                    "params": {"include_containment": True},
                    "is_default": True,
                    "created_at": "2026-05-24T10:00:00Z",
                    "updated_at": "2026-05-24T10:00:00Z",
                }
            ],
        },
    )
    assert imported.status_code == 400
    assert imported.json()["detail"] == "规则 ID 不能为空。"


def test_analysis_scheme_import_empty_rule_profile_id_does_not_mutate_existing_profiles(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    seeded = client.post(
        "/api/rule-profiles",
        json={
            "name": "保留波浪规则",
            "analysis_type": "wave",
            "version": "0.3.2",
            "params": {"threshold_pct": 7, "min_swing_bars": 4},
            "is_default": True,
        },
    )
    assert seeded.status_code == 200

    before = client.get("/api/rule-profiles")
    assert before.status_code == 200
    before_items = [(item["analysis_type"], item["id"], item["is_default"]) for item in before.json()]

    imported = client.post(
        "/api/schemes/analysis",
        json={
            "schema_version": 1,
            "name": "空 ID 冲突方案",
            "description": "应失败且不改动现有规则",
            "workspace": {},
            "rule_profiles": [
                {
                    "id": "  ",
                    "name": "无效规则",
                    "analysis_type": "wave",
                    "version": "0.3.0",
                    "params": {"threshold_pct": 5},
                    "is_default": True,
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                }
            ],
        },
    )
    assert imported.status_code == 400
    assert imported.json()["detail"] == "规则 ID 不能为空。"

    after = client.get("/api/rule-profiles")
    assert after.status_code == 200
    after_items = [(item["analysis_type"], item["id"], item["is_default"]) for item in after.json()]
    assert after_items == before_items


def test_analysis_scheme_import_cross_type_conflict_does_not_mutate_existing_profiles(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    seeded = client.post(
        "/api/rule-profiles",
        json={
            "name": "保留规则",
            "analysis_type": "wave",
            "version": "0.3.1",
            "params": {"threshold_pct": 9, "min_swing_bars": 4},
            "is_default": True,
        },
    )
    assert seeded.status_code == 200

    before = client.get("/api/rule-profiles")
    assert before.status_code == 200
    before_items = [(item["analysis_type"], item["id"], item["is_default"]) for item in before.json()]

    imported = client.post(
        "/api/schemes/analysis",
        json={
            "schema_version": 1,
            "name": "冲突方案",
            "description": "应失败且不改动现有规则",
            "workspace": {},
            "rule_profiles": [
                {
                    "id": "shared-id",
                    "name": "缠论冲突规则",
                    "analysis_type": "chan",
                    "version": "0.5.0",
                    "params": {"include_containment": True},
                    "is_default": True,
                    "created_at": "2026-05-24T10:00:00Z",
                    "updated_at": "2026-05-24T10:00:00Z",
                },
                {
                    "id": "shared-id",
                    "name": "波浪冲突规则",
                    "analysis_type": "wave",
                    "version": "0.3.0",
                    "params": {"threshold_pct": 5},
                    "is_default": True,
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                },
            ],
        },
    )
    assert imported.status_code == 400

    after = client.get("/api/rule-profiles")
    assert after.status_code == 200
    after_items = [(item["analysis_type"], item["id"], item["is_default"]) for item in after.json()]
    assert after_items == before_items


def test_user_backup_import_deduplicates_duplicate_rule_profile_ids(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    backup_payload = {
        "schema_version": 1,
        "config": {},
        "annotations": [],
        "rule_profiles": [
            {
                "id": "dup-chan-id",
                "name": "缠论旧值",
                "analysis_type": "chan",
                "version": "0.2.0",
                "params": {"strict_fractal": False},
                "is_default": False,
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-24T10:00:00Z",
            },
            {
                "id": "dup-chan-id",
                "name": "缠论新值",
                "analysis_type": "chan",
                "version": "0.3.0",
                "params": {"strict_fractal": True},
                "is_default": True,
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-25T10:00:00Z",
            },
        ],
    }
    restored = client.post("/api/backups/user", json=backup_payload)
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": False,
        "annotations_imported": 0,
        "rule_profiles_imported": 1,
    }

    chan_profiles = client.get("/api/rule-profiles?analysis_type=chan")
    assert chan_profiles.status_code == 200
    chan_items = chan_profiles.json()
    deduped_item = next((item for item in chan_items if item["id"] == "dup-chan-id"), None)
    assert deduped_item is not None
    assert deduped_item["name"] == "缠论新值"
    assert deduped_item["version"] == "0.3.0"
    assert deduped_item["params"]["strict_fractal"] is True
    assert deduped_item["is_default"] is True


def test_user_backup_import_rejects_rule_profile_id_cross_type_conflict(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    backup_payload = {
        "schema_version": 1,
        "config": {},
        "annotations": [],
        "rule_profiles": [
            {
                "id": "shared-id",
                "name": "缠论规则",
                "analysis_type": "chan",
                "version": "0.5.0",
                "params": {"strict_fractal": False},
                "is_default": True,
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-24T10:00:00Z",
            },
            {
                "id": "shared-id",
                "name": "波浪规则",
                "analysis_type": "wave",
                "version": "0.3.0",
                "params": {"threshold_pct": 5},
                "is_default": True,
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-25T10:00:00Z",
            },
        ],
    }
    restored = client.post("/api/backups/user", json=backup_payload)
    assert restored.status_code == 400
    assert restored.json()["detail"] == "规则 ID 冲突：shared-id 同时用于 chan 和 wave。"


def test_user_backup_import_rejects_empty_rule_profile_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {},
            "annotations": [],
            "rule_profiles": [
                {
                    "id": "",
                    "name": "无效规则",
                    "analysis_type": "wave",
                    "version": "0.3.0",
                    "params": {"threshold_pct": 5},
                    "is_default": True,
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                }
            ],
        },
    )
    assert restored.status_code == 400
    assert restored.json()["detail"] == "规则 ID 不能为空。"


def test_user_backup_import_rejects_unsupported_annotation_timeframe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {},
            "annotations": [
                {
                    "id": "bad-timeframe-note",
                    "symbol": "sh600000",
                    "timeframe": "2m",
                    "overlay_type": "note",
                    "payload": {"note": "invalid"},
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                }
            ],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 400
    assert restored.json()["detail"] == "标注 timeframe 不支持：2m"


def test_user_backup_import_normalizes_config_source_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {"source_path": "  ~/tdx/vipdoc  "},
            "annotations": [],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": True,
        "annotations_imported": 0,
        "rule_profiles_imported": 0,
    }
    expected_source_path = str(Path("~/tdx/vipdoc").expanduser().resolve())
    assert config.load_config() == {"source_path": expected_source_path}


def test_user_backup_import_normalizes_config_source_path_with_relative_segments(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    config_source_path = source.parent / ".." / "tdx" / source.name

    client = TestClient(app)
    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {"source_path": f"  {config_source_path}  "},
            "annotations": [],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": True,
        "annotations_imported": 0,
        "rule_profiles_imported": 0,
    }
    assert config.load_config() == {"source_path": str(config_source_path.resolve())}


def test_user_backup_export_normalizes_config_source_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    config_source_path = source.parent / ".." / "tdx" / source.name
    config.save_config({"source_path": f"  {config_source_path}  ", "unexpected_local_key": "ignored"})

    client = TestClient(app)
    exported = client.get("/api/backups/user")

    assert exported.status_code == 200
    payload = exported.json()
    assert payload["config"] == {"source_path": str(config_source_path.resolve())}


def test_user_backup_export_ignores_blank_config_source_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "   ", "unexpected_local_key": "ignored"})

    client = TestClient(app)
    exported = client.get("/api/backups/user")

    assert exported.status_code == 200
    payload = exported.json()
    assert payload["config"] == {}


def test_user_backup_export_ignores_unknown_config_keys_without_source_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"unexpected_local_key": "ignored"})

    client = TestClient(app)
    exported = client.get("/api/backups/user")

    assert exported.status_code == 200
    payload = exported.json()
    assert payload["config"] == {}


def test_user_backup_import_ignores_blank_config_source_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "/keep/source"})

    client = TestClient(app)
    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {"source_path": "   "},
            "annotations": [],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": False,
        "annotations_imported": 0,
        "rule_profiles_imported": 0,
    }
    assert config.load_config() == {"source_path": "/keep/source"}


def test_user_backup_import_ignores_invalid_config_source_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "/keep/source"})

    client = TestClient(app)
    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {"source_path": "bad\0path"},
            "annotations": [],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": False,
        "annotations_imported": 0,
        "rule_profiles_imported": 0,
    }
    assert config.load_config() == {"source_path": "/keep/source"}


def test_user_backup_export_ignores_invalid_config_source_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "bad\0path"})

    client = TestClient(app)
    exported = client.get("/api/backups/user")

    assert exported.status_code == 200
    payload = exported.json()
    assert payload["config"] == {}


def test_user_backup_import_rejects_empty_annotation_symbol(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {},
            "annotations": [
                {
                    "id": "bad-symbol-note",
                    "symbol": "   ",
                    "timeframe": "D",
                    "overlay_type": "note",
                    "payload": {"note": "invalid"},
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                }
            ],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 400
    assert restored.json()["detail"] == "标注 symbol 不能为空。"


def test_user_backup_import_rejects_empty_annotation_overlay_type(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {},
            "annotations": [
                {
                    "id": "bad-overlay-note",
                    "symbol": "sh600000",
                    "timeframe": "D",
                    "overlay_type": "   ",
                    "payload": {"note": "invalid"},
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                }
            ],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 400
    assert restored.json()["detail"] == "标注 overlay_type 不能为空。"


def test_user_backup_import_rejects_empty_annotation_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {},
            "annotations": [
                {
                    "id": "   ",
                    "symbol": "sh600000",
                    "timeframe": "D",
                    "overlay_type": "note",
                    "payload": {"note": "invalid"},
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                }
            ],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 400
    assert restored.json()["detail"] == "标注 ID 不能为空。"


def test_user_backup_import_empty_rule_profile_id_does_not_mutate_annotations_or_config(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    config.save_config({"source_path": "/keep/source"})

    created = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "保留标注"},
        },
    )
    assert created.status_code == 200
    original_annotation_id = created.json()["id"]

    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {"source_path": "/should/not/apply"},
            "annotations": [
                {
                    "id": "new-annotation",
                    "symbol": "sh600000",
                    "timeframe": "D",
                    "overlay_type": "note",
                    "payload": {"note": "不应写入"},
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                }
            ],
            "rule_profiles": [
                {
                    "id": "",
                    "name": "无效规则",
                    "analysis_type": "wave",
                    "version": "0.3.0",
                    "params": {"threshold_pct": 5},
                    "is_default": True,
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                }
            ],
        },
    )
    assert restored.status_code == 400
    assert restored.json()["detail"] == "规则 ID 不能为空。"

    assert config.load_config() == {"source_path": "/keep/source"}

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    items = annotations.json()
    assert [item["id"] for item in items] == [original_annotation_id]
    assert items[0]["payload"] == {"note": "保留标注"}


def test_user_backup_import_empty_annotation_symbol_does_not_mutate_annotations_or_config(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    config.save_config({"source_path": "/keep/source"})

    created = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "保留标注"},
        },
    )
    assert created.status_code == 200
    original_annotation_id = created.json()["id"]

    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {"source_path": "/should/not/apply"},
            "annotations": [
                {
                    "id": "bad-symbol-note",
                    "symbol": " ",
                    "timeframe": "D",
                    "overlay_type": "note",
                    "payload": {"note": "不应写入"},
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                }
            ],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 400
    assert restored.json()["detail"] == "标注 symbol 不能为空。"

    assert config.load_config() == {"source_path": "/keep/source"}

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    items = annotations.json()
    assert [item["id"] for item in items] == [original_annotation_id]
    assert items[0]["payload"] == {"note": "保留标注"}


def test_user_backup_import_empty_annotation_id_does_not_mutate_annotations_or_config(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    config.save_config({"source_path": "/keep/source"})

    created = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "保留标注"},
        },
    )
    assert created.status_code == 200
    original_annotation_id = created.json()["id"]

    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {"source_path": "/should/not/apply"},
            "annotations": [
                {
                    "id": " ",
                    "symbol": "sh600000",
                    "timeframe": "D",
                    "overlay_type": "note",
                    "payload": {"note": "不应写入"},
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                }
            ],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 400
    assert restored.json()["detail"] == "标注 ID 不能为空。"

    assert config.load_config() == {"source_path": "/keep/source"}

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    items = annotations.json()
    assert [item["id"] for item in items] == [original_annotation_id]
    assert items[0]["payload"] == {"note": "保留标注"}


def test_user_backup_import_empty_annotation_overlay_type_does_not_mutate_annotations_or_config(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    config.save_config({"source_path": "/keep/source"})

    created = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "保留标注"},
        },
    )
    assert created.status_code == 200
    original_annotation_id = created.json()["id"]

    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {"source_path": "/should/not/apply"},
            "annotations": [
                {
                    "id": "bad-overlay-note",
                    "symbol": "sh600000",
                    "timeframe": "D",
                    "overlay_type": " ",
                    "payload": {"note": "不应写入"},
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                }
            ],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 400
    assert restored.json()["detail"] == "标注 overlay_type 不能为空。"

    assert config.load_config() == {"source_path": "/keep/source"}

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    items = annotations.json()
    assert [item["id"] for item in items] == [original_annotation_id]
    assert items[0]["payload"] == {"note": "保留标注"}


def test_user_backup_import_unsupported_annotation_timeframe_does_not_mutate_annotations_or_config(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    config.save_config({"source_path": "/keep/source"})

    created = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "保留标注"},
        },
    )
    assert created.status_code == 200
    original_annotation_id = created.json()["id"]

    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {"source_path": "/should/not/apply"},
            "annotations": [
                {
                    "id": "bad-timeframe-note",
                    "symbol": "sh600000",
                    "timeframe": "2m",
                    "overlay_type": "note",
                    "payload": {"note": "不应写入"},
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                }
            ],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 400
    assert restored.json()["detail"] == "标注 timeframe 不支持：2m"

    assert config.load_config() == {"source_path": "/keep/source"}

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    items = annotations.json()
    assert [item["id"] for item in items] == [original_annotation_id]
    assert items[0]["payload"] == {"note": "保留标注"}


def test_user_backup_import_cross_type_conflict_does_not_mutate_existing_profiles(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    seeded = client.post(
        "/api/rule-profiles",
        json={
            "name": "保留缠论规则",
            "analysis_type": "chan",
            "version": "0.5.1",
            "params": {"strict_fractal": True, "include_containment": True},
            "is_default": True,
        },
    )
    assert seeded.status_code == 200

    before = client.get("/api/rule-profiles")
    assert before.status_code == 200
    before_items = [(item["analysis_type"], item["id"], item["is_default"]) for item in before.json()]

    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {},
            "annotations": [],
            "rule_profiles": [
                {
                    "id": "shared-id",
                    "name": "缠论冲突规则",
                    "analysis_type": "chan",
                    "version": "0.5.0",
                    "params": {"strict_fractal": False},
                    "is_default": True,
                    "created_at": "2026-05-24T10:00:00Z",
                    "updated_at": "2026-05-24T10:00:00Z",
                },
                {
                    "id": "shared-id",
                    "name": "波浪冲突规则",
                    "analysis_type": "wave",
                    "version": "0.3.0",
                    "params": {"threshold_pct": 5},
                    "is_default": True,
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                },
            ],
        },
    )
    assert restored.status_code == 400

    after = client.get("/api/rule-profiles")
    assert after.status_code == 200
    after_items = [(item["analysis_type"], item["id"], item["is_default"]) for item in after.json()]
    assert after_items == before_items


def test_user_backup_import_cross_type_conflict_does_not_mutate_annotations_or_config(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    config.save_config({"source_path": "/keep/source"})

    created = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "保留标注"},
        },
    )
    assert created.status_code == 200
    original_annotation_id = created.json()["id"]

    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {"source_path": "/should/not/apply"},
            "annotations": [
                {
                    "id": "conflict-new-annotation",
                    "symbol": "sh600000",
                    "timeframe": "D",
                    "overlay_type": "note",
                    "payload": {"note": "不应写入"},
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                }
            ],
            "rule_profiles": [
                {
                    "id": "shared-id",
                    "name": "缠论冲突规则",
                    "analysis_type": "chan",
                    "version": "0.5.0",
                    "params": {"strict_fractal": False},
                    "is_default": True,
                    "created_at": "2026-05-24T10:00:00Z",
                    "updated_at": "2026-05-24T10:00:00Z",
                },
                {
                    "id": "shared-id",
                    "name": "波浪冲突规则",
                    "analysis_type": "wave",
                    "version": "0.3.0",
                    "params": {"threshold_pct": 5},
                    "is_default": True,
                    "created_at": "2026-05-25T10:00:00Z",
                    "updated_at": "2026-05-25T10:00:00Z",
                },
            ],
        },
    )
    assert restored.status_code == 400
    assert restored.json()["detail"] == "规则 ID 冲突：shared-id 同时用于 chan 和 wave。"

    assert config.load_config() == {"source_path": "/keep/source"}

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    items = annotations.json()
    assert [item["id"] for item in items] == [original_annotation_id]
    assert items[0]["payload"] == {"note": "保留标注"}


def test_user_backup_import_deduplicates_duplicate_annotation_ids(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    backup_payload = {
        "schema_version": 1,
        "config": {},
        "annotations": [
            {
                "id": "dup-annotation-id",
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "note",
                "payload": {"note": "旧标注"},
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-24T10:00:00Z",
            },
            {
                "id": "dup-annotation-id",
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "note",
                "payload": {"note": "新标注"},
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-25T10:00:00Z",
            },
        ],
        "rule_profiles": [],
    }
    restored = client.post("/api/backups/user", json=backup_payload)
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": False,
        "annotations_imported": 1,
        "rule_profiles_imported": 0,
    }

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    items = annotations.json()
    assert len(items) == 1
    assert items[0]["id"] == "dup-annotation-id"
    assert items[0]["payload"] == {"note": "新标注"}


def test_user_backup_import_validates_annotation_timeframe_after_deduplication(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    backup_payload = {
        "schema_version": 1,
        "config": {},
        "annotations": [
            {
                "id": "dup-timeframe-id",
                "symbol": "sh600000",
                "timeframe": "2m",
                "overlay_type": "note",
                "payload": {"note": "应被覆盖的非法记录"},
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-24T10:00:00Z",
            },
            {
                "id": "dup-timeframe-id",
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "note",
                "payload": {"note": "最终生效记录"},
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-25T10:00:00Z",
            },
        ],
        "rule_profiles": [],
    }
    restored = client.post("/api/backups/user", json=backup_payload)
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": False,
        "annotations_imported": 1,
        "rule_profiles_imported": 0,
    }

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    items = annotations.json()
    assert len(items) == 1
    assert items[0]["id"] == "dup-timeframe-id"
    assert items[0]["payload"] == {"note": "最终生效记录"}


def test_user_backup_import_validates_annotation_symbol_after_deduplication(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    backup_payload = {
        "schema_version": 1,
        "config": {},
        "annotations": [
            {
                "id": "dup-symbol-id",
                "symbol": "   ",
                "timeframe": "D",
                "overlay_type": "note",
                "payload": {"note": "应被覆盖的非法记录"},
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-24T10:00:00Z",
            },
            {
                "id": "dup-symbol-id",
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "note",
                "payload": {"note": "最终生效记录"},
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-25T10:00:00Z",
            },
        ],
        "rule_profiles": [],
    }
    restored = client.post("/api/backups/user", json=backup_payload)
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": False,
        "annotations_imported": 1,
        "rule_profiles_imported": 0,
    }

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    items = annotations.json()
    assert len(items) == 1
    assert items[0]["id"] == "dup-symbol-id"
    assert items[0]["payload"] == {"note": "最终生效记录"}


def test_user_backup_import_rejects_annotation_symbol_when_latest_duplicate_invalid(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    backup_payload = {
        "schema_version": 1,
        "config": {},
        "annotations": [
            {
                "id": "dup-symbol-invalid-last",
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "note",
                "payload": {"note": "应被覆盖的有效记录"},
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-24T10:00:00Z",
            },
            {
                "id": "dup-symbol-invalid-last",
                "symbol": "   ",
                "timeframe": "D",
                "overlay_type": "note",
                "payload": {"note": "最终非法记录"},
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-25T10:00:00Z",
            },
        ],
        "rule_profiles": [],
    }
    restored = client.post("/api/backups/user", json=backup_payload)
    assert restored.status_code == 400
    assert restored.json()["detail"] == "标注 symbol 不能为空。"

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    assert annotations.json() == []


def test_user_backup_import_validates_annotation_overlay_type_after_deduplication(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    backup_payload = {
        "schema_version": 1,
        "config": {},
        "annotations": [
            {
                "id": "dup-overlay-id",
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "   ",
                "payload": {"note": "应被覆盖的非法记录"},
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-24T10:00:00Z",
            },
            {
                "id": "dup-overlay-id",
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "note",
                "payload": {"note": "最终生效记录"},
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-25T10:00:00Z",
            },
        ],
        "rule_profiles": [],
    }
    restored = client.post("/api/backups/user", json=backup_payload)
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": False,
        "annotations_imported": 1,
        "rule_profiles_imported": 0,
    }

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    items = annotations.json()
    assert len(items) == 1
    assert items[0]["id"] == "dup-overlay-id"
    assert items[0]["overlay_type"] == "note"


def test_user_backup_import_rejects_annotation_overlay_type_when_latest_duplicate_invalid(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    backup_payload = {
        "schema_version": 1,
        "config": {},
        "annotations": [
            {
                "id": "dup-overlay-invalid-last",
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "note",
                "payload": {"note": "应被覆盖的有效记录"},
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-24T10:00:00Z",
            },
            {
                "id": "dup-overlay-invalid-last",
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "  ",
                "payload": {"note": "最终非法记录"},
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-25T10:00:00Z",
            },
        ],
        "rule_profiles": [],
    }
    restored = client.post("/api/backups/user", json=backup_payload)
    assert restored.status_code == 400
    assert restored.json()["detail"] == "标注 overlay_type 不能为空。"

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    assert annotations.json() == []


def test_user_backup_import_normalizes_annotation_timeframe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {},
            "annotations": [
                {
                    "id": "normalize-timeframe-note",
                    "symbol": "sh600000",
                    "timeframe": " d ",
                    "overlay_type": "note",
                    "payload": {"note": "normalize"},
                    "created_at": "2026-05-24T10:00:00Z",
                    "updated_at": "2026-05-24T10:00:00Z",
                }
            ],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": False,
        "annotations_imported": 1,
        "rule_profiles_imported": 0,
    }

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    items = annotations.json()
    assert len(items) == 1
    assert items[0]["id"] == "normalize-timeframe-note"
    assert items[0]["timeframe"] == "D"

    exported = client.get("/api/backups/user")
    assert exported.status_code == 200
    exported_items = [item for item in exported.json()["annotations"] if item["id"] == "normalize-timeframe-note"]
    assert len(exported_items) == 1
    assert exported_items[0]["timeframe"] == "D"


def test_user_backup_import_normalizes_annotation_symbol(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {},
            "annotations": [
                {
                    "id": "normalize-symbol-note",
                    "symbol": " SH600000 ",
                    "timeframe": "D",
                    "overlay_type": "note",
                    "payload": {"note": "normalize symbol"},
                    "created_at": "2026-05-24T10:00:00Z",
                    "updated_at": "2026-05-24T10:00:00Z",
                }
            ],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": False,
        "annotations_imported": 1,
        "rule_profiles_imported": 0,
    }

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    items = annotations.json()
    assert len(items) == 1
    assert items[0]["id"] == "normalize-symbol-note"
    assert items[0]["symbol"] == "sh600000"

    exported = client.get("/api/backups/user")
    assert exported.status_code == 200
    exported_items = [item for item in exported.json()["annotations"] if item["id"] == "normalize-symbol-note"]
    assert len(exported_items) == 1
    assert exported_items[0]["symbol"] == "sh600000"


def test_user_backup_import_normalizes_annotation_overlay_type(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    restored = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {},
            "annotations": [
                {
                    "id": "normalize-overlay-type-note",
                    "symbol": "sh600000",
                    "timeframe": "D",
                    "overlay_type": " note ",
                    "payload": {"note": "normalize overlay type"},
                    "created_at": "2026-05-24T10:00:00Z",
                    "updated_at": "2026-05-24T10:00:00Z",
                }
            ],
            "rule_profiles": [],
        },
    )
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": False,
        "annotations_imported": 1,
        "rule_profiles_imported": 0,
    }

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    items = annotations.json()
    assert len(items) == 1
    assert items[0]["id"] == "normalize-overlay-type-note"
    assert items[0]["overlay_type"] == "note"

    exported = client.get("/api/backups/user")
    assert exported.status_code == 200
    exported_items = [item for item in exported.json()["annotations"] if item["id"] == "normalize-overlay-type-note"]
    assert len(exported_items) == 1
    assert exported_items[0]["overlay_type"] == "note"


def test_user_backup_export_orders_tie_updated_at_annotations_by_id_desc(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    imported = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {},
            "annotations": [
                {
                    "id": "tie-note-a",
                    "symbol": "sh600000",
                    "timeframe": "D",
                    "overlay_type": "note",
                    "payload": {"note": "A"},
                    "created_at": "2026-05-26T10:00:00Z",
                    "updated_at": "2026-05-26T10:00:00Z",
                },
                {
                    "id": "tie-note-b",
                    "symbol": "sh600000",
                    "timeframe": "D",
                    "overlay_type": "note",
                    "payload": {"note": "B"},
                    "created_at": "2026-05-26T10:00:00Z",
                    "updated_at": "2026-05-26T10:00:00Z",
                },
            ],
            "rule_profiles": [],
        },
    )
    assert imported.status_code == 200

    exported = client.get("/api/backups/user")
    assert exported.status_code == 200
    annotation_ids = [item["id"] for item in exported.json()["annotations"] if item["overlay_type"] == "note"]
    assert annotation_ids == ["tie-note-b", "tie-note-a"]


def test_user_backup_import_normalizes_active_manual_structures_with_tie_updated_at(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    backup_payload = {
        "schema_version": 1,
        "config": {},
        "annotations": [
            {
                "id": "tie-wave-a",
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "wave",
                "payload": {
                    "active": True,
                    "threshold_pct": 5,
                    "pivots": [
                        {"index": 0, "trade_date": "2026-05-17", "price": 8.6, "kind": "start", "wave_no": 1},
                        {"index": 2, "trade_date": "2026-05-19", "price": 9.2, "kind": "bottom", "wave_no": 2},
                    ],
                },
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-26T10:00:00Z",
            },
            {
                "id": "tie-wave-b",
                "symbol": "sh600000",
                "timeframe": "D",
                "overlay_type": "wave",
                "payload": {
                    "active": True,
                    "threshold_pct": 8,
                    "pivots": [
                        {"index": 0, "trade_date": "2026-05-17", "price": 8.6, "kind": "start", "wave_no": 1},
                        {"index": 3, "trade_date": "2026-05-20", "price": 10.1, "kind": "top", "wave_no": 3},
                    ],
                },
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-26T10:00:00Z",
            },
        ],
        "rule_profiles": [],
    }
    restored = client.post("/api/backups/user", json=backup_payload)
    assert restored.status_code == 200
    assert restored.json() == {
        "config_imported": False,
        "annotations_imported": 2,
        "rule_profiles_imported": 0,
    }

    annotations = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert annotations.status_code == 200
    wave_payloads = {
        item["id"]: item["payload"]
        for item in annotations.json()
        if item["overlay_type"] == "wave"
    }
    assert wave_payloads["tie-wave-b"]["active"] is True
    assert wave_payloads["tie-wave-a"]["active"] is False
    assert wave_payloads["tie-wave-a"]["deactivated_reason"] == "superseded_during_backup_import"


def test_import_updates_names_and_chart_includes_minute_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert imported.status_code == 200
    assert imported.json()["bars_imported"] == 6
    assert imported.json()["minute_files_seen"] == 1
    assert imported.json()["minute_files_imported"] == 1
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

    raw_bars = client.get("/api/bars?symbol=sh600000&timeframe=5m&start_date=2026-05-22&end_date=2026-05-22")
    assert raw_bars.status_code == 200
    assert len(raw_bars.json()) == 48
    assert raw_bars.json()[0]["timeframe"] == "5M"
    assert raw_bars.json()[0]["trade_date"] == "2026-05-22T09:35"

    aggregated = client.get("/api/chart?symbol=sh600000&timeframe=15m&start_date=2026-05-22&end_date=2026-05-22")
    assert aggregated.status_code == 200
    aggregated_payload = aggregated.json()
    aggregated_bars = aggregated_payload["bars"]
    assert len(aggregated_payload["bars"]) == 16
    assert [bar["trade_date"] for bar in aggregated_payload["bars"][:2]] == ["2026-05-22T09:45", "2026-05-22T10:00"]
    assert [bar["trade_date"] for bar in aggregated_payload["bars"][-2:]] == ["2026-05-22T14:45", "2026-05-22T15:00"]
    assert aggregated_payload["bars"][0]["open"] == pytest.approx(10.0)
    assert aggregated_payload["bars"][0]["high"] == pytest.approx(10.22)
    assert aggregated_payload["bars"][0]["low"] == pytest.approx(9.9)
    assert aggregated_payload["bars"][0]["close"] == pytest.approx(10.07)
    assert aggregated_payload["bars"][0]["volume"] == 303
    assert aggregated_payload["chan"]["timeframe"] == "15M"

    raw_5m_bars = raw_bars.json()
    assert len(raw_5m_bars) == len(aggregated_bars) * 3
    for index, bucket in enumerate(aggregated_bars):
        chunk = raw_5m_bars[index * 3 : index * 3 + 3]
        assert len(chunk) == 3
        assert bucket["trade_date"] == chunk[-1]["trade_date"]
        assert bucket["open"] == pytest.approx(chunk[0]["open"])
        assert bucket["high"] == pytest.approx(max(item["high"] for item in chunk))
        assert bucket["low"] == pytest.approx(min(item["low"] for item in chunk))
        assert bucket["close"] == pytest.approx(chunk[-1]["close"])
        assert bucket["amount"] == pytest.approx(sum(item["amount"] for item in chunk))
        assert bucket["volume"] == sum(item["volume"] for item in chunk)

    aggregated30 = client.get("/api/chart?symbol=sh600000&timeframe=30m&start_date=2026-05-22&end_date=2026-05-22")
    assert aggregated30.status_code == 200
    aggregated30_bars = aggregated30.json()["bars"]
    assert [bar["trade_date"] for bar in aggregated30_bars] == [
        "2026-05-22T10:00",
        "2026-05-22T10:30",
        "2026-05-22T11:00",
        "2026-05-22T11:30",
        "2026-05-22T13:30",
        "2026-05-22T14:00",
        "2026-05-22T14:30",
        "2026-05-22T15:00",
    ]
    assert len(raw_5m_bars) == len(aggregated30_bars) * 6
    for index, bucket in enumerate(aggregated30_bars):
        chunk = raw_5m_bars[index * 6 : index * 6 + 6]
        assert len(chunk) == 6
        assert bucket["trade_date"] == chunk[-1]["trade_date"]
        assert bucket["open"] == pytest.approx(chunk[0]["open"])
        assert bucket["high"] == pytest.approx(max(item["high"] for item in chunk))
        assert bucket["low"] == pytest.approx(min(item["low"] for item in chunk))
        assert bucket["close"] == pytest.approx(chunk[-1]["close"])
        assert bucket["amount"] == pytest.approx(sum(item["amount"] for item in chunk))
        assert bucket["volume"] == sum(item["volume"] for item in chunk)

    aggregated60 = client.get("/api/chart?symbol=sh600000&timeframe=60m&start_date=2026-05-22&end_date=2026-05-22")
    assert aggregated60.status_code == 200
    aggregated60_bars = aggregated60.json()["bars"]
    assert [bar["trade_date"] for bar in aggregated60_bars] == [
        "2026-05-22T10:30",
        "2026-05-22T11:30",
        "2026-05-22T14:00",
        "2026-05-22T15:00",
    ]
    assert len(raw_5m_bars) == len(aggregated60_bars) * 12
    for index, bucket in enumerate(aggregated60_bars):
        chunk = raw_5m_bars[index * 12 : index * 12 + 12]
        assert len(chunk) == 12
        assert bucket["trade_date"] == chunk[-1]["trade_date"]
        assert bucket["open"] == pytest.approx(chunk[0]["open"])
        assert bucket["high"] == pytest.approx(max(item["high"] for item in chunk))
        assert bucket["low"] == pytest.approx(min(item["low"] for item in chunk))
        assert bucket["close"] == pytest.approx(chunk[-1]["close"])
        assert bucket["amount"] == pytest.approx(sum(item["amount"] for item in chunk))
        assert bucket["volume"] == sum(item["volume"] for item in chunk)

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


def test_minute_aggregation_before_boundary_matches_chart_and_bars(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert imported.status_code == 200
    assert imported.json()["minute_bars_imported"] == 48

    # before=桶终点前 1 分钟，15m 桶应回退到 09:45。
    chart_15m_pre_bucket = client.get("/api/chart?symbol=sh600000&timeframe=15m&limit=1&before=2026-05-22T09:59")
    bars_15m_pre_bucket = client.get("/api/bars?symbol=sh600000&timeframe=15m&limit=1&before=2026-05-22T09:59")
    assert chart_15m_pre_bucket.status_code == 200
    assert bars_15m_pre_bucket.status_code == 200
    assert [bar["trade_date"] for bar in chart_15m_pre_bucket.json()["bars"]] == ["2026-05-22T09:45"]
    assert chart_15m_pre_bucket.json()["bars"] == bars_15m_pre_bucket.json()

    # before=桶终点（10:00）时，10:00 桶应被排除，回退到 09:45。
    chart_15m_exact_bucket = client.get("/api/chart?symbol=sh600000&timeframe=15m&limit=1&before=2026-05-22T10:00")
    bars_15m_exact_bucket = client.get("/api/bars?symbol=sh600000&timeframe=15m&limit=1&before=2026-05-22T10:00")
    assert chart_15m_exact_bucket.status_code == 200
    assert bars_15m_exact_bucket.status_code == 200
    assert [bar["trade_date"] for bar in chart_15m_exact_bucket.json()["bars"]] == ["2026-05-22T09:45"]
    assert chart_15m_exact_bucket.json()["bars"] == bars_15m_exact_bucket.json()

    # before=桶终点前 1 分钟，30m 桶应回退到 10:00。
    chart_30m_pre_bucket = client.get("/api/chart?symbol=sh600000&timeframe=30m&limit=1&before=2026-05-22T10:29")
    bars_30m_pre_bucket = client.get("/api/bars?symbol=sh600000&timeframe=30m&limit=1&before=2026-05-22T10:29")
    assert chart_30m_pre_bucket.status_code == 200
    assert bars_30m_pre_bucket.status_code == 200
    assert [bar["trade_date"] for bar in chart_30m_pre_bucket.json()["bars"]] == ["2026-05-22T10:00"]
    assert chart_30m_pre_bucket.json()["bars"] == bars_30m_pre_bucket.json()

    # before=桶终点（10:30）时，10:30 桶应被排除，回退到 10:00。
    chart_30m_exact_bucket = client.get("/api/chart?symbol=sh600000&timeframe=30m&limit=1&before=2026-05-22T10:30")
    bars_30m_exact_bucket = client.get("/api/bars?symbol=sh600000&timeframe=30m&limit=1&before=2026-05-22T10:30")
    assert chart_30m_exact_bucket.status_code == 200
    assert bars_30m_exact_bucket.status_code == 200
    assert [bar["trade_date"] for bar in chart_30m_exact_bucket.json()["bars"]] == ["2026-05-22T10:00"]
    assert chart_30m_exact_bucket.json()["bars"] == bars_30m_exact_bucket.json()

    # 午休边界 before=13:00，应返回上午最后完整 15m 桶 11:30。
    chart_lunch_boundary = client.get("/api/chart?symbol=sh600000&timeframe=15m&limit=1&before=2026-05-22T13:00")
    bars_lunch_boundary = client.get("/api/bars?symbol=sh600000&timeframe=15m&limit=1&before=2026-05-22T13:00")
    assert chart_lunch_boundary.status_code == 200
    assert bars_lunch_boundary.status_code == 200
    assert [bar["trade_date"] for bar in chart_lunch_boundary.json()["bars"]] == ["2026-05-22T11:30"]
    assert chart_lunch_boundary.json()["bars"] == bars_lunch_boundary.json()

    # before=桶终点前 1 分钟，60m 桶应回退到 14:00。
    chart_60m_pre_bucket = client.get("/api/chart?symbol=sh600000&timeframe=60m&limit=1&before=2026-05-22T14:59")
    bars_60m_pre_bucket = client.get("/api/bars?symbol=sh600000&timeframe=60m&limit=1&before=2026-05-22T14:59")
    assert chart_60m_pre_bucket.status_code == 200
    assert bars_60m_pre_bucket.status_code == 200
    assert [bar["trade_date"] for bar in chart_60m_pre_bucket.json()["bars"]] == ["2026-05-22T14:00"]
    assert chart_60m_pre_bucket.json()["bars"] == bars_60m_pre_bucket.json()

    # before=桶终点（15:00）时，15:00 桶应被排除，回退到 14:00。
    chart_60m_exact_bucket = client.get("/api/chart?symbol=sh600000&timeframe=60m&limit=1&before=2026-05-22T15:00")
    bars_60m_exact_bucket = client.get("/api/bars?symbol=sh600000&timeframe=60m&limit=1&before=2026-05-22T15:00")
    assert chart_60m_exact_bucket.status_code == 200
    assert bars_60m_exact_bucket.status_code == 200
    assert [bar["trade_date"] for bar in chart_60m_exact_bucket.json()["bars"]] == ["2026-05-22T14:00"]
    assert chart_60m_exact_bucket.json()["bars"] == bars_60m_exact_bucket.json()

    # 60m 的午休边界 before=13:00，也应返回上午最后完整桶 11:30。
    chart_60m_lunch_boundary = client.get("/api/chart?symbol=sh600000&timeframe=60m&limit=1&before=2026-05-22T13:00")
    bars_60m_lunch_boundary = client.get("/api/bars?symbol=sh600000&timeframe=60m&limit=1&before=2026-05-22T13:00")
    assert chart_60m_lunch_boundary.status_code == 200
    assert bars_60m_lunch_boundary.status_code == 200
    assert [bar["trade_date"] for bar in chart_60m_lunch_boundary.json()["bars"]] == ["2026-05-22T11:30"]
    assert chart_60m_lunch_boundary.json()["bars"] == bars_60m_lunch_boundary.json()

    # before 只传日期时按当日 00:00 处理：分钟与聚合分钟都不应返回当日数据。
    chart_5m_date_before = client.get("/api/chart?symbol=sh600000&timeframe=5m&before=2026-05-22")
    bars_5m_date_before = client.get("/api/bars?symbol=sh600000&timeframe=5m&before=2026-05-22")
    assert chart_5m_date_before.status_code == 200
    assert bars_5m_date_before.status_code == 200
    assert chart_5m_date_before.json()["bars"] == []
    assert bars_5m_date_before.json() == []

    chart_15m_date_before = client.get("/api/chart?symbol=sh600000&timeframe=15m&before=2026-05-22")
    bars_15m_date_before = client.get("/api/bars?symbol=sh600000&timeframe=15m&before=2026-05-22")
    assert chart_15m_date_before.status_code == 200
    assert bars_15m_date_before.status_code == 200
    assert chart_15m_date_before.json()["bars"] == []
    assert bars_15m_date_before.json() == []


def test_structure_backtest_endpoint_returns_research_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert imported.status_code == 200

    result = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D")
    assert result.status_code == 200
    payload = result.json()
    assert payload["algorithm"] == "structure-backtest"
    assert payload["version"] == "0.1.0"
    assert payload["strategy"] == "chan_fractal_reversal"
    assert payload["structure_source"] == "auto"
    assert payload["manual_annotation_id"] is None
    assert payload["params"]["entry_signal"] == "bottom_fractal"
    assert payload["params"]["exit_signal"] == "top_fractal"
    assert payload["params"]["strategy_condition_key"] == "chan_fractal_reversal"
    assert "底分型确认" in payload["params"]["strategy_condition"]
    assert set(payload["params"]["structure_counts"]) == {"fractals", "bis", "segments", "zhongshu"}
    assert payload["params"]["signal_count"] == (
        payload["params"]["entry_signal_count"] + payload["params"]["exit_signal_count"]
    )
    assert payload["params"]["apply_limit_constraints"] is False
    assert payload["params"]["limit_pct"] == 10
    assert payload["params"]["limit_rule"] == "prev_close_10pct"
    assert payload["params"]["skipped_limit_up_entries"] == 0
    assert payload["params"]["skipped_limit_down_exits"] == 0
    assert payload["bars_tested"] == 6
    assert set(payload["summary"]) == {
        "total_trades",
        "winning_trades",
        "losing_trades",
        "win_rate",
        "total_return_pct",
        "average_return_pct",
        "max_drawdown_pct",
        "average_holding_bars",
        "min_holding_bars",
        "max_holding_bars",
        "median_holding_bars",
    }

    bi_strategy_result = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=chan_bi_reversal")
    assert bi_strategy_result.status_code == 200
    bi_strategy_payload = bi_strategy_result.json()
    assert bi_strategy_payload["strategy"] == "chan_bi_reversal"
    assert bi_strategy_payload["params"]["entry_signal"] == "down_bi_end"
    assert bi_strategy_payload["params"]["exit_signal"] == "up_bi_end"
    assert bi_strategy_payload["params"]["strategy_condition_key"] == "chan_bi_reversal"

    manual_chan = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "chan",
            "payload": {
                "active": True,
                "chan_algorithm": "chan-fractal",
                "chan_version": "0.5.0",
                "params": {"source": "manual-test", "min_bars_for_bi": 1},
                "fractals": [
                    {"index": 1, "trade_date": "2026-05-18", "price": 8.9, "kind": "bottom"},
                    {"index": 3, "trade_date": "2026-05-20", "price": 10.1, "kind": "top"},
                ],
            },
        },
    )
    assert manual_chan.status_code == 200

    manual_result = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D")
    assert manual_result.status_code == 200
    manual_payload = manual_result.json()
    assert manual_payload["structure_source"] == "manual"
    assert manual_payload["manual_annotation_id"] == manual_chan.json()["id"]
    assert manual_payload["params"]["source_algorithm"] == "manual-chan"
    assert manual_payload["params"]["structure_counts"]["bis"] == 1
    assert manual_payload["params"]["derived_from_manual_fractals"] is True
    assert manual_payload["summary"]["total_trades"] == 1
    assert manual_payload["trades"][0]["entry_trade_date"] == "2026-05-19"
    assert manual_payload["trades"][0]["exit_trade_date"] == "2026-05-21"

    manual_chart = client.get("/api/chart?symbol=sh600000&timeframe=D")
    assert manual_chart.status_code == 200
    manual_chart_payload = manual_chart.json()
    assert manual_chart_payload["chan"]["algorithm"] == "manual-chan"
    assert manual_chart_payload["chan"]["params"]["derived_from_manual_fractals"] is True
    assert [(item["start_index"], item["end_index"], item["direction"]) for item in manual_chart_payload["chan"]["bis"]] == [
        (1, 3, "up"),
    ]
    manual_chan_analysis = client.get("/api/analysis/chan?symbol=sh600000&timeframe=D")
    assert manual_chan_analysis.status_code == 200
    manual_chan_analysis_payload = manual_chan_analysis.json()
    assert manual_chan_analysis_payload["algorithm"] == "manual-chan"
    assert manual_chan_analysis_payload["params"]["derived_from_manual_fractals"] is True
    assert [
        (item["start_index"], item["end_index"], item["direction"])
        for item in manual_chan_analysis_payload["bis"]
    ] == [(1, 3, "up")]

    newer_manual_chan = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "chan",
            "payload": {
                "active": True,
                "chan_algorithm": "chan-fractal",
                "chan_version": "0.5.0",
                "params": {"source": "newer-manual-test", "min_bars_for_bi": 1},
                "fractals": [
                    {"index": 2, "trade_date": "2026-05-19", "price": 9.2, "kind": "bottom"},
                    {"index": 4, "trade_date": "2026-05-21", "price": 10.4, "kind": "top"},
                ],
            },
        },
    )
    assert newer_manual_chan.status_code == 200

    superseded_chan = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert superseded_chan.status_code == 200
    chan_payloads = {
        item["id"]: item["payload"]
        for item in superseded_chan.json()
        if item["overlay_type"] == "chan"
    }
    assert chan_payloads[manual_chan.json()["id"]]["active"] is False
    assert chan_payloads[manual_chan.json()["id"]]["deactivated_reason"] == "superseded_by_new_manual_structure"
    assert chan_payloads[newer_manual_chan.json()["id"]]["active"] is True

    reactivated_chan = client.patch(
        f"/api/annotations/{manual_chan.json()['id']}",
        json={"payload": {**manual_chan.json()["payload"], "active": True}},
    )
    assert reactivated_chan.status_code == 200
    chan_items_after_reactivation = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert chan_items_after_reactivation.status_code == 200
    chan_payloads_after_reactivation = {
        item["id"]: item["payload"]
        for item in chan_items_after_reactivation.json()
        if item["overlay_type"] == "chan"
    }
    assert chan_payloads_after_reactivation[manual_chan.json()["id"]]["active"] is True
    assert chan_payloads_after_reactivation[newer_manual_chan.json()["id"]]["active"] is False
    assert (
        chan_payloads_after_reactivation[newer_manual_chan.json()["id"]]["deactivated_reason"]
        == "superseded_by_new_manual_structure"
    )

    newer_manual_result = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D")
    assert newer_manual_result.status_code == 200
    newer_manual_payload = newer_manual_result.json()
    assert newer_manual_payload["manual_annotation_id"] == manual_chan.json()["id"]
    reactivated_manual_chan_analysis = client.get("/api/analysis/chan?symbol=sh600000&timeframe=D")
    assert reactivated_manual_chan_analysis.status_code == 200
    assert reactivated_manual_chan_analysis.json()["algorithm"] == "manual-chan"

    manual_bi_result = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=chan_bi_reversal")
    assert manual_bi_result.status_code == 200
    manual_bi_payload = manual_bi_result.json()
    assert manual_bi_payload["structure_source"] == "manual"
    assert manual_bi_payload["params"]["structure_counts"]["bis"] == 1
    assert manual_bi_payload["params"]["signal_count"] == 1

    manual_zhongshu_payload = {
        **manual_chan.json()["payload"],
        "fractals": [],
        "zhongshu": [
            {
                "index": 1,
                "start_bi_index": 1,
                "end_bi_index": 3,
                "start_index": 0,
                "end_index": 1,
                "start_trade_date": "2026-05-11",
                "end_trade_date": "2026-05-18",
                "low": 9.0,
                "high": 9.6,
                "mid": 9.3,
                "bi_count": 3,
            }
        ],
    }
    manual_zhongshu = client.patch(
        f"/api/annotations/{manual_chan.json()['id']}",
        json={"payload": manual_zhongshu_payload},
    )
    assert manual_zhongshu.status_code == 200

    zhongshu_result = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=chan_zhongshu_breakout")
    assert zhongshu_result.status_code == 200
    zhongshu_payload = zhongshu_result.json()
    assert zhongshu_payload["strategy"] == "chan_zhongshu_breakout"
    assert zhongshu_payload["structure_source"] == "manual"
    assert zhongshu_payload["manual_annotation_id"] == manual_chan.json()["id"]
    assert zhongshu_payload["params"]["entry_signal"] == "zhongshu_breakout"
    assert zhongshu_payload["params"]["exit_signal"] == "zhongshu_breakdown"
    assert zhongshu_payload["params"]["strategy_condition_key"] == "chan_zhongshu_breakout"
    assert "突破中枢上沿" in zhongshu_payload["params"]["strategy_condition"]
    assert zhongshu_payload["params"]["structure_counts"]["zhongshu"] == 1
    assert zhongshu_payload["params"]["signal_count"] == (
        zhongshu_payload["params"]["entry_signal_count"] + zhongshu_payload["params"]["exit_signal_count"]
    )

    manual_wave = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "wave",
            "payload": {
                "active": True,
                "wave_algorithm": "wave-zigzag",
                "wave_version": "0.1.0",
                "threshold_pct": 8,
                "pivots": [
                    {"index": 0, "trade_date": "2026-05-11", "price": 8.4, "kind": "start", "wave_no": 1},
                    {"index": 1, "trade_date": "2026-05-18", "price": 8.9, "kind": "bottom", "wave_no": 2},
                    {"index": 3, "trade_date": "2026-05-20", "price": 10.1, "kind": "top", "wave_no": 3},
                ],
            },
        },
    )
    assert manual_wave.status_code == 200

    wave_result = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8")
    assert wave_result.status_code == 200
    wave_payload = wave_result.json()
    assert wave_payload["strategy"] == "wave_zigzag_reversal"
    assert wave_payload["structure_source"] == "manual"
    assert wave_payload["manual_annotation_id"] == manual_wave.json()["id"]
    assert wave_payload["params"]["entry_signal"] == "wave_bottom"
    assert wave_payload["params"]["exit_signal"] == "wave_top"
    assert wave_payload["params"]["source_algorithm"] == "manual-wave"
    assert wave_payload["params"]["wave_threshold_pct"] == 8
    assert wave_payload["params"]["strategy_condition_key"] == "wave_zigzag_reversal"
    assert wave_payload["params"]["apply_limit_constraints"] is False
    assert wave_payload["params"]["limit_pct"] == 10
    assert wave_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert wave_payload["params"]["skipped_limit_up_entries"] == 0
    assert wave_payload["params"]["skipped_limit_down_exits"] == 0
    assert wave_payload["params"]["structure_counts"] == {"wave_pivots": 3, "wave_tops": 1, "wave_bottoms": 1}
    assert wave_payload["params"]["signal_count"] == 2
    assert wave_payload["trades"][0]["entry_signal"] == "wave_bottom"
    assert wave_payload["trades"][0]["exit_signal"] == "wave_top"
    manual_wave_analysis = client.get("/api/analysis/wave?symbol=sh600000&timeframe=D&threshold_pct=8")
    assert manual_wave_analysis.status_code == 200
    manual_wave_analysis_payload = manual_wave_analysis.json()
    assert manual_wave_analysis_payload["algorithm"] == "manual-wave"
    assert manual_wave_analysis_payload["threshold_pct"] == 8
    assert len(manual_wave_analysis_payload["pivots"]) == 3

    cost_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&fee_bps=10&slippage_bps=5&position_pct=50&apply_limit_constraints=true&limit_pct=20"
    )
    assert cost_result.status_code == 200
    cost_payload = cost_result.json()
    assert cost_payload["params"]["fee_bps"] == 10
    assert cost_payload["params"]["slippage_bps"] == 5
    assert cost_payload["params"]["position_pct"] == 50
    assert cost_payload["params"]["apply_limit_constraints"] is True
    assert cost_payload["params"]["limit_pct"] == 20
    assert cost_payload["params"]["limit_rule"] == "prev_close_20pct"
    assert "skipped_limit_up_entries" in cost_payload["params"]
    assert "skipped_limit_down_exits" in cost_payload["params"]

    unconstrained_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=false&limit_pct=20"
    )
    assert unconstrained_limit_result.status_code == 200
    unconstrained_limit_payload = unconstrained_limit_result.json()
    assert unconstrained_limit_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_limit_payload["params"]["limit_pct"] == 20
    assert unconstrained_limit_payload["params"]["limit_rule"] == "prev_close_20pct"
    assert unconstrained_limit_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_limit_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_decimal_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=false&limit_pct=12.5"
    )
    assert unconstrained_decimal_limit_result.status_code == 200
    unconstrained_decimal_limit_payload = unconstrained_decimal_limit_result.json()
    assert unconstrained_decimal_limit_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_decimal_limit_payload["params"]["limit_pct"] == 12.5
    assert unconstrained_decimal_limit_payload["params"]["limit_rule"] == "prev_close_12.5pct"
    assert unconstrained_decimal_limit_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_decimal_limit_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_decimal_plus_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=false&limit_pct=%2B12.5"
    )
    assert unconstrained_decimal_plus_limit_result.status_code == 200
    unconstrained_decimal_plus_limit_payload = unconstrained_decimal_plus_limit_result.json()
    assert unconstrained_decimal_plus_limit_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_decimal_plus_limit_payload["params"]["limit_pct"] == 12.5
    assert unconstrained_decimal_plus_limit_payload["params"]["limit_rule"] == "prev_close_12.5pct"
    assert unconstrained_decimal_plus_limit_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_decimal_plus_limit_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_decimal_plus_spaced_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=false&limit_pct=%20%2B12.5%20"
    )
    assert unconstrained_decimal_plus_spaced_limit_result.status_code == 200
    unconstrained_decimal_plus_spaced_limit_payload = unconstrained_decimal_plus_spaced_limit_result.json()
    assert unconstrained_decimal_plus_spaced_limit_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_decimal_plus_spaced_limit_payload["params"]["limit_pct"] == 12.5
    assert unconstrained_decimal_plus_spaced_limit_payload["params"]["limit_rule"] == "prev_close_12.5pct"
    assert unconstrained_decimal_plus_spaced_limit_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_decimal_plus_spaced_limit_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_scientific_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=false&limit_pct=1e1"
    )
    assert unconstrained_scientific_limit_result.status_code == 200
    unconstrained_scientific_limit_payload = unconstrained_scientific_limit_result.json()
    assert unconstrained_scientific_limit_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_scientific_limit_payload["params"]["limit_pct"] == 10
    assert unconstrained_scientific_limit_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert unconstrained_scientific_limit_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_scientific_limit_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_scientific_upper_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=false&limit_pct=1E1"
    )
    assert unconstrained_scientific_upper_limit_result.status_code == 200
    unconstrained_scientific_upper_limit_payload = unconstrained_scientific_upper_limit_result.json()
    assert unconstrained_scientific_upper_limit_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_scientific_upper_limit_payload["params"]["limit_pct"] == 10
    assert unconstrained_scientific_upper_limit_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert unconstrained_scientific_upper_limit_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_scientific_upper_limit_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_scientific_plus_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=false&limit_pct=%2B1e1"
    )
    assert unconstrained_scientific_plus_limit_result.status_code == 200
    unconstrained_scientific_plus_limit_payload = unconstrained_scientific_plus_limit_result.json()
    assert unconstrained_scientific_plus_limit_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_scientific_plus_limit_payload["params"]["limit_pct"] == 10
    assert unconstrained_scientific_plus_limit_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert unconstrained_scientific_plus_limit_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_scientific_plus_limit_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_scientific_plus_upper_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=false&limit_pct=%2B1E1"
    )
    assert unconstrained_scientific_plus_upper_limit_result.status_code == 200
    unconstrained_scientific_plus_upper_limit_payload = unconstrained_scientific_plus_upper_limit_result.json()
    assert unconstrained_scientific_plus_upper_limit_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_scientific_plus_upper_limit_payload["params"]["limit_pct"] == 10
    assert unconstrained_scientific_plus_upper_limit_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert unconstrained_scientific_plus_upper_limit_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_scientific_plus_upper_limit_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_scientific_plus_upper_spaced_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=false&limit_pct=%20%2B1E1%20"
    )
    assert unconstrained_scientific_plus_upper_spaced_limit_result.status_code == 200
    unconstrained_scientific_plus_upper_spaced_limit_payload = unconstrained_scientific_plus_upper_spaced_limit_result.json()
    assert unconstrained_scientific_plus_upper_spaced_limit_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_scientific_plus_upper_spaced_limit_payload["params"]["limit_pct"] == 10
    assert unconstrained_scientific_plus_upper_spaced_limit_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert unconstrained_scientific_plus_upper_spaced_limit_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_scientific_plus_upper_spaced_limit_payload["params"]["skipped_limit_down_exits"] == 0

    min_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=true&limit_pct=0.1"
    )
    assert min_limit_result.status_code == 200
    min_limit_payload = min_limit_result.json()
    assert min_limit_payload["params"]["apply_limit_constraints"] is True
    assert min_limit_payload["params"]["limit_pct"] == 0.1
    assert min_limit_payload["params"]["limit_rule"] == "prev_close_0.1pct"

    scientific_min_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=true&limit_pct=1e-1"
    )
    assert scientific_min_limit_result.status_code == 200
    scientific_min_limit_payload = scientific_min_limit_result.json()
    assert scientific_min_limit_payload["params"]["apply_limit_constraints"] is True
    assert scientific_min_limit_payload["params"]["limit_pct"] == 0.1
    assert scientific_min_limit_payload["params"]["limit_rule"] == "prev_close_0.1pct"

    scientific_plus_min_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=true&limit_pct=%2B1e-1"
    )
    assert scientific_plus_min_limit_result.status_code == 200
    scientific_plus_min_limit_payload = scientific_plus_min_limit_result.json()
    assert scientific_plus_min_limit_payload["params"]["apply_limit_constraints"] is True
    assert scientific_plus_min_limit_payload["params"]["limit_pct"] == 0.1
    assert scientific_plus_min_limit_payload["params"]["limit_rule"] == "prev_close_0.1pct"

    plus_min_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=true&limit_pct=%2B0.1"
    )
    assert plus_min_limit_result.status_code == 200
    plus_min_limit_payload = plus_min_limit_result.json()
    assert plus_min_limit_payload["params"]["apply_limit_constraints"] is True
    assert plus_min_limit_payload["params"]["limit_pct"] == 0.1
    assert plus_min_limit_payload["params"]["limit_rule"] == "prev_close_0.1pct"

    max_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=true&limit_pct=30"
    )
    assert max_limit_result.status_code == 200
    max_limit_payload = max_limit_result.json()
    assert max_limit_payload["params"]["apply_limit_constraints"] is True
    assert max_limit_payload["params"]["limit_pct"] == 30
    assert max_limit_payload["params"]["limit_rule"] == "prev_close_30pct"

    scientific_max_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=true&limit_pct=3e1"
    )
    assert scientific_max_limit_result.status_code == 200
    scientific_max_limit_payload = scientific_max_limit_result.json()
    assert scientific_max_limit_payload["params"]["apply_limit_constraints"] is True
    assert scientific_max_limit_payload["params"]["limit_pct"] == 30
    assert scientific_max_limit_payload["params"]["limit_rule"] == "prev_close_30pct"

    scientific_plus_max_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=true&limit_pct=%2B3e1"
    )
    assert scientific_plus_max_limit_result.status_code == 200
    scientific_plus_max_limit_payload = scientific_plus_max_limit_result.json()
    assert scientific_plus_max_limit_payload["params"]["apply_limit_constraints"] is True
    assert scientific_plus_max_limit_payload["params"]["limit_pct"] == 30
    assert scientific_plus_max_limit_payload["params"]["limit_rule"] == "prev_close_30pct"

    decimal_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=true&limit_pct=12.5"
    )
    assert decimal_limit_result.status_code == 200
    decimal_limit_payload = decimal_limit_result.json()
    assert decimal_limit_payload["params"]["apply_limit_constraints"] is True
    assert decimal_limit_payload["params"]["limit_pct"] == 12.5
    assert decimal_limit_payload["params"]["limit_rule"] == "prev_close_12.5pct"

    scientific_limit_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=true&limit_pct=1e1"
    )
    assert scientific_limit_result.status_code == 200
    scientific_limit_payload = scientific_limit_result.json()
    assert scientific_limit_payload["params"]["apply_limit_constraints"] is True
    assert scientific_limit_payload["params"]["limit_pct"] == 10
    assert scientific_limit_payload["params"]["limit_rule"] == "prev_close_10pct"

    scientific_limit_upper_result = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=true&limit_pct=1E1"
    )
    assert scientific_limit_upper_result.status_code == 200
    scientific_limit_upper_payload = scientific_limit_upper_result.json()
    assert scientific_limit_upper_payload["params"]["apply_limit_constraints"] is True
    assert scientific_limit_upper_payload["params"]["limit_pct"] == 10
    assert scientific_limit_upper_payload["params"]["limit_rule"] == "prev_close_10pct"

    unsupported = client.get("/api/backtests/structure?symbol=sh600000&strategy=unknown")
    assert unsupported.status_code == 400
    assert "Unsupported backtest strategy" in unsupported.json()["detail"]


def test_analysis_and_backtest_fallback_to_auto_when_active_manual_chan_invalid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert imported.status_code == 200

    invalid_manual_chan = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "chan",
            "payload": {
                "active": True,
                "chan_algorithm": "chan-fractal",
                "chan_version": "0.5.0",
                "fractals": [
                    {"index": 1, "trade_date": "2026-05-18", "price": 8.9, "kind": "invalid-kind"},
                ],
            },
        },
    )
    assert invalid_manual_chan.status_code == 200

    chan_analysis = client.get("/api/analysis/chan?symbol=sh600000&timeframe=D")
    assert chan_analysis.status_code == 200
    chan_payload = chan_analysis.json()
    assert chan_payload["algorithm"] == "chan-fractal"

    backtest = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D")
    assert backtest.status_code == 200
    backtest_payload = backtest.json()
    assert backtest_payload["structure_source"] == "auto"
    assert backtest_payload["manual_annotation_id"] is None
    assert backtest_payload["params"]["source_algorithm"] == "chan-fractal"

    backtest_with_decimal_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=false&limit_pct=12.5"
    )
    assert backtest_with_decimal_limit.status_code == 200
    backtest_with_decimal_limit_payload = backtest_with_decimal_limit.json()
    assert backtest_with_decimal_limit_payload["structure_source"] == "auto"
    assert backtest_with_decimal_limit_payload["manual_annotation_id"] is None
    assert backtest_with_decimal_limit_payload["params"]["source_algorithm"] == "chan-fractal"
    assert backtest_with_decimal_limit_payload["params"]["apply_limit_constraints"] is False
    assert backtest_with_decimal_limit_payload["params"]["limit_pct"] == 12.5
    assert backtest_with_decimal_limit_payload["params"]["limit_rule"] == "prev_close_12.5pct"
    assert backtest_with_decimal_limit_payload["params"]["skipped_limit_up_entries"] == 0
    assert backtest_with_decimal_limit_payload["params"]["skipped_limit_down_exits"] == 0


def test_analysis_and_backtest_fallback_to_auto_when_active_manual_wave_invalid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert imported.status_code == 200

    invalid_manual_wave = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "wave",
            "payload": {
                "active": True,
                "wave_algorithm": "wave-zigzag",
                "wave_version": "0.1.0",
                "threshold_pct": 8,
                "pivots": [
                    {"index": 0, "trade_date": "2026-05-11", "price": 8.4, "kind": "start"},
                    {"index": 3, "trade_date": "2026-05-20", "price": 10.1, "kind": "top"},
                ],
            },
        },
    )
    assert invalid_manual_wave.status_code == 200

    wave_analysis = client.get("/api/analysis/wave?symbol=sh600000&timeframe=D&threshold_pct=8")
    assert wave_analysis.status_code == 200
    wave_payload = wave_analysis.json()
    assert wave_payload["algorithm"] == "wave-zigzag"

    backtest = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8")
    assert backtest.status_code == 200
    backtest_payload = backtest.json()
    assert backtest_payload["structure_source"] == "auto"
    assert backtest_payload["manual_annotation_id"] is None
    assert backtest_payload["params"]["source_algorithm"] == "wave-zigzag"
    assert backtest_payload["params"]["apply_limit_constraints"] is False
    assert backtest_payload["params"]["limit_pct"] == 10
    assert backtest_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert backtest_payload["params"]["skipped_limit_up_entries"] == 0
    assert backtest_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_with_custom_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=false&limit_pct=20"
    )
    assert unconstrained_with_custom_limit.status_code == 200
    unconstrained_payload = unconstrained_with_custom_limit.json()
    assert unconstrained_payload["structure_source"] == "auto"
    assert unconstrained_payload["manual_annotation_id"] is None
    assert unconstrained_payload["params"]["source_algorithm"] == "wave-zigzag"
    assert unconstrained_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_payload["params"]["limit_pct"] == 20
    assert unconstrained_payload["params"]["limit_rule"] == "prev_close_20pct"
    assert unconstrained_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_with_decimal_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=false&limit_pct=12.5"
    )
    assert unconstrained_with_decimal_limit.status_code == 200
    unconstrained_decimal_payload = unconstrained_with_decimal_limit.json()
    assert unconstrained_decimal_payload["structure_source"] == "auto"
    assert unconstrained_decimal_payload["manual_annotation_id"] is None
    assert unconstrained_decimal_payload["params"]["source_algorithm"] == "wave-zigzag"
    assert unconstrained_decimal_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_decimal_payload["params"]["limit_pct"] == 12.5
    assert unconstrained_decimal_payload["params"]["limit_rule"] == "prev_close_12.5pct"
    assert unconstrained_decimal_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_decimal_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_with_decimal_plus_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=false&limit_pct=%2B12.5"
    )
    assert unconstrained_with_decimal_plus_limit.status_code == 200
    unconstrained_decimal_plus_payload = unconstrained_with_decimal_plus_limit.json()
    assert unconstrained_decimal_plus_payload["structure_source"] == "auto"
    assert unconstrained_decimal_plus_payload["manual_annotation_id"] is None
    assert unconstrained_decimal_plus_payload["params"]["source_algorithm"] == "wave-zigzag"
    assert unconstrained_decimal_plus_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_decimal_plus_payload["params"]["limit_pct"] == 12.5
    assert unconstrained_decimal_plus_payload["params"]["limit_rule"] == "prev_close_12.5pct"
    assert unconstrained_decimal_plus_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_decimal_plus_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_with_scientific_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=false&limit_pct=1e1"
    )
    assert unconstrained_with_scientific_limit.status_code == 200
    unconstrained_scientific_payload = unconstrained_with_scientific_limit.json()
    assert unconstrained_scientific_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_scientific_payload["params"]["limit_pct"] == 10
    assert unconstrained_scientific_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert unconstrained_scientific_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_scientific_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_with_scientific_upper_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=false&limit_pct=1E1"
    )
    assert unconstrained_with_scientific_upper_limit.status_code == 200
    unconstrained_scientific_upper_payload = unconstrained_with_scientific_upper_limit.json()
    assert unconstrained_scientific_upper_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_scientific_upper_payload["params"]["limit_pct"] == 10
    assert unconstrained_scientific_upper_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert unconstrained_scientific_upper_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_scientific_upper_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_with_scientific_plus_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=false&limit_pct=%2B1e1"
    )
    assert unconstrained_with_scientific_plus_limit.status_code == 200
    unconstrained_scientific_plus_payload = unconstrained_with_scientific_plus_limit.json()
    assert unconstrained_scientific_plus_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_scientific_plus_payload["params"]["limit_pct"] == 10
    assert unconstrained_scientific_plus_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert unconstrained_scientific_plus_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_scientific_plus_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_with_scientific_plus_upper_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=false&limit_pct=%2B1E1"
    )
    assert unconstrained_with_scientific_plus_upper_limit.status_code == 200
    unconstrained_scientific_plus_upper_payload = unconstrained_with_scientific_plus_upper_limit.json()
    assert unconstrained_scientific_plus_upper_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_scientific_plus_upper_payload["params"]["limit_pct"] == 10
    assert unconstrained_scientific_plus_upper_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert unconstrained_scientific_plus_upper_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_scientific_plus_upper_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_with_scientific_plus_upper_spaced_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=false&limit_pct=%20%2B1E1%20"
    )
    assert unconstrained_with_scientific_plus_upper_spaced_limit.status_code == 200
    unconstrained_scientific_plus_upper_spaced_payload = unconstrained_with_scientific_plus_upper_spaced_limit.json()
    assert unconstrained_scientific_plus_upper_spaced_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_scientific_plus_upper_spaced_payload["params"]["limit_pct"] == 10
    assert unconstrained_scientific_plus_upper_spaced_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert unconstrained_scientific_plus_upper_spaced_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_scientific_plus_upper_spaced_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_with_scientific_plus_spaced_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=false&limit_pct=%20%2B1e1%20"
    )
    assert unconstrained_with_scientific_plus_spaced_limit.status_code == 200
    unconstrained_scientific_plus_spaced_payload = unconstrained_with_scientific_plus_spaced_limit.json()
    assert unconstrained_scientific_plus_spaced_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_scientific_plus_spaced_payload["params"]["limit_pct"] == 10
    assert unconstrained_scientific_plus_spaced_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert unconstrained_scientific_plus_spaced_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_scientific_plus_spaced_payload["params"]["skipped_limit_down_exits"] == 0

    unconstrained_with_scientific_plus_min_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=false&limit_pct=%2B1e-1"
    )
    assert unconstrained_with_scientific_plus_min_limit.status_code == 200
    unconstrained_scientific_plus_min_payload = unconstrained_with_scientific_plus_min_limit.json()
    assert unconstrained_scientific_plus_min_payload["params"]["apply_limit_constraints"] is False
    assert unconstrained_scientific_plus_min_payload["params"]["limit_pct"] == 0.1
    assert unconstrained_scientific_plus_min_payload["params"]["limit_rule"] == "prev_close_0.1pct"
    assert unconstrained_scientific_plus_min_payload["params"]["skipped_limit_up_entries"] == 0
    assert unconstrained_scientific_plus_min_payload["params"]["skipped_limit_down_exits"] == 0

    constrained_with_custom_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=true&limit_pct=20"
    )
    assert constrained_with_custom_limit.status_code == 200
    constrained_payload = constrained_with_custom_limit.json()
    assert constrained_payload["structure_source"] == "auto"
    assert constrained_payload["manual_annotation_id"] is None
    assert constrained_payload["params"]["source_algorithm"] == "wave-zigzag"
    assert constrained_payload["params"]["apply_limit_constraints"] is True
    assert constrained_payload["params"]["limit_pct"] == 20
    assert constrained_payload["params"]["limit_rule"] == "prev_close_20pct"
    assert "skipped_limit_up_entries" in constrained_payload["params"]
    assert "skipped_limit_down_exits" in constrained_payload["params"]
    assert constrained_payload["params"]["skipped_limit_up_entries"] >= 0
    assert constrained_payload["params"]["skipped_limit_down_exits"] >= 0

    constrained_with_scientific_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=true&limit_pct=1e1"
    )
    assert constrained_with_scientific_limit.status_code == 200
    constrained_scientific_payload = constrained_with_scientific_limit.json()
    assert constrained_scientific_payload["params"]["apply_limit_constraints"] is True
    assert constrained_scientific_payload["params"]["limit_pct"] == 10
    assert constrained_scientific_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert constrained_scientific_payload["params"]["skipped_limit_up_entries"] >= 0
    assert constrained_scientific_payload["params"]["skipped_limit_down_exits"] >= 0

    constrained_with_scientific_upper_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=true&limit_pct=1E1"
    )
    assert constrained_with_scientific_upper_limit.status_code == 200
    constrained_scientific_upper_payload = constrained_with_scientific_upper_limit.json()
    assert constrained_scientific_upper_payload["params"]["apply_limit_constraints"] is True
    assert constrained_scientific_upper_payload["params"]["limit_pct"] == 10
    assert constrained_scientific_upper_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert constrained_scientific_upper_payload["params"]["skipped_limit_up_entries"] >= 0
    assert constrained_scientific_upper_payload["params"]["skipped_limit_down_exits"] >= 0

    constrained_with_scientific_plus_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=true&limit_pct=%2B1e1"
    )
    assert constrained_with_scientific_plus_limit.status_code == 200
    constrained_scientific_plus_payload = constrained_with_scientific_plus_limit.json()
    assert constrained_scientific_plus_payload["params"]["apply_limit_constraints"] is True
    assert constrained_scientific_plus_payload["params"]["limit_pct"] == 10
    assert constrained_scientific_plus_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert constrained_scientific_plus_payload["params"]["skipped_limit_up_entries"] >= 0
    assert constrained_scientific_plus_payload["params"]["skipped_limit_down_exits"] >= 0

    constrained_with_scientific_plus_upper_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=true&limit_pct=%2B1E1"
    )
    assert constrained_with_scientific_plus_upper_limit.status_code == 200
    constrained_scientific_plus_upper_payload = constrained_with_scientific_plus_upper_limit.json()
    assert constrained_scientific_plus_upper_payload["params"]["apply_limit_constraints"] is True
    assert constrained_scientific_plus_upper_payload["params"]["limit_pct"] == 10
    assert constrained_scientific_plus_upper_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert constrained_scientific_plus_upper_payload["params"]["skipped_limit_up_entries"] >= 0
    assert constrained_scientific_plus_upper_payload["params"]["skipped_limit_down_exits"] >= 0

    constrained_with_scientific_plus_upper_spaced_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=true&limit_pct=%20%2B1E1%20"
    )
    assert constrained_with_scientific_plus_upper_spaced_limit.status_code == 200
    constrained_scientific_plus_upper_spaced_payload = constrained_with_scientific_plus_upper_spaced_limit.json()
    assert constrained_scientific_plus_upper_spaced_payload["params"]["apply_limit_constraints"] is True
    assert constrained_scientific_plus_upper_spaced_payload["params"]["limit_pct"] == 10
    assert constrained_scientific_plus_upper_spaced_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert constrained_scientific_plus_upper_spaced_payload["params"]["skipped_limit_up_entries"] >= 0
    assert constrained_scientific_plus_upper_spaced_payload["params"]["skipped_limit_down_exits"] >= 0

    constrained_with_scientific_plus_spaced_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=true&limit_pct=%20%2B1e1%20"
    )
    assert constrained_with_scientific_plus_spaced_limit.status_code == 200
    constrained_scientific_plus_spaced_payload = constrained_with_scientific_plus_spaced_limit.json()
    assert constrained_scientific_plus_spaced_payload["params"]["apply_limit_constraints"] is True
    assert constrained_scientific_plus_spaced_payload["params"]["limit_pct"] == 10
    assert constrained_scientific_plus_spaced_payload["params"]["limit_rule"] == "prev_close_10pct"
    assert constrained_scientific_plus_spaced_payload["params"]["skipped_limit_up_entries"] >= 0
    assert constrained_scientific_plus_spaced_payload["params"]["skipped_limit_down_exits"] >= 0

    constrained_with_scientific_plus_max_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=true&limit_pct=%2B3e1"
    )
    assert constrained_with_scientific_plus_max_limit.status_code == 200
    constrained_scientific_plus_max_payload = constrained_with_scientific_plus_max_limit.json()
    assert constrained_scientific_plus_max_payload["params"]["apply_limit_constraints"] is True
    assert constrained_scientific_plus_max_payload["params"]["limit_pct"] == 30
    assert constrained_scientific_plus_max_payload["params"]["limit_rule"] == "prev_close_30pct"
    assert constrained_scientific_plus_max_payload["params"]["skipped_limit_up_entries"] >= 0
    assert constrained_scientific_plus_max_payload["params"]["skipped_limit_down_exits"] >= 0

    constrained_with_min_plus_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=true&limit_pct=%2B0.1"
    )
    assert constrained_with_min_plus_limit.status_code == 200
    constrained_min_plus_payload = constrained_with_min_plus_limit.json()
    assert constrained_min_plus_payload["params"]["apply_limit_constraints"] is True
    assert constrained_min_plus_payload["params"]["limit_pct"] == 0.1
    assert constrained_min_plus_payload["params"]["limit_rule"] == "prev_close_0.1pct"
    assert constrained_min_plus_payload["params"]["skipped_limit_up_entries"] >= 0
    assert constrained_min_plus_payload["params"]["skipped_limit_down_exits"] >= 0


def test_wave_backtest_ignores_manual_chan_when_no_manual_wave(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert imported.status_code == 200

    manual_chan = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "chan",
            "payload": {
                "active": True,
                "chan_algorithm": "chan-fractal",
                "chan_version": "0.5.0",
                "fractals": [
                    {"index": 1, "trade_date": "2026-05-18", "price": 8.9, "kind": "top"},
                    {"index": 2, "trade_date": "2026-05-19", "price": 9.2, "kind": "bottom"},
                    {"index": 4, "trade_date": "2026-05-21", "price": 10.4, "kind": "top"},
                ],
            },
        },
    )
    assert manual_chan.status_code == 200

    wave_backtest = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8"
    )
    assert wave_backtest.status_code == 200
    wave_payload = wave_backtest.json()
    assert wave_payload["structure_source"] == "auto"
    assert wave_payload["manual_annotation_id"] is None
    assert wave_payload["params"]["source_algorithm"] == "wave-zigzag"
    assert wave_payload["params"]["strategy_condition_key"] == "wave_zigzag_reversal"


def test_wave_backtest_falls_back_to_auto_when_manual_wave_inactive_even_with_manual_chan_active(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    assert imported.status_code == 200

    manual_chan = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "chan",
            "payload": {
                "active": True,
                "chan_algorithm": "chan-fractal",
                "chan_version": "0.5.0",
                "fractals": [
                    {"index": 1, "trade_date": "2026-05-18", "price": 8.9, "kind": "top"},
                    {"index": 2, "trade_date": "2026-05-19", "price": 9.2, "kind": "bottom"},
                    {"index": 4, "trade_date": "2026-05-21", "price": 10.4, "kind": "top"},
                ],
            },
        },
    )
    assert manual_chan.status_code == 200

    manual_wave = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "wave",
            "payload": {
                "active": False,
                "wave_algorithm": "wave-zigzag",
                "wave_version": "0.1.0",
                "threshold_pct": 8,
                "pivots": [
                    {"index": 0, "trade_date": "2026-05-11", "price": 8.4, "kind": "start", "wave_no": 1},
                    {"index": 1, "trade_date": "2026-05-18", "price": 8.9, "kind": "bottom", "wave_no": 2},
                    {"index": 3, "trade_date": "2026-05-20", "price": 10.1, "kind": "top", "wave_no": 3},
                ],
            },
        },
    )
    assert manual_wave.status_code == 200

    wave_analysis = client.get("/api/analysis/wave?symbol=sh600000&timeframe=D&threshold_pct=8")
    assert wave_analysis.status_code == 200
    wave_analysis_payload = wave_analysis.json()
    assert wave_analysis_payload["algorithm"] == "wave-zigzag"

    wave_backtest = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8"
    )
    assert wave_backtest.status_code == 200
    wave_payload = wave_backtest.json()
    assert wave_payload["structure_source"] == "auto"
    assert wave_payload["manual_annotation_id"] is None
    assert wave_payload["params"]["source_algorithm"] == "wave-zigzag"
    assert wave_payload["params"]["strategy_condition_key"] == "wave_zigzag_reversal"

    wave_backtest_with_decimal_limit = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=false&limit_pct=12.5"
    )
    assert wave_backtest_with_decimal_limit.status_code == 200
    wave_backtest_with_decimal_limit_payload = wave_backtest_with_decimal_limit.json()
    assert wave_backtest_with_decimal_limit_payload["structure_source"] == "auto"
    assert wave_backtest_with_decimal_limit_payload["manual_annotation_id"] is None
    assert wave_backtest_with_decimal_limit_payload["params"]["source_algorithm"] == "wave-zigzag"
    assert wave_backtest_with_decimal_limit_payload["params"]["strategy_condition_key"] == "wave_zigzag_reversal"
    assert wave_backtest_with_decimal_limit_payload["params"]["apply_limit_constraints"] is False
    assert wave_backtest_with_decimal_limit_payload["params"]["limit_pct"] == 12.5
    assert wave_backtest_with_decimal_limit_payload["params"]["limit_rule"] == "prev_close_12.5pct"
    assert wave_backtest_with_decimal_limit_payload["params"]["skipped_limit_up_entries"] == 0
    assert wave_backtest_with_decimal_limit_payload["params"]["skipped_limit_down_exits"] == 0


def test_analysis_and_backtest_use_next_valid_manual_chan_when_latest_manual_invalid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="invalid-manual-chan-newest",
            symbol="sh600001",
            timeframe="D",
            overlay_type="chan",
            payload={
                "active": True,
                "fractals": [{"index": 1, "trade_date": "2026-06-02", "price": 12.0, "kind": "invalid-kind"}],
            },
            created_at=now,
            updated_at=now,
        ),
        AnnotationRecord(
            id="valid-manual-chan-older",
            symbol="sh600001",
            timeframe="D",
            overlay_type="chan",
            payload={
                "active": True,
                "params": {"min_bars_for_bi": 1},
                "fractals": [
                    {"index": 1, "trade_date": "2026-06-02", "price": 12.0, "kind": "top"},
                    {"index": 2, "trade_date": "2026-06-03", "price": 8.0, "kind": "bottom"},
                    {"index": 3, "trade_date": "2026-06-04", "price": 13.0, "kind": "top"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    chan_analysis = client.get("/api/analysis/chan?symbol=sh600001&timeframe=D")
    assert chan_analysis.status_code == 200
    chan_payload = chan_analysis.json()
    assert chan_payload["algorithm"] == "manual-chan"
    assert chan_payload["params"]["derived_from_manual_fractals"] is True

    backtest = client.get("/api/backtests/structure?symbol=sh600001&timeframe=D")
    assert backtest.status_code == 200
    backtest_payload = backtest.json()
    assert backtest_payload["structure_source"] == "manual"
    assert backtest_payload["manual_annotation_id"] == "valid-manual-chan-older"
    assert backtest_payload["params"]["source_algorithm"] == "manual-chan"


def test_analysis_and_backtest_use_next_valid_manual_wave_when_latest_manual_invalid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="invalid-manual-wave-newest",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": 8,
                "pivots": [{"index": 1, "trade_date": "2026-06-02", "price": 12.0, "kind": "top"}],
            },
            created_at=now,
            updated_at=now,
        ),
        AnnotationRecord(
            id="valid-manual-wave-older",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": 8,
                "pivots": [
                    {"index": 0, "trade_date": "2026-06-01", "price": 9.0, "kind": "start", "wave_no": 1},
                    {"index": 2, "trade_date": "2026-06-03", "price": 8.0, "kind": "bottom", "wave_no": 2},
                    {"index": 3, "trade_date": "2026-06-04", "price": 13.0, "kind": "top", "wave_no": 3},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    wave_analysis = client.get("/api/analysis/wave?symbol=sh600001&timeframe=D&threshold_pct=8")
    assert wave_analysis.status_code == 200
    wave_payload = wave_analysis.json()
    assert wave_payload["algorithm"] == "manual-wave"
    assert wave_payload["threshold_pct"] == 8

    backtest = client.get("/api/backtests/structure?symbol=sh600001&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8")
    assert backtest.status_code == 200
    backtest_payload = backtest.json()
    assert backtest_payload["structure_source"] == "manual"
    assert backtest_payload["manual_annotation_id"] == "valid-manual-wave-older"
    assert backtest_payload["params"]["source_algorithm"] == "manual-wave"


def test_analysis_and_backtest_use_next_valid_manual_chan_when_latest_manual_has_invalid_trade_dates(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="invalid-date-manual-chan-newest",
            symbol="sh600001",
            timeframe="D",
            overlay_type="chan",
            payload={
                "active": True,
                "fractals": [
                    {"index": 1, "trade_date": "2026-06-31", "price": 12.0, "kind": "top"},
                    {"index": 2, "trade_date": "bad-date", "price": 8.0, "kind": "bottom"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
        AnnotationRecord(
            id="valid-date-manual-chan-older",
            symbol="sh600001",
            timeframe="D",
            overlay_type="chan",
            payload={
                "active": True,
                "params": {"min_bars_for_bi": 1},
                "fractals": [
                    {"index": 1, "trade_date": "2026-06-02", "price": 12.0, "kind": "top"},
                    {"index": 2, "trade_date": "2026-06-03", "price": 8.0, "kind": "bottom"},
                    {"index": 3, "trade_date": "2026-06-04", "price": 13.0, "kind": "top"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    chan_analysis = client.get("/api/analysis/chan?symbol=sh600001&timeframe=D")
    assert chan_analysis.status_code == 200
    chan_payload = chan_analysis.json()
    assert chan_payload["algorithm"] == "manual-chan"

    backtest = client.get("/api/backtests/structure?symbol=sh600001&timeframe=D")
    assert backtest.status_code == 200
    backtest_payload = backtest.json()
    assert backtest_payload["structure_source"] == "manual"
    assert backtest_payload["manual_annotation_id"] == "valid-date-manual-chan-older"
    assert backtest_payload["params"]["source_algorithm"] == "manual-chan"


def test_analysis_and_backtest_use_next_valid_manual_wave_when_latest_manual_has_invalid_trade_dates(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="invalid-date-manual-wave-newest",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": 8,
                "pivots": [
                    {"index": 0, "trade_date": "2026-13-01", "price": 9.0, "kind": "start", "wave_no": 1},
                    {"index": 2, "trade_date": "not-a-date", "price": 8.0, "kind": "bottom", "wave_no": 2},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
        AnnotationRecord(
            id="valid-date-manual-wave-older",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": 8,
                "pivots": [
                    {"index": 0, "trade_date": "2026-06-01", "price": 9.0, "kind": "start", "wave_no": 1},
                    {"index": 2, "trade_date": "2026-06-03", "price": 8.0, "kind": "bottom", "wave_no": 2},
                    {"index": 3, "trade_date": "2026-06-04", "price": 13.0, "kind": "top", "wave_no": 3},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    wave_analysis = client.get("/api/analysis/wave?symbol=sh600001&timeframe=D&threshold_pct=8")
    assert wave_analysis.status_code == 200
    wave_payload = wave_analysis.json()
    assert wave_payload["algorithm"] == "manual-wave"

    backtest = client.get("/api/backtests/structure?symbol=sh600001&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8")
    assert backtest.status_code == 200
    backtest_payload = backtest.json()
    assert backtest_payload["structure_source"] == "manual"
    assert backtest_payload["manual_annotation_id"] == "valid-date-manual-wave-older"
    assert backtest_payload["params"]["source_algorithm"] == "manual-wave"


def test_manual_chan_analysis_normalizes_alias_kind_and_numeric_string_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-chan-alias-kind",
            symbol="sh600001",
            timeframe="D",
            overlay_type="chan",
            payload={
                "active": True,
                "params": {"min_bars_for_bi": "1"},
                "fractals": [
                    {"index": "1", "trade_date": "2026-06-02", "price": "12.0", "kind": "high"},
                    {"index": "2", "trade_date": "2026-06-03", "price": "8.0", "kind": "low"},
                    {"index": "3", "trade_date": "2026-06-04", "price": "13.0", "kind": "top"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    chan_analysis = client.get("/api/analysis/chan?symbol=sh600001&timeframe=D")
    assert chan_analysis.status_code == 200
    chan_payload = chan_analysis.json()
    assert chan_payload["algorithm"] == "manual-chan"
    assert chan_payload["params"]["derived_from_manual_fractals"] is True
    assert [item["kind"] for item in chan_payload["fractals"]] == ["top", "bottom", "top"]
    assert len(chan_payload["bis"]) >= 1

    backtest = client.get("/api/backtests/structure?symbol=sh600001&timeframe=D")
    assert backtest.status_code == 200
    backtest_payload = backtest.json()
    assert backtest_payload["structure_source"] == "manual"
    assert backtest_payload["manual_annotation_id"] == "manual-chan-alias-kind"
    assert backtest_payload["params"]["source_algorithm"] == "manual-chan"


def test_manual_wave_analysis_normalizes_alias_kind_and_numeric_string_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-wave-alias-kind",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": "8.5",
                "pivots": [
                    {"index": "0", "trade_date": "2026-06-01", "price": "9.0", "kind": "low", "wave_no": "1"},
                    {"index": "2", "trade_date": "2026-06-03", "price": "8.5", "kind": "bottom", "wave_no": "2"},
                    {"index": 3, "trade_date": "2026-06-04", "price": 13.0, "kind": "high", "wave_no": "9"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    wave_analysis = client.get("/api/analysis/wave?symbol=sh600001&timeframe=D&threshold_pct=5")
    assert wave_analysis.status_code == 200
    wave_payload = wave_analysis.json()
    assert wave_payload["algorithm"] == "manual-wave"
    assert wave_payload["threshold_pct"] == 8.5
    assert [item["kind"] for item in wave_payload["pivots"]] == ["bottom", "bottom", "top"]
    assert [item["wave_no"] for item in wave_payload["pivots"]] == [1, 2, 9]


def test_manual_chan_analysis_trims_trade_date_and_skips_blank_points(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-chan-trim-date",
            symbol="sh600001",
            timeframe="D",
            overlay_type="chan",
            payload={
                "active": True,
                "params": {"min_bars_for_bi": "1"},
                "fractals": [
                    {"index": "1", "trade_date": " 2026-06-02 ", "price": "12.0", "kind": "high"},
                    {"index": "2", "trade_date": "   ", "price": "8.0", "kind": "low"},
                    {"index": "3", "trade_date": "\t2026-06-04\t", "price": "13.0", "kind": "top"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    chan_analysis = client.get("/api/analysis/chan?symbol=sh600001&timeframe=D")
    assert chan_analysis.status_code == 200
    chan_payload = chan_analysis.json()
    assert chan_payload["algorithm"] == "manual-chan"
    assert [item["trade_date"] for item in chan_payload["fractals"]] == ["2026-06-02", "2026-06-04"]
    assert [item["kind"] for item in chan_payload["fractals"]] == ["top", "top"]


def test_manual_wave_analysis_trims_trade_date_and_skips_blank_points(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-wave-trim-date",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": "8.5",
                "pivots": [
                    {"index": "0", "trade_date": " 2026-06-01 ", "price": "9.0", "kind": "start", "wave_no": "1"},
                    {"index": "1", "trade_date": "   ", "price": "10.0", "kind": "top", "wave_no": "2"},
                    {"index": "2", "trade_date": "\t2026-06-03\t", "price": "8.5", "kind": "low", "wave_no": "3"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    wave_analysis = client.get("/api/analysis/wave?symbol=sh600001&timeframe=D&threshold_pct=5")
    assert wave_analysis.status_code == 200
    wave_payload = wave_analysis.json()
    assert wave_payload["algorithm"] == "manual-wave"
    assert [item["trade_date"] for item in wave_payload["pivots"]] == ["2026-06-01", "2026-06-03"]
    assert [item["kind"] for item in wave_payload["pivots"]] == ["start", "bottom"]
    assert [item["wave_no"] for item in wave_payload["pivots"]] == [1, 3]


def test_manual_chan_analysis_skips_invalid_trade_date_points(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-chan-invalid-date",
            symbol="sh600001",
            timeframe="D",
            overlay_type="chan",
            payload={
                "active": True,
                "fractals": [
                    {"index": "1", "trade_date": "2026-06-02", "price": "12.0", "kind": "high"},
                    {"index": "2", "trade_date": "2026-06-31", "price": "8.0", "kind": "low"},
                    {"index": "3", "trade_date": "not-a-date", "price": "13.0", "kind": "top"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    chan_analysis = client.get("/api/analysis/chan?symbol=sh600001&timeframe=D")
    assert chan_analysis.status_code == 200
    chan_payload = chan_analysis.json()
    assert chan_payload["algorithm"] == "manual-chan"
    assert [item["trade_date"] for item in chan_payload["fractals"]] == ["2026-06-02"]
    assert [item["kind"] for item in chan_payload["fractals"]] == ["top"]


def test_manual_wave_analysis_skips_invalid_trade_date_points(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-wave-invalid-date",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": "8.5",
                "pivots": [
                    {"index": "0", "trade_date": "2026-06-01", "price": "9.0", "kind": "start", "wave_no": "1"},
                    {"index": "1", "trade_date": "2026-13-01", "price": "10.0", "kind": "top", "wave_no": "2"},
                    {"index": "2", "trade_date": "bad-date", "price": "8.5", "kind": "low", "wave_no": "3"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    wave_analysis = client.get("/api/analysis/wave?symbol=sh600001&timeframe=D&threshold_pct=5")
    assert wave_analysis.status_code == 200
    wave_payload = wave_analysis.json()
    assert wave_payload["algorithm"] == "manual-wave"
    assert [item["trade_date"] for item in wave_payload["pivots"]] == ["2026-06-01"]
    assert [item["kind"] for item in wave_payload["pivots"]] == ["start"]
    assert [item["wave_no"] for item in wave_payload["pivots"]] == [1]


def test_manual_chan_analysis_supports_minute_trade_datetime_strings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-chan-minute-trade-date",
            symbol="sh600001",
            timeframe="15M",
            overlay_type="chan",
            payload={
                "active": True,
                "fractals": [
                    {"index": "1", "trade_date": "2026-06-02T09:35:00", "price": "12.0", "kind": "high"},
                    {"index": "2", "trade_date": "2026-06-02 09:40", "price": "8.0", "kind": "low"},
                    {"index": "3", "trade_date": "2026-06-02T09:45", "price": "13.0", "kind": "top"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    chan_analysis = client.get("/api/analysis/chan?symbol=sh600001&timeframe=15m")
    assert chan_analysis.status_code == 200
    chan_payload = chan_analysis.json()
    assert chan_payload["algorithm"] == "manual-chan"
    assert [item["trade_date"] for item in chan_payload["fractals"]] == [
        "2026-06-02T09:35",
        "2026-06-02T09:40",
        "2026-06-02T09:45",
    ]


def test_manual_wave_analysis_supports_minute_trade_datetime_strings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-wave-minute-trade-date",
            symbol="sh600001",
            timeframe="15M",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": "8.5",
                "pivots": [
                    {"index": "0", "trade_date": "2026-06-02T09:35:00", "price": "9.0", "kind": "start", "wave_no": "1"},
                    {"index": "2", "trade_date": "2026-06-02 09:40", "price": "8.5", "kind": "low", "wave_no": "2"},
                    {"index": "3", "trade_date": "2026-06-02T09:45", "price": "13.0", "kind": "high", "wave_no": "3"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    wave_analysis = client.get("/api/analysis/wave?symbol=sh600001&timeframe=15m&threshold_pct=5")
    assert wave_analysis.status_code == 200
    wave_payload = wave_analysis.json()
    assert wave_payload["algorithm"] == "manual-wave"
    assert [item["trade_date"] for item in wave_payload["pivots"]] == [
        "2026-06-02T09:35",
        "2026-06-02T09:40",
        "2026-06-02T09:45",
    ]


def test_manual_chan_analysis_supports_timezone_trade_datetime_strings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-chan-timezone-trade-date",
            symbol="sh600001",
            timeframe="15M",
            overlay_type="chan",
            payload={
                "active": True,
                "fractals": [
                    {"index": "1", "trade_date": "2026-06-02T09:35:00z", "price": "12.0", "kind": "high"},
                    {"index": "2", "trade_date": "2026-06-02T09:40:00+08", "price": "8.0", "kind": "low"},
                    {"index": "3", "trade_date": "2026-06-02T09:45+08:00", "price": "13.0", "kind": "top"},
                    {"index": "4", "trade_date": "2026-06-02T10:00:00-05", "price": "11.5", "kind": "high"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    chan_analysis = client.get("/api/analysis/chan?symbol=sh600001&timeframe=15m")
    assert chan_analysis.status_code == 200
    chan_payload = chan_analysis.json()
    assert chan_payload["algorithm"] == "manual-chan"
    assert [item["trade_date"] for item in chan_payload["fractals"]] == [
        "2026-06-02T09:35+00:00",
        "2026-06-02T09:40+08:00",
        "2026-06-02T09:45+08:00",
        "2026-06-02T10:00-05:00",
    ]

    manual_annotations[0].payload["fractals"] = [
        {"index": "1", "trade_date": "2026-06-02T09:35:00z", "price": "12.0", "kind": "high"},
        {"index": "2", "trade_date": "2026-06-02T09:40:00+0800", "price": "8.0", "kind": "low"},
        {"index": "3", "trade_date": "2026-06-02T09:45+08:00", "price": "13.0", "kind": "top"},
        {"index": "4", "trade_date": "2026-06-02T10:00:00-0530", "price": "11.5", "kind": "high"},
    ]
    chan_analysis_half_hour_offset = client.get("/api/analysis/chan?symbol=sh600001&timeframe=15m")
    assert chan_analysis_half_hour_offset.status_code == 200
    assert [item["trade_date"] for item in chan_analysis_half_hour_offset.json()["fractals"]] == [
        "2026-06-02T09:35+00:00",
        "2026-06-02T09:40+08:00",
        "2026-06-02T09:45+08:00",
        "2026-06-02T10:00-05:30",
    ]


def test_manual_wave_analysis_supports_timezone_trade_datetime_strings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-wave-timezone-trade-date",
            symbol="sh600001",
            timeframe="15M",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": "8.5",
                "pivots": [
                    {"index": "0", "trade_date": "2026-06-02T09:35:00z", "price": "9.0", "kind": "start", "wave_no": "1"},
                    {"index": "2", "trade_date": "2026-06-02T09:40:00+08", "price": "8.5", "kind": "low", "wave_no": "2"},
                    {"index": "3", "trade_date": "2026-06-02T09:45+08:00", "price": "13.0", "kind": "high", "wave_no": "3"},
                    {"index": "4", "trade_date": "2026-06-02T10:00:00-05", "price": "12.1", "kind": "top", "wave_no": "4"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    wave_analysis = client.get("/api/analysis/wave?symbol=sh600001&timeframe=15m&threshold_pct=5")
    assert wave_analysis.status_code == 200
    wave_payload = wave_analysis.json()
    assert wave_payload["algorithm"] == "manual-wave"
    assert [item["trade_date"] for item in wave_payload["pivots"]] == [
        "2026-06-02T09:35+00:00",
        "2026-06-02T09:40+08:00",
        "2026-06-02T09:45+08:00",
        "2026-06-02T10:00-05:00",
    ]

    manual_annotations[0].payload["pivots"] = [
        {"index": "0", "trade_date": "2026-06-02T09:35:00z", "price": "9.0", "kind": "start", "wave_no": "1"},
        {"index": "2", "trade_date": "2026-06-02T09:40:00+0800", "price": "8.5", "kind": "low", "wave_no": "2"},
        {"index": "3", "trade_date": "2026-06-02T09:45+08:00", "price": "13.0", "kind": "high", "wave_no": "3"},
        {"index": "4", "trade_date": "2026-06-02T10:00:00-0530", "price": "12.1", "kind": "top", "wave_no": "4"},
    ]
    wave_analysis_half_hour_offset = client.get("/api/analysis/wave?symbol=sh600001&timeframe=15m&threshold_pct=5")
    assert wave_analysis_half_hour_offset.status_code == 200
    assert [item["trade_date"] for item in wave_analysis_half_hour_offset.json()["pivots"]] == [
        "2026-06-02T09:35+00:00",
        "2026-06-02T09:40+08:00",
        "2026-06-02T09:45+08:00",
        "2026-06-02T10:00-05:30",
    ]


def test_manual_timezone_trade_dates_are_usable_in_structure_backtests(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-chan-timezone-backtest",
            symbol="sh600001",
            timeframe="D",
            overlay_type="chan",
            payload={
                "active": True,
                "params": {"min_bars_for_bi": 1},
                "fractals": [
                    {"index": 1, "trade_date": "2026-06-02T09:35:00z", "price": 12.0, "kind": "top"},
                    {"index": 2, "trade_date": "2026-06-03T09:40:00+0800", "price": 8.0, "kind": "bottom"},
                    {"index": 3, "trade_date": "2026-06-04T10:00:00-0530", "price": 13.0, "kind": "top"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
        AnnotationRecord(
            id="manual-wave-timezone-backtest",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": 8,
                "pivots": [
                    {"index": 0, "trade_date": "2026-06-01T09:35:00z", "price": 9.0, "kind": "start", "wave_no": 1},
                    {"index": 2, "trade_date": "2026-06-03T09:40:00+0800", "price": 8.0, "kind": "bottom", "wave_no": 2},
                    {"index": 3, "trade_date": "2026-06-04T10:00:00-0530", "price": 13.0, "kind": "top", "wave_no": 3},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    chan_backtest = client.get(
        "/api/backtests/structure?symbol=sh600001&timeframe=D&apply_limit_constraints=true&limit_pct=20"
    )
    assert chan_backtest.status_code == 200
    chan_backtest_payload = chan_backtest.json()
    assert chan_backtest_payload["structure_source"] == "manual"
    assert chan_backtest_payload["manual_annotation_id"] == "manual-chan-timezone-backtest"
    assert chan_backtest_payload["params"]["source_algorithm"] == "manual-chan"
    assert chan_backtest_payload["params"]["limit_pct"] == 20
    assert chan_backtest_payload["params"]["limit_rule"] == "prev_close_20pct"

    wave_backtest = client.get(
        "/api/backtests/structure?symbol=sh600001&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=true&limit_pct=20"
    )
    assert wave_backtest.status_code == 200
    wave_backtest_payload = wave_backtest.json()
    assert wave_backtest_payload["structure_source"] == "manual"
    assert wave_backtest_payload["manual_annotation_id"] == "manual-wave-timezone-backtest"
    assert wave_backtest_payload["params"]["source_algorithm"] == "manual-wave"
    assert wave_backtest_payload["params"]["limit_pct"] == 20
    assert wave_backtest_payload["params"]["limit_rule"] == "prev_close_20pct"

    # Also accept hour-only timezone offsets (+08 / -05) in the same backtest flow.
    manual_annotations[0].payload["fractals"] = [
        {"index": 1, "trade_date": "2026-06-02T09:35:00z", "price": 12.0, "kind": "top"},
        {"index": 2, "trade_date": "2026-06-03T09:40:00+08", "price": 8.0, "kind": "bottom"},
        {"index": 3, "trade_date": "2026-06-04T10:00:00-05", "price": 13.0, "kind": "top"},
    ]
    manual_annotations[1].payload["pivots"] = [
        {"index": 0, "trade_date": "2026-06-01T09:35:00z", "price": 9.0, "kind": "start", "wave_no": 1},
        {"index": 2, "trade_date": "2026-06-03T09:40:00+08", "price": 8.0, "kind": "bottom", "wave_no": 2},
        {"index": 3, "trade_date": "2026-06-04T10:00:00-05", "price": 13.0, "kind": "top", "wave_no": 3},
    ]

    chan_backtest_hour_only_offset = client.get(
        "/api/backtests/structure?symbol=sh600001&timeframe=D&apply_limit_constraints=true&limit_pct=20"
    )
    assert chan_backtest_hour_only_offset.status_code == 200
    chan_backtest_hour_only_offset_payload = chan_backtest_hour_only_offset.json()
    assert chan_backtest_hour_only_offset_payload["structure_source"] == "manual"
    assert chan_backtest_hour_only_offset_payload["manual_annotation_id"] == "manual-chan-timezone-backtest"
    assert chan_backtest_hour_only_offset_payload["params"]["source_algorithm"] == "manual-chan"
    assert chan_backtest_hour_only_offset_payload["params"]["limit_pct"] == 20
    assert chan_backtest_hour_only_offset_payload["params"]["limit_rule"] == "prev_close_20pct"

    wave_backtest_hour_only_offset = client.get(
        "/api/backtests/structure?symbol=sh600001&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=true&limit_pct=20"
    )
    assert wave_backtest_hour_only_offset.status_code == 200
    wave_backtest_hour_only_offset_payload = wave_backtest_hour_only_offset.json()
    assert wave_backtest_hour_only_offset_payload["structure_source"] == "manual"
    assert wave_backtest_hour_only_offset_payload["manual_annotation_id"] == "manual-wave-timezone-backtest"
    assert wave_backtest_hour_only_offset_payload["params"]["source_algorithm"] == "manual-wave"
    assert wave_backtest_hour_only_offset_payload["params"]["limit_pct"] == 20
    assert wave_backtest_hour_only_offset_payload["params"]["limit_rule"] == "prev_close_20pct"


def test_manual_timezone_trade_dates_reject_single_digit_hour_offsets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-chan-invalid-hour-offset",
            symbol="sh600001",
            timeframe="15M",
            overlay_type="chan",
            payload={
                "active": True,
                "fractals": [
                    {"index": "1", "trade_date": "2026-06-02T09:35:00z", "price": "12.0", "kind": "high"},
                    {"index": "2", "trade_date": "2026-06-02T09:40:00+8", "price": "8.0", "kind": "low"},
                    {"index": "3", "trade_date": "2026-06-02T09:45+08:00", "price": "13.0", "kind": "top"},
                    {"index": "4", "trade_date": "2026-06-02T10:00:00-5", "price": "11.5", "kind": "high"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
        AnnotationRecord(
            id="manual-wave-invalid-hour-offset",
            symbol="sh600001",
            timeframe="15M",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": "8.5",
                "pivots": [
                    {"index": "0", "trade_date": "2026-06-02T09:35:00z", "price": "9.0", "kind": "start", "wave_no": "1"},
                    {"index": "2", "trade_date": "2026-06-02T09:40:00+8", "price": "8.5", "kind": "low", "wave_no": "2"},
                    {"index": "3", "trade_date": "2026-06-02T09:45+08:00", "price": "13.0", "kind": "high", "wave_no": "3"},
                    {"index": "4", "trade_date": "2026-06-02T10:00:00-5", "price": "12.1", "kind": "top", "wave_no": "4"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    chan_analysis = client.get("/api/analysis/chan?symbol=sh600001&timeframe=15m")
    assert chan_analysis.status_code == 200
    chan_payload = chan_analysis.json()
    assert chan_payload["algorithm"] == "manual-chan"
    assert [item["trade_date"] for item in chan_payload["fractals"]] == [
        "2026-06-02T09:35+00:00",
        "2026-06-02T09:45+08:00",
    ]

    wave_analysis = client.get("/api/analysis/wave?symbol=sh600001&timeframe=15m&threshold_pct=5")
    assert wave_analysis.status_code == 200
    wave_payload = wave_analysis.json()
    assert wave_payload["algorithm"] == "manual-wave"
    assert [item["trade_date"] for item in wave_payload["pivots"]] == [
        "2026-06-02T09:35+00:00",
        "2026-06-02T09:45+08:00",
    ]


def test_manual_wave_analysis_clamps_threshold_from_numeric_string(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-wave-threshold-clamp",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": "80.5",
                "pivots": [
                    {"index": 0, "trade_date": "2026-06-01", "price": 9.0, "kind": "start", "wave_no": 1},
                    {"index": 2, "trade_date": "2026-06-03", "price": 8.5, "kind": "bottom", "wave_no": 2},
                    {"index": 3, "trade_date": "2026-06-04", "price": 13.0, "kind": "top", "wave_no": 3},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    wave_analysis = client.get("/api/analysis/wave?symbol=sh600001&timeframe=D&threshold_pct=5")
    assert wave_analysis.status_code == 200
    wave_payload = wave_analysis.json()
    assert wave_payload["algorithm"] == "manual-wave"
    assert wave_payload["threshold_pct"] == 50.0


def test_manual_wave_analysis_clamps_negative_threshold_from_numeric_string(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-wave-threshold-clamp-low",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": "-3.2",
                "pivots": [
                    {"index": 0, "trade_date": "2026-06-01", "price": 9.0, "kind": "start", "wave_no": 1},
                    {"index": 2, "trade_date": "2026-06-03", "price": 8.5, "kind": "bottom", "wave_no": 2},
                    {"index": 3, "trade_date": "2026-06-04", "price": 13.0, "kind": "top", "wave_no": 3},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    wave_analysis = client.get("/api/analysis/wave?symbol=sh600001&timeframe=D&threshold_pct=5")
    assert wave_analysis.status_code == 200
    wave_payload = wave_analysis.json()
    assert wave_payload["algorithm"] == "manual-wave"
    assert wave_payload["threshold_pct"] == 0.1


def test_manual_wave_analysis_falls_back_when_threshold_is_not_finite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="manual-wave-threshold-nan",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": "NaN",
                "pivots": [
                    {"index": 0, "trade_date": "2026-06-01", "price": 9.0, "kind": "start", "wave_no": 1},
                    {"index": 2, "trade_date": "2026-06-03", "price": 8.5, "kind": "bottom", "wave_no": 2},
                    {"index": 3, "trade_date": "2026-06-04", "price": 13.0, "kind": "top", "wave_no": 3},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    wave_analysis = client.get("/api/analysis/wave?symbol=sh600001&timeframe=D&threshold_pct=8")
    assert wave_analysis.status_code == 200
    wave_payload = wave_analysis.json()
    assert wave_payload["algorithm"] == "manual-wave"
    assert wave_payload["threshold_pct"] == 8.0


def test_chart_uses_next_valid_manual_chan_when_latest_manual_invalid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="invalid-manual-chan-newest",
            symbol="sh600001",
            timeframe="D",
            overlay_type="chan",
            payload={
                "active": True,
                "fractals": [{"index": 1, "trade_date": "2026-06-02", "price": 12.0, "kind": "invalid-kind"}],
            },
            created_at=now,
            updated_at=now,
        ),
        AnnotationRecord(
            id="valid-manual-chan-older",
            symbol="sh600001",
            timeframe="D",
            overlay_type="chan",
            payload={
                "active": True,
                "params": {"min_bars_for_bi": 1},
                "fractals": [
                    {"index": 1, "trade_date": "2026-06-02", "price": 12.0, "kind": "top"},
                    {"index": 2, "trade_date": "2026-06-03", "price": 8.0, "kind": "bottom"},
                    {"index": 3, "trade_date": "2026-06-04", "price": 13.0, "kind": "top"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    chart = client.get("/api/chart?symbol=sh600001&timeframe=D")
    assert chart.status_code == 200
    chart_payload = chart.json()
    assert chart_payload["chan"]["algorithm"] == "manual-chan"
    assert chart_payload["chan"]["params"]["derived_from_manual_fractals"] is True
    assert len(chart_payload["chan"]["bis"]) >= 1


def test_chart_uses_next_valid_manual_wave_when_latest_manual_invalid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="invalid-manual-wave-newest",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": 8,
                "pivots": [{"index": 1, "trade_date": "2026-06-02", "price": 12.0, "kind": "top"}],
            },
            created_at=now,
            updated_at=now,
        ),
        AnnotationRecord(
            id="valid-manual-wave-older",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": 8,
                "pivots": [
                    {"index": 0, "trade_date": "2026-06-01", "price": 9.0, "kind": "start", "wave_no": 1},
                    {"index": 2, "trade_date": "2026-06-03", "price": 8.0, "kind": "bottom", "wave_no": 2},
                    {"index": 3, "trade_date": "2026-06-04", "price": 13.0, "kind": "top", "wave_no": 3},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    chart = client.get("/api/chart?symbol=sh600001&timeframe=D&threshold_pct=8")
    assert chart.status_code == 200
    chart_payload = chart.json()
    assert chart_payload["wave"]["algorithm"] == "manual-wave"
    assert chart_payload["wave"]["threshold_pct"] == 8
    assert len(chart_payload["wave"]["pivots"]) == 3


def test_chart_uses_next_valid_manual_chan_when_latest_manual_has_invalid_trade_dates(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="invalid-date-manual-chan-newest",
            symbol="sh600001",
            timeframe="D",
            overlay_type="chan",
            payload={
                "active": True,
                "fractals": [
                    {"index": 1, "trade_date": "2026-06-31", "price": 12.0, "kind": "top"},
                    {"index": 2, "trade_date": "bad-date", "price": 8.0, "kind": "bottom"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
        AnnotationRecord(
            id="valid-date-manual-chan-older",
            symbol="sh600001",
            timeframe="D",
            overlay_type="chan",
            payload={
                "active": True,
                "params": {"min_bars_for_bi": 1},
                "fractals": [
                    {"index": 1, "trade_date": "2026-06-02", "price": 12.0, "kind": "top"},
                    {"index": 2, "trade_date": "2026-06-03", "price": 8.0, "kind": "bottom"},
                    {"index": 3, "trade_date": "2026-06-04", "price": 13.0, "kind": "top"},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    chart = client.get("/api/chart?symbol=sh600001&timeframe=D")
    assert chart.status_code == 200
    chart_payload = chart.json()
    assert chart_payload["chan"]["algorithm"] == "manual-chan"
    assert chart_payload["chan"]["params"]["derived_from_manual_fractals"] is True
    assert len(chart_payload["chan"]["bis"]) >= 1


def test_chart_uses_next_valid_manual_wave_when_latest_manual_has_invalid_trade_dates(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    now = datetime.now(timezone.utc)
    manual_annotations = [
        AnnotationRecord(
            id="invalid-date-manual-wave-newest",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": 8,
                "pivots": [
                    {"index": 0, "trade_date": "2026-13-01", "price": 9.0, "kind": "start", "wave_no": 1},
                    {"index": 2, "trade_date": "not-a-date", "price": 8.0, "kind": "bottom", "wave_no": 2},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
        AnnotationRecord(
            id="valid-date-manual-wave-older",
            symbol="sh600001",
            timeframe="D",
            overlay_type="wave",
            payload={
                "active": True,
                "threshold_pct": 8,
                "pivots": [
                    {"index": 0, "trade_date": "2026-06-01", "price": 9.0, "kind": "start", "wave_no": 1},
                    {"index": 2, "trade_date": "2026-06-03", "price": 8.0, "kind": "bottom", "wave_no": 2},
                    {"index": 3, "trade_date": "2026-06-04", "price": 13.0, "kind": "top", "wave_no": 3},
                ],
            },
            created_at=now,
            updated_at=now,
        ),
    ]
    monkeypatch.setattr("app.main.list_annotations", lambda conn, symbol, timeframe: manual_annotations)

    client = TestClient(app)
    chart = client.get("/api/chart?symbol=sh600001&timeframe=D&threshold_pct=8")
    assert chart.status_code == 200
    chart_payload = chart.json()
    assert chart_payload["wave"]["algorithm"] == "manual-wave"
    assert chart_payload["wave"]["threshold_pct"] == 8
    assert len(chart_payload["wave"]["pivots"]) == 3


def test_structure_backtest_endpoint_rejects_out_of_range_limit_pct(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)

    too_small = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=0.09")
    too_large = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=30.1")
    scientific_too_small = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=9e-2")
    scientific_too_large = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=3.01e1")
    scientific_plus_too_small = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%2B9e-2")
    scientific_plus_too_large = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%2B3.01e1")
    scientific_negative_too_small_spaced = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%20-9e-2%20"
    )
    scientific_negative_too_large_spaced = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%20-3.01e1%20"
    )
    not_a_number = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=NaN")
    not_a_number_lower = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=nan")
    not_a_number_spaced = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%20NaN%20")
    not_a_number_lower_spaced = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%20nan%20")
    positive_infinity = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=Infinity")
    positive_infinity_lower = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=inf")
    positive_infinity_plus = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%2BInfinity")
    positive_infinity_plus_lower = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%2Binf")
    positive_infinity_spaced = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%20Infinity%20")
    positive_infinity_lower_spaced = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%20inf%20")
    positive_infinity_plus_spaced = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%20%2BInfinity%20")
    positive_infinity_plus_lower_spaced = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%20%2Binf%20")
    negative_infinity = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=-Infinity")
    negative_infinity_lower = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=-inf")
    negative_infinity_spaced = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%20-Infinity%20")
    negative_infinity_lower_spaced = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%20-inf%20")
    overflow_positive = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=1e309")
    overflow_positive_plus = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%2B1e309")
    overflow_positive_spaced = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%201e309%20")
    overflow_positive_plus_spaced = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%20%2B1e309%20")
    overflow_negative = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=-1e309")
    overflow_negative_spaced = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&limit_pct=%20-1e309%20")

    assert too_small.status_code == 422
    assert too_large.status_code == 422
    assert scientific_too_small.status_code == 422
    assert scientific_too_large.status_code == 422
    assert scientific_plus_too_small.status_code == 422
    assert scientific_plus_too_large.status_code == 422
    assert scientific_negative_too_small_spaced.status_code == 422
    assert scientific_negative_too_large_spaced.status_code == 422
    assert not_a_number.status_code == 422
    assert not_a_number_lower.status_code == 422
    assert not_a_number_spaced.status_code == 422
    assert not_a_number_lower_spaced.status_code == 422
    assert positive_infinity.status_code == 422
    assert positive_infinity_lower.status_code == 422
    assert positive_infinity_plus.status_code == 422
    assert positive_infinity_plus_lower.status_code == 422
    assert positive_infinity_spaced.status_code == 422
    assert positive_infinity_lower_spaced.status_code == 422
    assert positive_infinity_plus_spaced.status_code == 422
    assert positive_infinity_plus_lower_spaced.status_code == 422
    assert negative_infinity.status_code == 422
    assert negative_infinity_lower.status_code == 422
    assert negative_infinity_spaced.status_code == 422
    assert negative_infinity_lower_spaced.status_code == 422
    assert overflow_positive.status_code == 422
    assert overflow_positive_plus.status_code == 422
    assert overflow_positive_spaced.status_code == 422
    assert overflow_positive_plus_spaced.status_code == 422
    assert overflow_negative.status_code == 422
    assert overflow_negative_spaced.status_code == 422


def test_structure_backtest_endpoint_rejects_out_of_range_execution_params(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)

    invalid_fee = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&fee_bps=-0.1")
    invalid_slippage = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&slippage_bps=1000.1")
    invalid_position = client.get("/api/backtests/structure?symbol=sh600000&timeframe=D&position_pct=100.1")

    assert invalid_fee.status_code == 422
    assert invalid_slippage.status_code == 422
    assert invalid_position.status_code == 422


def test_wave_threshold_query_rejects_out_of_range_values(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)

    endpoints = [
        "/api/analysis/wave?symbol=sh600000&timeframe=D",
        "/api/chart?symbol=sh600000&timeframe=D",
        "/api/backtests/structure?symbol=sh600000&timeframe=D",
    ]
    for endpoint in endpoints:
        too_small = client.get(f"{endpoint}&threshold_pct=0.09")
        too_large = client.get(f"{endpoint}&threshold_pct=50.1")

        assert too_small.status_code == 422
        assert too_large.status_code == 422


def test_analysis_chart_and_backtest_reject_out_of_range_limits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)

    bars_too_small = client.get("/api/bars?symbol=sh600000&timeframe=D&limit=0")
    chart_too_small = client.get("/api/chart?symbol=sh600000&timeframe=D&limit=0")
    assert bars_too_small.status_code == 422
    assert chart_too_small.status_code == 422

    endpoints = [
        "/api/bars?symbol=sh600000&timeframe=D",
        "/api/chart?symbol=sh600000&timeframe=D",
        "/api/analysis/chan?symbol=sh600000&timeframe=D",
        "/api/analysis/wave?symbol=sh600000&timeframe=D",
        "/api/backtests/structure?symbol=sh600000&timeframe=D",
    ]
    for endpoint in endpoints:
        too_large = client.get(f"{endpoint}&limit=2001")
        assert too_large.status_code == 422

    analysis_and_backtest_endpoints = [
        "/api/analysis/chan?symbol=sh600000&timeframe=D",
        "/api/analysis/wave?symbol=sh600000&timeframe=D",
        "/api/backtests/structure?symbol=sh600000&timeframe=D",
    ]
    for endpoint in analysis_and_backtest_endpoints:
        too_small = client.get(f"{endpoint}&limit=19")
        assert too_small.status_code == 422


def test_analysis_chart_and_backtest_reject_invalid_date_queries(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)

    endpoints = [
        "/api/bars?symbol=sh600000&timeframe=D",
        "/api/chart?symbol=sh600000&timeframe=D",
        "/api/analysis/chan?symbol=sh600000&timeframe=D",
        "/api/analysis/wave?symbol=sh600000&timeframe=D",
        "/api/backtests/structure?symbol=sh600000&timeframe=D",
    ]
    for endpoint in endpoints:
        invalid_start = client.get(f"{endpoint}&start_date=not-a-date")
        invalid_end = client.get(f"{endpoint}&end_date=2026-02-30")
        invalid_before = client.get(f"{endpoint}&before=not-a-date")
        invalid_before_date = client.get(f"{endpoint}&before=2026-02-30")

        assert invalid_start.status_code == 400
        assert invalid_end.status_code == 400
        assert invalid_before.status_code == 400
        assert invalid_before_date.status_code == 400
        assert "日期格式无效" in invalid_start.json()["detail"]
        assert "日期格式无效" in invalid_end.json()["detail"]
        assert "before 格式无效" in invalid_before.json()["detail"]
        assert "before 格式无效" in invalid_before_date.json()["detail"]


def test_endpoints_reject_empty_symbol(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    endpoints = [
        "/api/bars?symbol=%20%20%20&timeframe=D",
        "/api/chart?symbol=%20%20%20&timeframe=D",
        "/api/analysis/chan?symbol=%20%20%20&timeframe=D",
        "/api/analysis/wave?symbol=%20%20%20&timeframe=D",
        "/api/backtests/structure?symbol=%20%20%20&timeframe=D",
        "/api/annotations?symbol=%20%20%20&timeframe=D",
        "/api/review-notes?symbol=%20%20%20&timeframe=D",
    ]
    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == 400
        assert response.json()["detail"] == "symbol 不能为空。"


def test_annotation_and_review_note_reject_empty_symbol(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    annotation = client.post(
        "/api/annotations",
        json={
            "symbol": " ",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "invalid"},
        },
    )
    assert annotation.status_code == 400
    assert annotation.json()["detail"] == "symbol 不能为空。"

    review_note = client.post(
        "/api/review-notes",
        json={
            "symbol": " ",
            "timeframe": "D",
            "title": "invalid",
            "content": "invalid",
            "tags": [],
            "payload": {},
        },
    )
    assert review_note.status_code == 400
    assert review_note.json()["detail"] == "symbol 不能为空。"


def test_annotation_rejects_empty_overlay_type(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "   ",
            "payload": {"note": "invalid"},
        },
    )
    assert created.status_code == 400
    assert created.json()["detail"] == "overlay_type 不能为空。"


def test_update_annotation_rejects_empty_overlay_type(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "keep"},
        },
    )
    assert created.status_code == 200

    updated = client.patch(
        f"/api/annotations/{created.json()['id']}",
        json={"overlay_type": " "},
    )
    assert updated.status_code == 400
    assert updated.json()["detail"] == "overlay_type 不能为空。"


def test_endpoints_reject_unsupported_timeframe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    endpoints = [
        "/api/bars?symbol=sh600000&timeframe=2m",
        "/api/chart?symbol=sh600000&timeframe=2m",
        "/api/analysis/chan?symbol=sh600000&timeframe=2m",
        "/api/analysis/wave?symbol=sh600000&timeframe=2m",
        "/api/backtests/structure?symbol=sh600000&timeframe=2m",
        "/api/annotations?symbol=sh600000&timeframe=2m",
        "/api/review-notes?symbol=sh600000&timeframe=2m",
    ]
    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == 400
        assert "timeframe 不支持" in response.json()["detail"]


def test_create_annotation_rejects_unsupported_timeframe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    response = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "2m",
            "overlay_type": "note",
            "payload": {"note": "invalid timeframe"},
        },
    )
    assert response.status_code == 400
    assert "timeframe 不支持" in response.json()["detail"]


def test_create_review_note_rejects_unsupported_timeframe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    response = client.post(
        "/api/review-notes",
        json={
            "symbol": "sh600000",
            "timeframe": "2m",
            "title": "invalid timeframe",
            "content": "invalid timeframe",
            "tags": [],
            "payload": {},
        },
    )
    assert response.status_code == 400
    assert "timeframe 不支持" in response.json()["detail"]


def test_create_annotation_normalizes_lowercase_timeframe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "5m",
            "overlay_type": "note",
            "payload": {"note": "normalized"},
        },
    )
    assert created.status_code == 200
    assert created.json()["timeframe"] == "5M"

    listed = client.get("/api/annotations?symbol=sh600000&timeframe=5m")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["timeframe"] == "5M"


def test_create_annotation_normalizes_symbol(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post(
        "/api/annotations",
        json={
            "symbol": " SH600000 ",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "normalized symbol"},
        },
    )
    assert created.status_code == 200
    assert created.json()["symbol"] == "sh600000"

    listed = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["symbol"] == "sh600000"


def test_create_annotation_normalizes_overlay_type(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": " note ",
            "payload": {"note": "normalized overlay type"},
        },
    )
    assert created.status_code == 200
    assert created.json()["overlay_type"] == "note"

    listed = client.get("/api/annotations?symbol=sh600000&timeframe=D")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["overlay_type"] == "note"


def test_update_annotation_normalizes_overlay_type(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "before update"},
        },
    )
    assert created.status_code == 200

    updated = client.patch(
        f"/api/annotations/{created.json()['id']}",
        json={"overlay_type": " review_note "},
    )
    assert updated.status_code == 200
    assert updated.json()["overlay_type"] == "review_note"

    listed_notes = client.get("/api/review-notes?symbol=sh600000&timeframe=D")
    assert listed_notes.status_code == 200
    assert len(listed_notes.json()) == 1
    assert listed_notes.json()[0]["id"] == created.json()["id"]


def test_create_annotation_maps_storage_value_error_to_http_400(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    def raising_create_annotation(conn, request):  # pragma: no cover - exercised via API
        raise ValueError("标注 payload 非法。")

    monkeypatch.setattr("app.main.create_annotation", raising_create_annotation)

    client = TestClient(app)
    response = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "invalid"},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "标注 payload 非法。"


def test_update_annotation_maps_storage_value_error_to_http_400(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "before update"},
        },
    )
    assert created.status_code == 200

    def raising_update_annotation(conn, annotation_id, request):  # pragma: no cover - exercised via API
        raise ValueError("标注更新参数非法。")

    monkeypatch.setattr("app.main.update_annotation", raising_update_annotation)

    updated = client.patch(
        f"/api/annotations/{created.json()['id']}",
        json={"overlay_type": "review_note"},
    )
    assert updated.status_code == 400
    assert updated.json()["detail"] == "标注更新参数非法。"


def test_create_review_note_maps_storage_value_error_to_http_400(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    def raising_save_review_note(conn, request):  # pragma: no cover - exercised via API
        raise ValueError("复盘笔记 payload 非法。")

    monkeypatch.setattr("app.main.save_review_note", raising_save_review_note)

    client = TestClient(app)
    response = client.post(
        "/api/review-notes",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "title": "invalid",
            "content": "invalid",
            "tags": [],
            "payload": {},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "复盘笔记 payload 非法。"


def test_user_backup_import_maps_storage_value_error_to_http_400(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    def raising_import_user_backup(conn, payload):  # pragma: no cover - exercised via API
        raise ValueError("备份文件字段非法。")

    monkeypatch.setattr("app.main.import_user_backup", raising_import_user_backup)

    client = TestClient(app)
    response = client.post(
        "/api/backups/user",
        json={
            "schema_version": 1,
            "config": {},
            "annotations": [],
            "rule_profiles": [],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "备份文件字段非法。"


def test_analysis_scheme_import_maps_storage_value_error_to_http_400(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    def raising_import_analysis_scheme(conn, payload):  # pragma: no cover - exercised via API
        raise ValueError("分析方案字段非法。")

    monkeypatch.setattr("app.main.import_analysis_scheme", raising_import_analysis_scheme)

    client = TestClient(app)
    response = client.post(
        "/api/schemes/analysis",
        json={
            "schema_version": 1,
            "name": "test",
            "description": "",
            "workspace": {},
            "rule_profiles": [],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "分析方案字段非法。"


def test_create_review_note_rejects_empty_content(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    response = client.post(
        "/api/review-notes",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "title": "empty content",
            "content": "   ",
            "tags": [],
            "payload": {},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "复盘笔记 content 不能为空。"


def test_create_review_note_normalizes_title_content_and_tags(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post(
        "/api/review-notes",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "title": "   ",
            "content": "  中枢震荡后观察三买  ",
            "tags": ["中枢", " ", "三买", "中枢"],
            "payload": {},
        },
    )
    assert created.status_code == 200
    payload = created.json()["payload"]
    assert payload["title"] == "复盘笔记"
    assert payload["content"] == "中枢震荡后观察三买"
    assert payload["tags"] == ["中枢", "三买"]


def test_create_review_note_normalizes_lowercase_timeframe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post(
        "/api/review-notes",
        json={
            "symbol": "sh600000",
            "timeframe": "w",
            "title": "normalized",
            "content": "normalized",
            "tags": ["test"],
            "payload": {},
        },
    )
    assert created.status_code == 200
    assert created.json()["timeframe"] == "W"

    listed = client.get("/api/review-notes?symbol=sh600000&timeframe=w")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["timeframe"] == "W"


def test_create_review_note_normalizes_symbol(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post(
        "/api/review-notes",
        json={
            "symbol": " SH600000 ",
            "timeframe": "D",
            "title": "normalized symbol",
            "content": "normalized symbol",
            "tags": [],
            "payload": {},
        },
    )
    assert created.status_code == 200
    assert created.json()["symbol"] == "sh600000"

    listed = client.get("/api/review-notes?symbol=sh600000&timeframe=D")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["symbol"] == "sh600000"


def test_read_endpoints_normalize_symbol_query(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_rule_profile_test_bars()

    client = TestClient(app)
    annotation = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600001",
            "timeframe": "D",
            "overlay_type": "note",
            "payload": {"note": "normalize symbol query"},
        },
    )
    assert annotation.status_code == 200

    review_note = client.post(
        "/api/review-notes",
        json={
            "symbol": "sh600001",
            "timeframe": "D",
            "title": "normalize",
            "content": "normalize",
            "tags": [],
            "payload": {},
        },
    )
    assert review_note.status_code == 200

    bars = client.get("/api/bars?symbol=%20SH600001%20&timeframe=D&limit=20")
    chart = client.get("/api/chart?symbol=%20SH600001%20&timeframe=D&limit=20")
    chan = client.get("/api/analysis/chan?symbol=%20SH600001%20&timeframe=D&limit=20")
    wave = client.get("/api/analysis/wave?symbol=%20SH600001%20&timeframe=D&limit=20")
    backtest = client.get("/api/backtests/structure?symbol=%20SH600001%20&timeframe=D&limit=20")
    annotations = client.get("/api/annotations?symbol=%20SH600001%20&timeframe=D")
    review_notes = client.get("/api/review-notes?symbol=%20SH600001%20&timeframe=D")

    assert bars.status_code == 200
    assert chart.status_code == 200
    assert chan.status_code == 200
    assert wave.status_code == 200
    assert backtest.status_code == 200
    assert annotations.status_code == 200
    assert review_notes.status_code == 200

    assert bars.json()
    assert bars.json()[0]["symbol"] == "sh600001"
    chart_payload = chart.json()
    assert chart_payload["bars"]
    assert chart_payload["bars"][0]["symbol"] == "sh600001"
    assert chart_payload["chan"]["symbol"] == "sh600001"
    assert chart_payload["wave"]["symbol"] == "sh600001"
    assert chan.json()["symbol"] == "sh600001"
    assert wave.json()["symbol"] == "sh600001"
    assert backtest.json()["symbol"] == "sh600001"

    annotation_items = annotations.json()
    assert len(annotation_items) == 2
    assert all(item["symbol"] == "sh600001" for item in annotation_items)
    assert {item["overlay_type"] for item in annotation_items} == {"note", "review_note"}
    assert len(review_notes.json()) == 1
    assert review_notes.json()[0]["symbol"] == "sh600001"


def test_structure_backtest_endpoint_returns_open_position_when_limit_exit_blocked(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    _insert_limit_backtest_test_bars()

    client = TestClient(app)
    manual_chan = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600002",
            "timeframe": "D",
            "overlay_type": "chan",
            "payload": {
                "active": True,
                "chan_algorithm": "chan-fractal",
                "chan_version": "0.5.0",
                "fractals": [
                    {"index": 0, "trade_date": "2026-07-01", "price": 9.0, "kind": "bottom"},
                    {"index": 2, "trade_date": "2026-07-03", "price": 11.0, "kind": "top"},
                ],
            },
        },
    )
    assert manual_chan.status_code == 200

    result = client.get(
        "/api/backtests/structure?symbol=sh600002&timeframe=D&apply_limit_constraints=true"
    )

    assert result.status_code == 200
    payload = result.json()
    assert payload["structure_source"] == "manual"
    assert payload["manual_annotation_id"] == manual_chan.json()["id"]
    assert payload["summary"]["total_trades"] == 0
    assert payload["params"]["apply_limit_constraints"] is True
    assert payload["params"]["skipped_limit_down_exits"] == 2
    assert payload["params"]["open_position_count"] == 1
    assert payload["params"]["open_position"] == {
        "entry_index": 1,
        "entry_trade_date": "2026-07-02",
        "entry_price": 10.5,
        "entry_signal": "bottom_fractal",
        "latest_index": 4,
        "latest_trade_date": "2026-07-05",
        "latest_close": 8.1,
        "holding_bars": 3,
        "reason": "limit_down_exit_blocked",
    }


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
    assert "minute_files_seen" in job
    assert "minute_files_imported" in job
    assert "minute_bars_imported" in job
    assert job["source_path_exists"] is True

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

    with connect() as conn:
        persisted = conn.execute(
            """
            SELECT status, source_path, files_seen, files_imported, bars_imported, minute_files_seen, minute_files_imported
            FROM import_jobs
            WHERE id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            [job["id"]],
        ).fetchone()
    assert persisted is not None
    assert persisted[0] == "succeeded"
    assert persisted[1] == str(source)
    assert persisted[2] == 1
    assert persisted[3] == 1
    assert persisted[4] == 6
    assert persisted[5] == 1
    assert persisted[6] == 1


def test_list_import_jobs_returns_persisted_jobs_with_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    older_source = tmp_path / "missing-source"
    newer_source = tmp_path / "existing-source"
    newer_source.mkdir(parents=True)

    with connect() as conn:
        save_import_job(
            conn,
            ImportJob(
                id="job-older",
                status="failed",
                source_path=str(older_source),
                files_seen=2,
                files_imported=1,
                bars_imported=100,
                minute_files_seen=1,
                minute_files_imported=0,
                minute_bars_imported=0,
                symbols_imported=1,
                errors=["older failed"],
                message="旧任务失败",
            ),
        )
        save_import_job(
            conn,
            ImportJob(
                id="job-newer",
                status="succeeded",
                source_path=str(newer_source),
                files_seen=3,
                files_imported=3,
                bars_imported=300,
                minute_files_seen=2,
                minute_files_imported=2,
                minute_bars_imported=60,
                symbols_imported=2,
                errors=[],
                message="新任务完成",
            ),
        )

    client = TestClient(app)
    listed_one = client.get("/api/imports/jobs?limit=1")
    assert listed_one.status_code == 200
    listed_one_payload = listed_one.json()
    assert len(listed_one_payload) == 1
    assert listed_one_payload[0]["id"] == "job-newer"
    assert listed_one_payload[0]["status"] == "succeeded"
    assert listed_one_payload[0]["minute_files_seen"] == 2
    assert listed_one_payload[0]["minute_files_imported"] == 2
    assert listed_one_payload[0]["minute_bars_imported"] == 60
    assert listed_one_payload[0]["source_path_exists"] is True

    listed_all = client.get("/api/imports/jobs?limit=10")
    assert listed_all.status_code == 200
    listed_all_payload = listed_all.json()
    assert [item["id"] for item in listed_all_payload][:2] == ["job-newer", "job-older"]
    older_payload = next(item for item in listed_all_payload if item["id"] == "job-older")
    assert older_payload["source_path_exists"] is False

    broken_only = client.get("/api/imports/jobs?limit=10&source_path_exists=false")
    assert broken_only.status_code == 200
    broken_only_payload = broken_only.json()
    assert [item["id"] for item in broken_only_payload] == ["job-older"]
    assert all(item["source_path_exists"] is False for item in broken_only_payload)


def test_list_import_jobs_source_path_filter_applies_before_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    with connect() as conn:
        existing_one = tmp_path / "existing-1"
        existing_two = tmp_path / "existing-2"
        existing_one.mkdir(parents=True)
        existing_two.mkdir(parents=True)
        save_import_job(
            conn,
            ImportJob(
                id="job-broken-old",
                status="failed",
                source_path=str(tmp_path / "missing-old"),
                files_seen=1,
                files_imported=0,
                bars_imported=0,
                minute_files_seen=0,
                minute_files_imported=0,
                minute_bars_imported=0,
                symbols_imported=0,
                errors=["x"],
                message="old missing",
            ),
        )
        save_import_job(
            conn,
            ImportJob(
                id="job-existing-middle",
                status="succeeded",
                source_path=str(existing_one),
                files_seen=1,
                files_imported=1,
                bars_imported=10,
                minute_files_seen=1,
                minute_files_imported=1,
                minute_bars_imported=10,
                symbols_imported=1,
                errors=[],
                message="ok",
            ),
        )
        save_import_job(
            conn,
            ImportJob(
                id="job-broken-new",
                status="failed",
                source_path=str(tmp_path / "missing-new"),
                files_seen=1,
                files_imported=0,
                bars_imported=0,
                minute_files_seen=0,
                minute_files_imported=0,
                minute_bars_imported=0,
                symbols_imported=0,
                errors=["x"],
                message="new missing",
            ),
        )
        save_import_job(
            conn,
            ImportJob(
                id="job-existing-newest",
                status="running",
                source_path=str(existing_two),
                files_seen=1,
                files_imported=0,
                bars_imported=0,
                minute_files_seen=0,
                minute_files_imported=0,
                minute_bars_imported=0,
                symbols_imported=0,
                errors=[],
                message="running",
            ),
        )

    client = TestClient(app)
    broken_only = client.get("/api/imports/jobs?limit=2&source_path_exists=false")
    assert broken_only.status_code == 200
    payload = broken_only.json()
    assert [item["id"] for item in payload] == ["job-broken-new", "job-broken-old"]
    assert all(item["source_path_exists"] is False for item in payload)


def test_list_import_jobs_supports_status_filter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setattr("app.main._reconcile_inactive_import_jobs", lambda _conn: None)

    with connect() as conn:
        save_import_job(
            conn,
            ImportJob(
                id="job-queued",
                status="queued",
                source_path="/tmp/queued",
                files_seen=0,
                files_imported=0,
                bars_imported=0,
                minute_files_seen=0,
                minute_files_imported=0,
                minute_bars_imported=0,
                symbols_imported=0,
                errors=[],
                message="排队中",
            ),
        )
        save_import_job(
            conn,
            ImportJob(
                id="job-running",
                status="running",
                source_path="/tmp/running",
                files_seen=1,
                files_imported=0,
                bars_imported=0,
                minute_files_seen=1,
                minute_files_imported=0,
                minute_bars_imported=0,
                symbols_imported=0,
                errors=[],
                message="导入中",
            ),
        )
        save_import_job(
            conn,
            ImportJob(
                id="job-failed",
                status="failed",
                source_path="/tmp/failed",
                files_seen=1,
                files_imported=0,
                bars_imported=0,
                minute_files_seen=1,
                minute_files_imported=0,
                minute_bars_imported=0,
                symbols_imported=0,
                errors=["failed"],
                message="导入失败",
            ),
        )
        save_import_job(
            conn,
            ImportJob(
                id="job-succeeded",
                status="succeeded",
                source_path="/tmp/succeeded",
                files_seen=2,
                files_imported=2,
                bars_imported=20,
                minute_files_seen=2,
                minute_files_imported=2,
                minute_bars_imported=10,
                symbols_imported=1,
                errors=[],
                message="导入成功",
            ),
        )

    client = TestClient(app)
    failed_only = client.get("/api/imports/jobs?limit=10&status=failed")
    assert failed_only.status_code == 200
    payload = failed_only.json()
    assert [item["id"] for item in payload] == ["job-failed"]
    assert all(item["status"] == "failed" for item in payload)

    pending_only = client.get("/api/imports/jobs?limit=10&status=pending")
    assert pending_only.status_code == 200
    pending_payload = pending_only.json()
    assert [item["id"] for item in pending_payload] == ["job-running", "job-queued"]
    assert {item["status"] for item in pending_payload} == {"queued", "running"}

    pending_missing_path = client.get("/api/imports/jobs?limit=10&status=pending&source_path_exists=false")
    assert pending_missing_path.status_code == 200
    pending_missing_path_payload = pending_missing_path.json()
    assert [item["id"] for item in pending_missing_path_payload] == ["job-running", "job-queued"]
    assert {item["status"] for item in pending_missing_path_payload} == {"queued", "running"}
    assert all(item["source_path_exists"] is False for item in pending_missing_path_payload)


def test_list_import_jobs_rejects_out_of_range_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    too_small = client.get("/api/imports/jobs?limit=0")
    too_large = client.get("/api/imports/jobs?limit=201")

    assert too_small.status_code == 422
    assert too_large.status_code == 422


def test_list_import_jobs_rejects_invalid_status_filter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    invalid_status = client.get("/api/imports/jobs?status=unknown")
    assert invalid_status.status_code == 422


def test_import_jobs_retains_only_recent_records(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    total_jobs = IMPORT_JOBS_RETENTION + 5
    with connect() as conn:
        for index in range(total_jobs):
            save_import_job(
                conn,
                ImportJob(
                    id=f"job-{index:04d}",
                    status="succeeded",
                    source_path=f"/tmp/job-{index:04d}",
                    files_seen=1,
                    files_imported=1,
                    bars_imported=10,
                    minute_files_seen=1,
                    minute_files_imported=1,
                    minute_bars_imported=5,
                    symbols_imported=1,
                    errors=[],
                    message="ok",
                ),
            )
        retained = conn.execute("SELECT count(*) FROM import_jobs").fetchone()[0]
        oldest = conn.execute("SELECT id FROM import_jobs ORDER BY updated_at ASC, id ASC LIMIT 1").fetchone()[0]
        newest = conn.execute("SELECT id FROM import_jobs ORDER BY updated_at DESC, id DESC LIMIT 1").fetchone()[0]

    assert retained == IMPORT_JOBS_RETENTION
    assert oldest == "job-0005"
    assert newest == f"job-{total_jobs - 1:04d}"


def test_list_import_jobs_marks_stale_pending_jobs_as_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    with connect() as conn:
        save_import_job(
            conn,
            ImportJob(
                id="stale-running-job",
                status="running",
                source_path="/tmp/stale-running-job",
                files_seen=3,
                files_imported=1,
                bars_imported=120,
                minute_files_seen=2,
                minute_files_imported=1,
                minute_bars_imported=60,
                symbols_imported=1,
                errors=[],
                message="正在导入",
            ),
        )

    client = TestClient(app)
    listed = client.get("/api/imports/jobs?limit=10")
    assert listed.status_code == 200
    listed_item = next((item for item in listed.json() if item["id"] == "stale-running-job"), None)
    assert listed_item is not None
    assert listed_item["status"] == "failed"
    assert "导入任务已中断" in listed_item["message"]
    assert any("导入任务已中断" in item for item in listed_item["errors"])

    detail = client.get("/api/imports/jobs/stale-running-job")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["status"] == "failed"
    assert detail_payload["source_path_exists"] is False
    assert "导入任务已中断" in detail_payload["message"]
    assert any("导入任务已中断" in item for item in detail_payload["errors"])


def test_get_import_job_returns_source_path_exists_for_existing_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    source_dir = tmp_path / "existing-source"
    source_dir.mkdir(parents=True)
    with connect() as conn:
        save_import_job(
            conn,
            ImportJob(
                id="existing-path-job",
                status="succeeded",
                source_path=str(source_dir),
                files_seen=1,
                files_imported=1,
                bars_imported=10,
                minute_files_seen=1,
                minute_files_imported=1,
                minute_bars_imported=5,
                symbols_imported=1,
                errors=[],
                message="完成",
            ),
        )

    client = TestClient(app)
    detail = client.get("/api/imports/jobs/existing-path-job")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["id"] == "existing-path-job"
    assert payload["source_path_exists"] is True


def test_import_job_chart_manual_chan_backtest_limit_pct_flow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"path": str(source), "markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["source_path"] == str(source)
    assert finished["bars_imported"] == 6

    chart = client.get("/api/chart?symbol=sh600000&timeframe=D&limit=20")
    assert chart.status_code == 200
    chart_payload = chart.json()
    assert len(chart_payload["bars"]) == 6

    manual_chan = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "chan",
            "payload": {
                "active": True,
                "chan_algorithm": "chan-fractal",
                "chan_version": "0.5.0",
                "fractals": [
                    {"index": 1, "trade_date": "2026-05-18", "price": 8.9, "kind": "bottom"},
                    {"index": 3, "trade_date": "2026-05-20", "price": 10.1, "kind": "top"},
                ],
            },
        },
    )
    assert manual_chan.status_code == 200

    backtest = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&apply_limit_constraints=true&limit_pct=20"
    )
    assert backtest.status_code == 200
    backtest_payload = backtest.json()
    assert backtest_payload["structure_source"] == "manual"
    assert backtest_payload["manual_annotation_id"] == manual_chan.json()["id"]
    assert backtest_payload["params"]["source_algorithm"] == "manual-chan"
    assert backtest_payload["params"]["apply_limit_constraints"] is True
    assert backtest_payload["params"]["limit_pct"] == 20
    assert backtest_payload["params"]["limit_rule"] == "prev_close_20pct"


def test_import_job_chart_manual_wave_backtest_limit_pct_flow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"path": str(source), "markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["source_path"] == str(source)
    assert finished["bars_imported"] == 6

    chart = client.get("/api/chart?symbol=sh600000&timeframe=D&limit=20&threshold_pct=8")
    assert chart.status_code == 200
    chart_payload = chart.json()
    assert len(chart_payload["bars"]) == 6

    manual_wave = client.post(
        "/api/annotations",
        json={
            "symbol": "sh600000",
            "timeframe": "D",
            "overlay_type": "wave",
            "payload": {
                "active": True,
                "wave_algorithm": "wave-zigzag",
                "wave_version": "0.1.0",
                "threshold_pct": 8,
                "pivots": [
                    {"index": 0, "trade_date": "2026-05-11", "price": 8.4, "kind": "start", "wave_no": 1},
                    {"index": 1, "trade_date": "2026-05-18", "price": 8.9, "kind": "bottom", "wave_no": 2},
                    {"index": 3, "trade_date": "2026-05-20", "price": 10.1, "kind": "top", "wave_no": 3},
                ],
            },
        },
    )
    assert manual_wave.status_code == 200

    backtest = client.get(
        "/api/backtests/structure?symbol=sh600000&timeframe=D&strategy=wave_zigzag_reversal&threshold_pct=8&apply_limit_constraints=true&limit_pct=20"
    )
    assert backtest.status_code == 200
    backtest_payload = backtest.json()
    assert backtest_payload["strategy"] == "wave_zigzag_reversal"
    assert backtest_payload["structure_source"] == "manual"
    assert backtest_payload["manual_annotation_id"] == manual_wave.json()["id"]
    assert backtest_payload["params"]["source_algorithm"] == "manual-wave"
    assert backtest_payload["params"]["wave_threshold_pct"] == 8
    assert backtest_payload["params"]["apply_limit_constraints"] is True
    assert backtest_payload["params"]["limit_pct"] == 20
    assert backtest_payload["params"]["limit_rule"] == "prev_close_20pct"


def test_import_daily_reports_zero_minute_file_counts_when_source_has_no_minute_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_day_only_fixture(tmp_path)

    client = TestClient(app)
    imported = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})

    assert imported.status_code == 200
    payload = imported.json()
    assert payload["files_seen"] == 1
    assert payload["files_imported"] == 1
    assert payload["bars_imported"] == 6
    assert payload["minute_files_seen"] == 0
    assert payload["minute_files_imported"] == 0
    assert payload["minute_bars_imported"] == 0


def test_import_job_reports_zero_minute_file_counts_when_source_has_no_minute_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_day_only_fixture(tmp_path)

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"path": str(source), "markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["files_seen"] == 1
    assert finished["files_imported"] == 1
    assert finished["bars_imported"] == 6
    assert finished["minute_files_seen"] == 0
    assert finished["minute_files_imported"] == 0
    assert finished["minute_bars_imported"] == 0


def test_import_daily_rejects_invalid_markets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"path": str(source), "markets": ["xx"]})
    assert response.status_code == 400
    assert response.json()["detail"] == "markets 参数不支持：'xx'"


def test_save_source_rejects_blank_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    response = client.post("/api/sources", json={"path": "   "})
    assert response.status_code == 400
    assert response.json()["detail"] == "数据源路径不能为空。"


def test_save_source_rejects_invalid_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    response = client.post("/api/sources", json={"path": "bad\0path"})
    assert response.status_code == 400
    assert response.json()["detail"] == "数据源路径无效。"


def test_save_source_normalizes_explicit_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    request_path = f"  {source.parent / '..' / 'tdx' / source.name}  "

    client = TestClient(app)
    response = client.post("/api/sources", json={"path": request_path})

    assert response.status_code == 200
    payload = response.json()
    normalized_path = str(Path(request_path.strip()).expanduser().resolve())
    assert payload["path"] == normalized_path
    assert payload["valid"] is True
    assert payload["health"]["path"] == normalized_path
    assert config.load_config() == {"source_path": normalized_path}


def test_import_daily_rejects_blank_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"path": "   ", "markets": ["sh"]})
    assert response.status_code == 400
    assert response.json()["detail"] == "数据源路径不能为空。"


def test_import_daily_rejects_invalid_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"path": "bad\0path", "markets": ["sh"]})
    assert response.status_code == 400
    assert response.json()["detail"] == "数据源路径无效。"


def test_import_daily_rejects_explicit_path_with_no_daily_files_even_if_detected_available(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    detected_source = _create_tdx_fixture(tmp_path)
    detected_health = DataSourceCandidate(
        path=str(detected_source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [detected_health])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"path": str(stale_source), "markets": ["sh"]})
    assert response.status_code == 400
    assert response.json()["detail"] == "数据源无效：没有找到可导入的日线文件。"


def test_import_daily_rejects_when_no_configured_or_detected_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setattr("app.main.detect_sources", lambda: [])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})
    assert response.status_code == 400
    assert response.json()["detail"] == "没有配置数据源，也没有自动探测到通达信数据。"


def test_import_daily_rejects_when_detected_candidates_have_blank_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    blank_path_candidate = DataSourceCandidate(
        path="   ",
        exists=True,
        valid=True,
        label="blank-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [blank_path_candidate])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 400
    assert response.json()["detail"] == "没有配置数据源，也没有自动探测到通达信数据。"


def test_import_daily_rejects_when_detected_candidates_have_exists_false(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    missing_candidate = DataSourceCandidate(
        path=str(tmp_path / "missing-vipdoc"),
        exists=False,
        valid=True,
        label="missing-but-valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [missing_candidate])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 400
    assert response.json()["detail"] == "没有配置数据源，也没有自动探测到通达信数据。"


def test_import_daily_uses_normalized_detected_source_when_path_omitted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    detected_source = source.parent / ".." / "tdx" / source.name
    detected_health = DataSourceCandidate(
        path=str(detected_source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [detected_health])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(detected_source.resolve())
    assert payload["files_seen"] == 1
    assert payload["bars_imported"] == 6


def test_import_daily_normalizes_explicit_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    request_path = f"  {source.parent / '..' / 'tdx' / source.name}  "

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"path": request_path, "markets": ["sh"]})

    assert response.status_code == 200
    payload = response.json()
    normalized_path = str(Path(request_path.strip()).expanduser().resolve())
    assert payload["source_path"] == normalized_path
    assert payload["files_seen"] == 1
    assert payload["bars_imported"] == 6


def test_import_daily_skips_blank_detected_path_candidate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    blank_path_candidate = DataSourceCandidate(
        path="   ",
        exists=True,
        valid=True,
        label="blank-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    valid_candidate = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [blank_path_candidate, valid_candidate])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(source.resolve())
    assert payload["files_seen"] == 1
    assert payload["bars_imported"] == 6


def test_import_daily_skips_detected_candidate_with_exists_false(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    invalid_candidate = DataSourceCandidate(
        path=str(tmp_path / "missing-vipdoc"),
        exists=False,
        valid=True,
        label="missing-but-valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    valid_candidate = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [invalid_candidate, valid_candidate])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(source.resolve())
    assert payload["files_seen"] == 1
    assert payload["bars_imported"] == 6


def test_import_daily_skips_detected_candidate_with_invalid_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    invalid_path_candidate = DataSourceCandidate(
        path="bad\0path",
        exists=True,
        valid=True,
        label="invalid-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    valid_candidate = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [invalid_path_candidate, valid_candidate])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(source.resolve())
    assert payload["files_seen"] == 1
    assert payload["bars_imported"] == 6


def test_import_daily_skips_stale_detected_candidate_with_no_daily_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_path = tmp_path / "stale-vipdoc"
    stale_path.mkdir(parents=True)
    stale_candidate = DataSourceCandidate(
        path=str(stale_path),
        exists=True,
        valid=True,
        label="stale-detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    source = _create_tdx_fixture(tmp_path)
    valid_candidate = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [stale_candidate, valid_candidate])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(source.resolve())
    assert payload["files_seen"] == 1
    assert payload["bars_imported"] == 6


def test_import_daily_rejects_when_detected_candidates_are_stale(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_path = tmp_path / "stale-vipdoc"
    stale_path.mkdir(parents=True)
    stale_candidate = DataSourceCandidate(
        path=str(stale_path),
        exists=True,
        valid=True,
        label="stale-detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [stale_candidate])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 400
    assert response.json()["detail"] == "没有配置数据源，也没有自动探测到通达信数据。"


def test_import_daily_rejects_when_detected_candidates_have_invalid_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    invalid_path_candidate = DataSourceCandidate(
        path="bad\0path",
        exists=True,
        valid=True,
        label="invalid-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [invalid_path_candidate])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 400
    assert response.json()["detail"] == "没有配置数据源，也没有自动探测到通达信数据。"


def test_import_job_rejects_blank_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"path": "   ", "markets": ["sh"]})
    assert created.status_code == 400
    assert created.json()["detail"] == "数据源路径不能为空。"


def test_import_job_uses_normalized_detected_source_when_path_omitted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    detected_source = source.parent / ".." / "tdx" / source.name
    detected_health = DataSourceCandidate(
        path=str(detected_source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [detected_health])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["source_path"] == str(detected_source.resolve())
    assert finished["files_seen"] == 1
    assert finished["bars_imported"] == 6


def test_import_job_normalizes_explicit_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    request_path = f"  {source.parent / '..' / 'tdx' / source.name}  "

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"path": request_path, "markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    normalized_path = str(Path(request_path.strip()).expanduser().resolve())
    assert finished["source_path"] == normalized_path
    assert finished["files_seen"] == 1
    assert finished["bars_imported"] == 6


def test_import_job_skips_blank_detected_path_candidate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    blank_path_candidate = DataSourceCandidate(
        path="   ",
        exists=True,
        valid=True,
        label="blank-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    valid_candidate = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [blank_path_candidate, valid_candidate])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["source_path"] == str(source.resolve())
    assert finished["files_seen"] == 1
    assert finished["bars_imported"] == 6


def test_import_job_skips_detected_candidate_with_exists_false(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    invalid_candidate = DataSourceCandidate(
        path=str(tmp_path / "missing-vipdoc"),
        exists=False,
        valid=True,
        label="missing-but-valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    valid_candidate = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [invalid_candidate, valid_candidate])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["source_path"] == str(source.resolve())
    assert finished["files_seen"] == 1
    assert finished["bars_imported"] == 6


def test_import_job_skips_detected_candidate_with_invalid_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    invalid_path_candidate = DataSourceCandidate(
        path="bad\0path",
        exists=True,
        valid=True,
        label="invalid-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    valid_candidate = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [invalid_path_candidate, valid_candidate])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["source_path"] == str(source.resolve())
    assert finished["files_seen"] == 1
    assert finished["bars_imported"] == 6


def test_import_job_skips_stale_detected_candidate_with_no_daily_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_path = tmp_path / "stale-vipdoc"
    stale_path.mkdir(parents=True)
    stale_candidate = DataSourceCandidate(
        path=str(stale_path),
        exists=True,
        valid=True,
        label="stale-detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    source = _create_tdx_fixture(tmp_path)
    valid_candidate = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [stale_candidate, valid_candidate])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["source_path"] == str(source.resolve())
    assert finished["files_seen"] == 1
    assert finished["bars_imported"] == 6


def test_import_job_rejects_when_detected_candidates_are_stale(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_path = tmp_path / "stale-vipdoc"
    stale_path.mkdir(parents=True)
    stale_candidate = DataSourceCandidate(
        path=str(stale_path),
        exists=True,
        valid=True,
        label="stale-detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [stale_candidate])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})

    assert created.status_code == 400
    assert created.json()["detail"] == "没有配置数据源，也没有自动探测到通达信数据。"


def test_import_job_rejects_when_detected_candidates_have_invalid_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    invalid_path_candidate = DataSourceCandidate(
        path="bad\0path",
        exists=True,
        valid=True,
        label="invalid-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [invalid_path_candidate])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})

    assert created.status_code == 400
    assert created.json()["detail"] == "没有配置数据源，也没有自动探测到通达信数据。"


def test_import_job_rejects_when_no_configured_or_detected_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setattr("app.main.detect_sources", lambda: [])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})
    assert created.status_code == 400
    assert created.json()["detail"] == "没有配置数据源，也没有自动探测到通达信数据。"


def test_import_job_rejects_when_detected_candidates_have_blank_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    blank_path_candidate = DataSourceCandidate(
        path="   ",
        exists=True,
        valid=True,
        label="blank-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [blank_path_candidate])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})

    assert created.status_code == 400
    assert created.json()["detail"] == "没有配置数据源，也没有自动探测到通达信数据。"


def test_import_job_rejects_when_detected_candidates_have_exists_false(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    missing_candidate = DataSourceCandidate(
        path=str(tmp_path / "missing-vipdoc"),
        exists=False,
        valid=True,
        label="missing-but-valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [missing_candidate])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})

    assert created.status_code == 400
    assert created.json()["detail"] == "没有配置数据源，也没有自动探测到通达信数据。"


def test_import_daily_uses_trimmed_configured_source_when_path_omitted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    config.save_config({"source_path": f"  {source}  "})

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(source)
    assert payload["files_seen"] == 1
    assert payload["bars_imported"] == 6


def test_import_daily_normalizes_relative_configured_source_when_path_omitted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    relative_config_path = source.parent / ".." / "tdx" / source.name
    config.save_config({"source_path": f"  {relative_config_path}  "})

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(relative_config_path.resolve())
    assert payload["files_seen"] == 1
    assert payload["bars_imported"] == 6


def test_import_daily_uses_detected_source_when_configured_source_invalid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    config.save_config({"source_path": "bad\0path"})
    detected_health = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [detected_health])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(source.resolve())
    assert payload["files_seen"] == 1
    assert payload["bars_imported"] == 6


def test_import_daily_uses_valid_detected_when_configured_source_invalid_and_first_detected_is_stale(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "bad\0path"})
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    stale_detected = DataSourceCandidate(
        path=str(stale_source),
        exists=True,
        valid=True,
        label="stale-detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    source = _create_tdx_fixture(tmp_path)
    detected_health = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [stale_detected, detected_health])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(source.resolve())
    assert payload["files_seen"] == 1
    assert payload["bars_imported"] == 6


def test_import_daily_uses_valid_detected_when_configured_source_invalid_and_detected_candidates_mixed_invalid(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "bad\0path"})
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    blank_path_candidate = DataSourceCandidate(
        path="   ",
        exists=True,
        valid=True,
        label="blank-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    missing_candidate = DataSourceCandidate(
        path=str(tmp_path / "missing-vipdoc"),
        exists=False,
        valid=True,
        label="missing-but-valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    stale_candidate = DataSourceCandidate(
        path=str(stale_source),
        exists=True,
        valid=True,
        label="stale-detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    source = _create_tdx_fixture(tmp_path)
    detected_health = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected-valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr(
        "app.main.detect_sources",
        lambda: [blank_path_candidate, missing_candidate, stale_candidate, detected_health],
    )

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(source.resolve())
    assert payload["files_seen"] == 1
    assert payload["bars_imported"] == 6


def test_import_daily_uses_detected_source_when_configured_source_has_no_daily_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    config.save_config({"source_path": str(stale_source)})
    source = _create_tdx_fixture(tmp_path)
    detected_health = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [detected_health])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(source.resolve())
    assert payload["files_seen"] == 1
    assert payload["bars_imported"] == 6


def test_import_daily_rejects_when_configured_source_has_no_daily_files_and_no_detected_source(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    config.save_config({"source_path": str(stale_source)})
    monkeypatch.setattr("app.main.detect_sources", lambda: [])

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"markets": ["sh"]})

    assert response.status_code == 400
    assert response.json()["detail"] == "没有配置数据源，也没有自动探测到通达信数据。"


def test_import_job_uses_trimmed_configured_source_when_path_omitted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    config.save_config({"source_path": f"  {source}  "})

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["source_path"] == str(source)
    assert finished["files_seen"] == 1
    assert finished["bars_imported"] == 6


def test_import_job_normalizes_relative_configured_source_when_path_omitted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    relative_config_path = source.parent / ".." / "tdx" / source.name
    config.save_config({"source_path": f"  {relative_config_path}  "})

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["source_path"] == str(relative_config_path.resolve())
    assert finished["files_seen"] == 1
    assert finished["bars_imported"] == 6


def test_import_job_rejects_invalid_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"path": "bad\0path", "markets": ["sh"]})
    assert created.status_code == 400
    assert created.json()["detail"] == "数据源路径无效。"


def test_import_job_rejects_explicit_path_with_no_daily_files_even_if_detected_available(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    detected_source = _create_tdx_fixture(tmp_path)
    detected_health = DataSourceCandidate(
        path=str(detected_source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [detected_health])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"path": str(stale_source), "markets": ["sh"]})
    assert created.status_code == 400
    assert created.json()["detail"] == "数据源无效：没有找到可导入的日线文件。"


def test_import_job_uses_detected_source_when_configured_source_invalid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)
    config.save_config({"source_path": "bad\0path"})
    detected_health = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [detected_health])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["source_path"] == str(source.resolve())
    assert finished["files_seen"] == 1
    assert finished["bars_imported"] == 6


def test_import_job_uses_valid_detected_when_configured_source_invalid_and_first_detected_is_stale(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "bad\0path"})
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    stale_detected = DataSourceCandidate(
        path=str(stale_source),
        exists=True,
        valid=True,
        label="stale-detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    source = _create_tdx_fixture(tmp_path)
    detected_health = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [stale_detected, detected_health])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["source_path"] == str(source.resolve())
    assert finished["files_seen"] == 1
    assert finished["bars_imported"] == 6


def test_import_job_uses_valid_detected_when_configured_source_invalid_and_detected_candidates_mixed_invalid(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    config.save_config({"source_path": "bad\0path"})
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    blank_path_candidate = DataSourceCandidate(
        path="   ",
        exists=True,
        valid=True,
        label="blank-path",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    missing_candidate = DataSourceCandidate(
        path=str(tmp_path / "missing-vipdoc"),
        exists=False,
        valid=True,
        label="missing-but-valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    stale_candidate = DataSourceCandidate(
        path=str(stale_source),
        exists=True,
        valid=True,
        label="stale-detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    source = _create_tdx_fixture(tmp_path)
    detected_health = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected-valid",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr(
        "app.main.detect_sources",
        lambda: [blank_path_candidate, missing_candidate, stale_candidate, detected_health],
    )

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["source_path"] == str(source.resolve())
    assert finished["files_seen"] == 1
    assert finished["bars_imported"] == 6


def test_import_job_uses_detected_source_when_configured_source_has_no_daily_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    config.save_config({"source_path": str(stale_source)})
    source = _create_tdx_fixture(tmp_path)
    detected_health = DataSourceCandidate(
        path=str(source),
        exists=True,
        valid=True,
        label="detected",
        markets=["sh"],
        daily_files=1,
        minute1_files=0,
        minute5_files=1,
        size_bytes=1,
        latest_modified=None,
    )
    monkeypatch.setattr("app.main.detect_sources", lambda: [detected_health])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})
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
    assert finished["status"] == "succeeded"
    assert finished["source_path"] == str(source.resolve())
    assert finished["files_seen"] == 1
    assert finished["bars_imported"] == 6


def test_import_job_rejects_when_configured_source_has_no_daily_files_and_no_detected_source(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    stale_source = tmp_path / "stale-vipdoc"
    stale_source.mkdir(parents=True)
    config.save_config({"source_path": str(stale_source)})
    monkeypatch.setattr("app.main.detect_sources", lambda: [])

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"markets": ["sh"]})

    assert created.status_code == 400
    assert created.json()["detail"] == "没有配置数据源，也没有自动探测到通达信数据。"


def test_import_daily_normalizes_and_deduplicates_markets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    response = client.post(
        "/api/imports/daily",
        json={"path": str(source), "markets": [" SH ", "sh", " sz "]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["files_seen"] == 1
    assert payload["files_imported"] == 1
    assert payload["bars_imported"] == 6
    assert payload["minute_files_seen"] == 2
    assert payload["minute_files_imported"] == 2
    assert payload["minute_bars_imported"] == 49


def test_import_daily_reimport_reports_processed_counts_without_increasing_cached_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    first = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})
    second = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"]})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["bars_imported"] == 6
    assert second.json()["bars_imported"] == 6
    assert first.json()["minute_bars_imported"] == 48
    assert second.json()["minute_bars_imported"] == 48

    with connect() as conn:
        day_count = conn.execute("SELECT COUNT(*) FROM bars_daily WHERE symbol = 'sh600000'").fetchone()[0]
        minute_count = conn.execute(
            "SELECT COUNT(*) FROM bars_minute WHERE symbol = 'sh600000' AND interval_minutes = 5"
        ).fetchone()[0]

    # 导入统计反映本次处理条数，底层写入按主键去重，重复导入不会增加缓存行数。
    assert day_count == 6
    assert minute_count == 48


def test_import_daily_rejects_non_positive_limit_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    response = client.post("/api/imports/daily", json={"path": str(source), "markets": ["sh"], "limit_files": 0})
    assert response.status_code == 422


def test_import_job_rejects_invalid_markets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"path": str(source), "markets": ["xx"]})
    assert created.status_code == 400
    assert created.json()["detail"] == "markets 参数不支持：'xx'"


def test_import_job_normalizes_and_deduplicates_markets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    created = client.post(
        "/api/imports/jobs",
        json={"path": str(source), "markets": [" SH ", "sh", " sz "]},
    )
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
    assert finished["status"] == "succeeded"
    assert finished["files_seen"] == 1
    assert finished["files_imported"] == 1
    assert finished["bars_imported"] == 6
    assert finished["minute_bars_imported"] == 49


def test_import_job_reimport_reports_processed_counts_without_increasing_cached_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    first_created = client.post("/api/imports/jobs", json={"path": str(source), "markets": ["sh"]})
    assert first_created.status_code == 200

    def wait_job(job_id: str) -> dict:
        finished_payload = None
        for _ in range(50):
            polled = client.get(f"/api/imports/jobs/{job_id}")
            assert polled.status_code == 200
            payload = polled.json()
            if payload["status"] in {"succeeded", "failed"}:
                finished_payload = payload
                break
            time.sleep(0.05)
        assert finished_payload is not None
        return finished_payload

    first_finished = wait_job(first_created.json()["id"])
    second_created = client.post("/api/imports/jobs", json={"path": str(source), "markets": ["sh"]})
    assert second_created.status_code == 200
    second_finished = wait_job(second_created.json()["id"])

    assert first_finished["status"] == "succeeded"
    assert second_finished["status"] == "succeeded"
    assert first_finished["bars_imported"] == 6
    assert second_finished["bars_imported"] == 6
    assert first_finished["minute_bars_imported"] == 48
    assert second_finished["minute_bars_imported"] == 48

    with connect() as conn:
        day_count = conn.execute("SELECT COUNT(*) FROM bars_daily WHERE symbol = 'sh600000'").fetchone()[0]
        minute_count = conn.execute(
            "SELECT COUNT(*) FROM bars_minute WHERE symbol = 'sh600000' AND interval_minutes = 5"
        ).fetchone()[0]

    # jobs 口径与同步导入一致：统计处理条数，缓存写入按主键去重不重复增长。
    assert day_count == 6
    assert minute_count == 48


def test_import_job_rejects_non_positive_limit_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")
    source = _create_tdx_fixture(tmp_path)

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"path": str(source), "markets": ["sh"], "limit_files": 0})
    assert created.status_code == 422


def test_import_job_invalid_path_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.duckdb")

    client = TestClient(app)
    created = client.post("/api/imports/jobs", json={"path": str(tmp_path / "missing")})
    assert created.status_code == 400
    assert created.json()["detail"] == "数据源无效：没有找到可导入的日线文件。"


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
