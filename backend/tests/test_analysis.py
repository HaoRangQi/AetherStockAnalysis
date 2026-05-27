from __future__ import annotations

from datetime import date, datetime, timedelta

from app.analysis import (
    build_bi_segments,
    build_line_segments,
    build_zhongshu,
    detect_fractals,
    detect_zigzag_waves,
    normalize_containment,
    run_structure_backtest,
)
from app.schemas import AnalysisPoint, BarRecord, ChanBiSegment, ChanZhongshu, WaveAnalysisResponse, WavePoint
from app.schemas import ChanAnalysisResponse


def test_detect_fractals() -> None:
    bars = [
        _bar(0, 10, 8),
        _bar(1, 12, 9),
        _bar(2, 11, 7),
        _bar(3, 13, 9),
        _bar(4, 10, 8),
    ]

    result = detect_fractals("sh600000", "D", bars)

    assert result.algorithm == "chan-fractal"
    assert result.version == "0.5.0"
    assert result.params == {
        "strict_fractal": False,
        "include_containment": True,
        "window": 3,
        "min_bars_for_bi": 5,
        "min_bis_for_segment": 3,
        "segment_step_bis": 3,
        "min_bis_for_zhongshu": 3,
        "zhongshu_step_bis": 1,
    }
    assert result.generated_at is not None
    assert [(point.index, point.kind) for point in result.fractals] == [
        (1, "top"),
        (2, "bottom"),
        (3, "top"),
    ]
    assert result.bis == []
    assert result.segments == []
    assert result.zhongshu == []


def test_normalize_containment_merges_in_direction_and_keeps_source_anchor() -> None:
    bars = [
        _price_bar(0, 10, 8, 9),
        _price_bar(1, 12, 9, 11),
        _price_bar(2, 11, 10, 10),
        _price_bar(3, 13, 11, 12),
        _price_bar(4, 10, 7, 8),
    ]

    normalized = normalize_containment(bars)

    assert [(item.high, item.low) for item in normalized] == [
        (10, 8),
        (12, 10),
        (13, 11),
        (10, 7),
    ]
    assert normalized[1].high_index == 1
    assert normalized[1].high_trade_date == "2026-01-02"
    assert normalized[1].low_index == 2
    assert normalized[1].low_trade_date == "2026-01-03"


def test_detect_fractals_uses_containment_normalized_bars() -> None:
    bars = [
        _price_bar(0, 10, 8, 9),
        _price_bar(1, 12, 9, 11),
        _price_bar(2, 11, 10, 10),
        _price_bar(3, 13, 11, 12),
        _price_bar(4, 10, 7, 8),
    ]

    result = detect_fractals("sh600000", "D", bars)

    assert [(point.index, point.trade_date, point.price, point.kind) for point in result.fractals] == [
        (3, "2026-01-04", 13, "top"),
    ]


def test_build_bi_segments_uses_alternating_fractals_with_min_interval() -> None:
    fractals = [
        _point(1, 12, "top"),
        _point(3, 14, "top"),
        _point(4, 8, "bottom"),
        _point(8, 7, "bottom"),
        _point(13, 15, "top"),
    ]

    result = build_bi_segments(fractals)

    assert [(item.start_index, item.end_index, item.direction) for item in result] == [
        (3, 8, "down"),
        (8, 13, "up"),
    ]
    assert [(item.start_kind, item.end_kind) for item in result] == [
        ("top", "bottom"),
        ("bottom", "top"),
    ]


def test_build_line_segments_uses_three_bi_windows() -> None:
    bis = build_bi_segments(
        [
            _point(1, 14, "top"),
            _point(6, 8, "bottom"),
            _point(11, 16, "top"),
            _point(16, 9, "bottom"),
            _point(21, 18, "top"),
            _point(26, 10, "bottom"),
        ]
    )

    result = build_line_segments(bis)

    assert [(item.start_bi_index, item.end_bi_index, item.bi_count) for item in result] == [
        (1, 3, 3),
    ]
    assert [(item.start_index, item.end_index, item.direction) for item in result] == [
        (1, 16, "down"),
    ]


def test_build_zhongshu_uses_three_bi_overlap() -> None:
    bis = build_bi_segments(
        [
            _point(1, 14, "top"),
            _point(6, 8, "bottom"),
            _point(11, 16, "top"),
            _point(16, 9, "bottom"),
            _point(21, 18, "top"),
            _point(26, 10, "bottom"),
        ]
    )

    result = build_zhongshu(bis)

    assert [(item.start_bi_index, item.end_bi_index, item.bi_count) for item in result] == [
        (1, 3, 3),
        (2, 4, 3),
        (3, 5, 3),
    ]
    assert [(item.low, item.high, item.mid) for item in result] == [
        (9, 14, 11.5),
        (9, 16, 12.5),
        (10, 16, 13),
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

    result = detect_zigzag_waves("sh600000", "D", bars, threshold_pct=10, min_swing_bars=1)

    assert result.algorithm == "wave-zigzag"
    assert result.version == "0.1.0"
    assert result.params == {"threshold_pct": 10, "min_swing_bars": 1}
    assert result.generated_at is not None
    assert len(result.pivots) >= 3
    assert {point.kind for point in result.pivots} >= {"top", "bottom"}


def test_detect_zigzag_waves_filters_close_pivots_by_min_swing_bars() -> None:
    bars = [
        _bar(0, 10, 9),
        _bar(1, 11, 10),
        _bar(2, 12, 11),
        _bar(3, 11, 10),
        _bar(4, 10, 9),
        _bar(5, 11, 10),
        _bar(6, 13, 12),
    ]

    dense = detect_zigzag_waves("sh600000", "D", bars, threshold_pct=10, min_swing_bars=1)
    filtered = detect_zigzag_waves("sh600000", "D", bars, threshold_pct=10, min_swing_bars=3)

    assert filtered.params == {"threshold_pct": 10, "min_swing_bars": 3}
    assert len(filtered.pivots) < len(dense.pivots)
    assert all(
        current.index - previous.index >= 3
        for previous, current in zip(filtered.pivots, filtered.pivots[1:])
    )


def test_run_structure_backtest_uses_confirmed_fractal_reversal_trades() -> None:
    bars = [
        _price_bar(0, 10, 9, 10),
        _price_bar(1, 12, 10, 11),
        _price_bar(2, 11, 8, 9),
        _price_bar(3, 13, 9, 12),
        _price_bar(4, 10, 7, 8),
        _price_bar(5, 12, 8, 11),
        _price_bar(6, 11, 9, 10),
    ]

    result = run_structure_backtest("sh600000", "D", bars)

    assert result.algorithm == "structure-backtest"
    assert result.version == "0.1.0"
    assert result.strategy == "chan_fractal_reversal"
    assert result.structure_source == "auto"
    assert result.manual_annotation_id is None
    assert result.params["entry_signal"] == "bottom_fractal"
    assert result.params["exit_signal"] == "top_fractal"
    assert result.params["strategy_condition_key"] == "chan_fractal_reversal"
    assert "底分型确认" in result.params["strategy_condition"]
    assert result.params["structure_counts"] == {"fractals": 4, "bis": 0, "segments": 0, "zhongshu": 0}
    assert result.params["signal_count"] == 4
    assert result.params["entry_signal_count"] == 2
    assert result.params["exit_signal_count"] == 2
    assert result.params["fee_bps"] == 0
    assert result.params["slippage_bps"] == 0
    assert result.params["position_pct"] == 100
    assert result.bars_tested == 7
    assert [(trade.entry_index, trade.exit_index, trade.exit_reason) for trade in result.trades] == [
        (3, 4, "top_fractal"),
        (5, 6, "end_of_data"),
    ]
    assert [trade.return_pct for trade in result.trades] == [-33.3333, -9.0909]
    assert result.summary.total_trades == 2
    assert result.summary.winning_trades == 0
    assert result.summary.losing_trades == 2
    assert result.summary.win_rate == 0
    assert result.summary.total_return_pct == -39.3939
    assert [(point.trade_index, point.trade_date, point.equity_return_pct, point.drawdown_pct) for point in result.equity_curve] == [
        (1, "2026-01-05", -33.3333, 33.3333),
        (2, "2026-01-07", -39.3939, 39.3939),
    ]
    assert result.summary.max_drawdown_pct == result.equity_curve[-1].drawdown_pct
    assert result.summary.average_holding_bars == 1
    assert result.summary.min_holding_bars == 1
    assert result.summary.max_holding_bars == 1
    assert result.summary.median_holding_bars == 1


def test_run_structure_backtest_applies_cost_and_position_params() -> None:
    bars = [
        _price_bar(0, 10, 9, 10),
        _price_bar(1, 12, 10, 11),
        _price_bar(2, 11, 8, 9),
        _price_bar(3, 13, 9, 12),
        _price_bar(4, 10, 7, 8),
    ]

    result = run_structure_backtest("sh600000", "D", bars, fee_bps=10, slippage_bps=5, position_pct=50)

    assert result.params["fee_bps"] == 10
    assert result.params["slippage_bps"] == 5
    assert result.params["position_pct"] == 50
    assert result.trades[0].entry_price == 12.006
    assert result.trades[0].exit_price == 7.996
    assert result.trades[0].return_pct == -16.8
    assert result.summary.total_return_pct == -16.8
    assert result.equity_curve[0].equity == 0.832
    assert result.equity_curve[0].equity_return_pct == -16.8
    assert result.summary.min_holding_bars == 1
    assert result.summary.max_holding_bars == 1
    assert result.summary.median_holding_bars == 1


def test_run_structure_backtest_can_skip_limit_blocked_entry() -> None:
    bars = [
        _price_bar(0, 10, 9, 10),
        _price_bar(1, 12, 10, 11),
        _price_bar(2, 11, 9, 10),
        _price_bar(3, 13, 10, 12),
    ]
    manual = ChanAnalysisResponse(
        symbol="sh600000",
        timeframe="D",
        algorithm="manual-chan",
        version="0.5.0",
        params={"source": "limit-entry-test"},
        generated_at=datetime(2026, 1, 1),
        fractals=[_point(0, 9, "bottom"), _point(2, 11, "top")],
        bis=[],
        segments=[],
        zhongshu=[],
    )

    unconstrained = run_structure_backtest("sh600000", "D", bars, analysis=manual)
    constrained = run_structure_backtest("sh600000", "D", bars, analysis=manual, apply_limit_constraints=True)

    assert unconstrained.summary.total_trades == 1
    assert constrained.params["apply_limit_constraints"] is True
    assert constrained.params["limit_pct"] == 10
    assert constrained.params["limit_rule"] == "prev_close_10pct"
    assert constrained.params["skipped_limit_up_entries"] == 1
    assert constrained.params["skipped_limit_down_exits"] == 0
    assert constrained.params["open_position_count"] == 0
    assert constrained.params["open_position"] is None
    assert constrained.trades == []
    assert constrained.summary.total_trades == 0

    twenty_pct_limit = run_structure_backtest(
        "sh600000",
        "D",
        bars,
        analysis=manual,
        apply_limit_constraints=True,
        limit_pct=20,
    )

    assert twenty_pct_limit.params["limit_pct"] == 20
    assert twenty_pct_limit.params["limit_rule"] == "prev_close_20pct"
    assert twenty_pct_limit.params["skipped_limit_up_entries"] == 0
    assert twenty_pct_limit.summary.total_trades == 1

    clamped_low_limit = run_structure_backtest(
        "sh600000",
        "D",
        bars,
        analysis=manual,
        apply_limit_constraints=True,
        limit_pct=-5,
    )
    clamped_high_limit = run_structure_backtest(
        "sh600000",
        "D",
        bars,
        analysis=manual,
        apply_limit_constraints=True,
        limit_pct=50,
    )

    assert clamped_low_limit.params["limit_pct"] == 0.1
    assert clamped_low_limit.params["limit_rule"] == "prev_close_0.1pct"
    assert clamped_high_limit.params["limit_pct"] == 30
    assert clamped_high_limit.params["limit_rule"] == "prev_close_30pct"

    nan_limit = run_structure_backtest(
        "sh600000",
        "D",
        bars,
        analysis=manual,
        apply_limit_constraints=True,
        limit_pct=float("nan"),
    )
    inf_limit = run_structure_backtest(
        "sh600000",
        "D",
        bars,
        analysis=manual,
        apply_limit_constraints=True,
        limit_pct=float("inf"),
    )
    neg_inf_limit = run_structure_backtest(
        "sh600000",
        "D",
        bars,
        analysis=manual,
        apply_limit_constraints=True,
        limit_pct=float("-inf"),
    )

    assert nan_limit.params["limit_pct"] == 10
    assert nan_limit.params["limit_rule"] == "prev_close_10pct"
    assert inf_limit.params["limit_pct"] == 10
    assert inf_limit.params["limit_rule"] == "prev_close_10pct"
    assert neg_inf_limit.params["limit_pct"] == 10
    assert neg_inf_limit.params["limit_rule"] == "prev_close_10pct"


def test_run_structure_backtest_can_skip_limit_blocked_exit() -> None:
    bars = [
        _price_bar(0, 10, 9, 10),
        _price_bar(1, 11, 10, 10.5),
        _price_bar(2, 11, 9, 10),
        _price_bar(3, 10, 8, 9),
        _price_bar(4, 9, 8, 8.1),
    ]
    manual = ChanAnalysisResponse(
        symbol="sh600000",
        timeframe="D",
        algorithm="manual-chan",
        version="0.5.0",
        params={"source": "limit-exit-test"},
        generated_at=datetime(2026, 1, 1),
        fractals=[_point(0, 9, "bottom"), _point(2, 11, "top")],
        bis=[],
        segments=[],
        zhongshu=[],
    )

    result = run_structure_backtest("sh600000", "D", bars, analysis=manual, apply_limit_constraints=True)

    assert result.params["skipped_limit_up_entries"] == 0
    assert result.params["skipped_limit_down_exits"] == 2
    assert result.params["open_position_count"] == 1
    assert result.params["open_position"] == {
        "entry_index": 1,
        "entry_trade_date": "2026-01-02",
        "entry_price": 10.5,
        "entry_signal": "bottom_fractal",
        "latest_index": 4,
        "latest_trade_date": "2026-01-05",
        "latest_close": 8.1,
        "holding_bars": 3,
        "reason": "limit_down_exit_blocked",
    }
    assert result.trades == []
    assert result.summary.total_trades == 0


def test_run_structure_backtest_uses_bi_reversal_strategy() -> None:
    bars = [_price_bar(index, 20, 8, 10 + index) for index in range(14)]
    manual = ChanAnalysisResponse(
        symbol="sh600000",
        timeframe="D",
        algorithm="manual-chan",
        version="0.5.0",
        params={"source": "manual-bi-test"},
        generated_at=datetime(2026, 1, 1),
        fractals=[],
        bis=[
            _bi(1, 1, 5, 16, 9, "down"),
            _bi(2, 5, 10, 9, 17, "up"),
        ],
        segments=[],
        zhongshu=[],
    )

    result = run_structure_backtest("sh600000", "D", bars, strategy="chan_bi_reversal", analysis=manual)

    assert result.strategy == "chan_bi_reversal"
    assert result.params["entry_signal"] == "down_bi_end"
    assert result.params["exit_signal"] == "up_bi_end"
    assert result.params["structure_counts"] == {"fractals": 0, "bis": 2, "segments": 0, "zhongshu": 0}
    assert result.params["signal_count"] == 2
    assert [(trade.entry_index, trade.exit_index, trade.entry_signal, trade.exit_signal, trade.exit_reason) for trade in result.trades] == [
        (6, 11, "down_bi_end", "up_bi_end", "up_bi"),
    ]
    assert result.trades[0].return_pct == 31.25


def test_run_structure_backtest_uses_wave_zigzag_reversal_strategy() -> None:
    bars = [_price_bar(index, 20, 8, 10 + index) for index in range(14)]
    wave = WaveAnalysisResponse(
        symbol="sh600000",
        timeframe="D",
        algorithm="manual-wave",
        version="0.1.0",
        params={"source": "manual-wave-test"},
        generated_at=datetime(2026, 1, 1),
        threshold_pct=5,
        pivots=[
            _wave_point(0, 10, "start", 1),
            _wave_point(4, 9, "bottom", 2),
            _wave_point(9, 18, "top", 3),
        ],
    )

    result = run_structure_backtest("sh600000", "D", bars, strategy="wave_zigzag_reversal", wave_analysis=wave)

    assert result.strategy == "wave_zigzag_reversal"
    assert result.params["entry_signal"] == "wave_bottom"
    assert result.params["exit_signal"] == "wave_top"
    assert result.params["source_algorithm"] == "manual-wave"
    assert result.params["structure_counts"] == {"wave_pivots": 3, "wave_tops": 1, "wave_bottoms": 1}
    assert result.params["signal_count"] == 2
    assert [(trade.entry_index, trade.exit_index, trade.entry_signal, trade.exit_signal, trade.exit_reason) for trade in result.trades] == [
        (5, 10, "wave_bottom", "wave_top", "wave_top"),
    ]
    assert result.trades[0].return_pct == 33.3333

    unconstrained_custom_limit = run_structure_backtest(
        "sh600000",
        "D",
        bars,
        strategy="wave_zigzag_reversal",
        wave_analysis=wave,
        apply_limit_constraints=False,
        limit_pct=20,
    )
    assert unconstrained_custom_limit.params["apply_limit_constraints"] is False
    assert unconstrained_custom_limit.params["limit_pct"] == 20
    assert unconstrained_custom_limit.params["limit_rule"] == "prev_close_20pct"
    assert unconstrained_custom_limit.params["skipped_limit_up_entries"] == 0
    assert unconstrained_custom_limit.params["skipped_limit_down_exits"] == 0


def test_run_structure_backtest_uses_zhongshu_breakout_strategy() -> None:
    bars = [
        _price_bar(0, 11, 9, 10),
        _price_bar(1, 11, 9, 10.5),
        _price_bar(2, 11, 9, 11),
        _price_bar(3, 12, 10, 11.5),
        _price_bar(4, 13, 11, 12.5),
        _price_bar(5, 12, 10, 10.5),
        _price_bar(6, 10, 8, 9.5),
        _price_bar(7, 11, 9, 10),
    ]
    manual = ChanAnalysisResponse(
        symbol="sh600000",
        timeframe="D",
        algorithm="manual-chan",
        version="0.5.0",
        params={"source": "manual-zhongshu-test"},
        generated_at=datetime(2026, 1, 1),
        fractals=[],
        bis=[],
        segments=[],
        zhongshu=[
            _zhongshu(1, 0, 2, 10, 12),
        ],
    )

    result = run_structure_backtest("sh600000", "D", bars, strategy="chan_zhongshu_breakout", analysis=manual)

    assert result.strategy == "chan_zhongshu_breakout"
    assert result.params["entry_signal"] == "zhongshu_breakout"
    assert result.params["exit_signal"] == "zhongshu_breakdown"
    assert result.params["source_algorithm"] == "manual-chan"
    assert result.params["strategy_condition_key"] == "chan_zhongshu_breakout"
    assert "突破中枢上沿" in result.params["strategy_condition"]
    assert result.params["structure_counts"] == {"fractals": 0, "bis": 0, "segments": 0, "zhongshu": 1}
    assert result.params["signal_count"] == 2
    assert result.params["entry_signal_count"] == 1
    assert result.params["exit_signal_count"] == 1
    assert [(trade.entry_index, trade.exit_index, trade.entry_signal, trade.exit_signal, trade.exit_reason) for trade in result.trades] == [
        (5, 7, "zhongshu_breakout", "zhongshu_breakdown", "zhongshu_breakdown"),
    ]
    assert result.trades[0].return_pct == -4.7619


def test_run_structure_backtest_can_use_manual_chan_analysis() -> None:
    bars = [
        _price_bar(0, 10, 9, 10),
        _price_bar(1, 12, 8, 11),
        _price_bar(2, 11, 7, 9),
        _price_bar(3, 13, 9, 12),
        _price_bar(4, 10, 8, 8),
        _price_bar(5, 11, 9, 10),
    ]
    manual = ChanAnalysisResponse(
        symbol="sh600000",
        timeframe="D",
        algorithm="manual-chan",
        version="0.5.0",
        params={"source": "manual"},
        generated_at=datetime(2026, 1, 1),
        fractals=[_point(1, 8, "bottom"), _point(3, 13, "top")],
        bis=[],
        segments=[],
        zhongshu=[],
    )

    result = run_structure_backtest(
        "sh600000",
        "D",
        bars,
        analysis=manual,
        structure_source="manual",
        manual_annotation_id="ann-1",
    )

    assert result.structure_source == "manual"
    assert result.manual_annotation_id == "ann-1"
    assert result.params["source_algorithm"] == "manual-chan"
    assert [(trade.entry_index, trade.exit_index, trade.return_pct) for trade in result.trades] == [
        (2, 4, -11.1111),
    ]


def _bar(offset: int, high: float, low: float) -> BarRecord:
    return _price_bar(offset, high, low, 10)


def _price_bar(offset: int, high: float, low: float, close: float) -> BarRecord:
    return BarRecord(
        symbol="sh600000",
        timeframe="D",
        trade_date=(date(2026, 1, 1) + timedelta(days=offset)).isoformat(),
        open=9,
        high=high,
        low=low,
        close=close,
        amount=0,
        volume=0,
    )


def _point(index: int, price: float, kind: str) -> AnalysisPoint:
    return AnalysisPoint(
        index=index,
        trade_date=(date(2026, 1, 1) + timedelta(days=index)).isoformat(),
        price=price,
        kind=kind,
    )


def _wave_point(index: int, price: float, kind: str, wave_no: int) -> WavePoint:
    return WavePoint(
        index=index,
        trade_date=(date(2026, 1, 1) + timedelta(days=index)).isoformat(),
        price=price,
        kind=kind,
        wave_no=wave_no,
    )


def _bi(index: int, start_index: int, end_index: int, start_price: float, end_price: float, direction: str) -> ChanBiSegment:
    return ChanBiSegment(
        index=index,
        start_index=start_index,
        end_index=end_index,
        start_trade_date=(date(2026, 1, 1) + timedelta(days=start_index)).isoformat(),
        end_trade_date=(date(2026, 1, 1) + timedelta(days=end_index)).isoformat(),
        start_price=start_price,
        end_price=end_price,
        direction=direction,
        start_kind="top" if direction == "down" else "bottom",
        end_kind="bottom" if direction == "down" else "top",
    )


def _zhongshu(index: int, start_index: int, end_index: int, low: float, high: float) -> ChanZhongshu:
    return ChanZhongshu(
        index=index,
        start_bi_index=1,
        end_bi_index=3,
        start_index=start_index,
        end_index=end_index,
        start_trade_date=(date(2026, 1, 1) + timedelta(days=start_index)).isoformat(),
        end_trade_date=(date(2026, 1, 1) + timedelta(days=end_index)).isoformat(),
        low=low,
        high=high,
        mid=(low + high) / 2,
        bi_count=3,
    )
