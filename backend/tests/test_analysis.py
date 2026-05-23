from __future__ import annotations

from datetime import date, timedelta

from app.analysis import detect_fractals, detect_zigzag_waves
from app.schemas import BarRecord


def test_detect_fractals() -> None:
    bars = [
        _bar(0, 10, 8),
        _bar(1, 12, 9),
        _bar(2, 11, 7),
        _bar(3, 13, 9),
        _bar(4, 10, 8),
    ]

    result = detect_fractals("sh600000", "D", bars)

    assert [(point.index, point.kind) for point in result.fractals] == [
        (1, "top"),
        (2, "bottom"),
        (3, "top"),
    ]


def test_detect_zigzag_waves() -> None:
    bars = [
        _bar(0, 10, 9),
        _bar(1, 11, 10),
        _bar(2, 12, 11),
        _bar(3, 11, 10),
        _bar(4, 10, 9),
        _bar(5, 11, 10),
        _bar(6, 13, 12),
    ]

    result = detect_zigzag_waves("sh600000", "D", bars, threshold_pct=10)

    assert result.algorithm == "wave-zigzag"
    assert len(result.pivots) >= 3
    assert {point.kind for point in result.pivots} >= {"top", "bottom"}


def _bar(offset: int, high: float, low: float) -> BarRecord:
    return BarRecord(
        symbol="sh600000",
        timeframe="D",
        trade_date=(date(2026, 1, 1) + timedelta(days=offset)).isoformat(),
        open=9,
        high=high,
        low=low,
        close=10,
        amount=0,
        volume=0,
    )
