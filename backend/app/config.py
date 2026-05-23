from __future__ import annotations

import json
from pathlib import Path
from typing import Any


APP_DIR = Path.home() / ".aether_stock_analysis"
CONFIG_PATH = APP_DIR / "config.json"
DB_PATH = APP_DIR / "aether.duckdb"


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    ensure_app_dir()
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_config(config: dict[str, Any]) -> None:
    ensure_app_dir()
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
