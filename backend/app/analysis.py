from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math

from .schemas import (
    AnalysisPoint,
    BacktestEquityPoint,
    BacktestResponse,
    BacktestSummary,
    BacktestTrade,
    BarRecord,
    ChanAnalysisResponse,
    ChanBiSegment,
    ChanLineSegment,
    ChanZhongshu,
    WaveAnalysisResponse,
    WavePoint,
)


CHAN_FRACTAL_VERSION = "0.5.0"
WAVE_ZIGZAG_VERSION = "0.1.0"
STRUCTURE_BACKTEST_VERSION = "0.1.0"
MIN_BARS_FOR_BI = 5
MIN_SWING_BARS = 3
MIN_BIS_FOR_SEGMENT = 3
SEGMENT_STEP_BIS = 3
MIN_BIS_FOR_ZHONGSHU = 3
ZHONGSHU_STEP_BIS = 1
STRUCTURE_BACKTEST_FRACTAL_STRATEGY = "chan_fractal_reversal"
STRUCTURE_BACKTEST_BI_STRATEGY = "chan_bi_reversal"
STRUCTURE_BACKTEST_ZHONGSHU_BREAKOUT_STRATEGY = "chan_zhongshu_breakout"
STRUCTURE_BACKTEST_WAVE_STRATEGY = "wave_zigzag_reversal"
STRUCTURE_BACKTEST_STRATEGY = STRUCTURE_BACKTEST_FRACTAL_STRATEGY
STRUCTURE_BACKTEST_STRATEGIES = {
    STRUCTURE_BACKTEST_FRACTAL_STRATEGY,
    STRUCTURE_BACKTEST_BI_STRATEGY,
    STRUCTURE_BACKTEST_ZHONGSHU_BREAKOUT_STRATEGY,
    STRUCTURE_BACKTEST_WAVE_STRATEGY,
}
STRUCTURE_BACKTEST_CONDITIONS = {
    STRUCTURE_BACKTEST_FRACTAL_STRATEGY: "底分型确认后的下一根 K 线收盘价买入，顶分型确认后的下一根 K 线收盘价卖出。",
    STRUCTURE_BACKTEST_BI_STRATEGY: "向下笔结束后的下一根 K 线收盘价买入，向上笔结束后的下一根 K 线收盘价卖出。",
    STRUCTURE_BACKTEST_ZHONGSHU_BREAKOUT_STRATEGY: "中枢形成后，收盘价突破中枢上沿后的下一根 K 线收盘价买入，跌破中枢下沿后的下一根 K 线收盘价卖出。",
    STRUCTURE_BACKTEST_WAVE_STRATEGY: "ZigZag 低点后的下一根 K 线收盘价买入，ZigZag 高点后的下一根 K 线收盘价卖出。",
}


def detect_fractals(
    symbol: str,
    timeframe: str,
    bars: list[BarRecord],
    *,
    strict_fractal: bool = False,
    include_containment: bool = True,
    min_bars_for_bi: int = MIN_BARS_FOR_BI,
    min_bis_for_segment: int = MIN_BIS_FOR_SEGMENT,
    segment_step_bis: int = SEGMENT_STEP_BIS,
    min_bis_for_zhongshu: int = MIN_BIS_FOR_ZHONGSHU,
    zhongshu_step_bis: int = ZHONGSHU_STEP_BIS,
) -> ChanAnalysisResponse:
    fractals: list[AnalysisPoint] = []
    normalized_min_bars_for_bi = _positive_int(min_bars_for_bi, MIN_BARS_FOR_BI)
    normalized_min_bis_for_segment = _positive_int(min_bis_for_segment, MIN_BIS_FOR_SEGMENT)
    normalized_segment_step_bis = _positive_int(segment_step_bis, SEGMENT_STEP_BIS)
    normalized_min_bis_for_zhongshu = _positive_int(min_bis_for_zhongshu, MIN_BIS_FOR_ZHONGSHU)
    normalized_zhongshu_step_bis = _positive_int(zhongshu_step_bis, ZHONGSHU_STEP_BIS)
    normalized_bars = normalize_containment(bars) if include_containment else raw_chan_klines(bars)
    for index in range(1, len(normalized_bars) - 1):
        prev_bar = normalized_bars[index - 1]
        bar = normalized_bars[index]
        next_bar = normalized_bars[index + 1]
        if bar.high > prev_bar.high and bar.high > next_bar.high:
            fractals.append(
                AnalysisPoint(index=bar.high_index, trade_date=bar.high_trade_date, price=bar.high, kind="top")
            )
        if bar.low < prev_bar.low and bar.low < next_bar.low:
            fractals.append(
                AnalysisPoint(index=bar.low_index, trade_date=bar.low_trade_date, price=bar.low, kind="bottom")
            )
    bis = build_bi_segments(fractals, normalized_min_bars_for_bi)
    return ChanAnalysisResponse(
        symbol=symbol,
        timeframe=timeframe,
        algorithm="chan-fractal",
        version=CHAN_FRACTAL_VERSION,
        params={
            "strict_fractal": strict_fractal,
            "include_containment": include_containment,
            "window": 3,
            "min_bars_for_bi": normalized_min_bars_for_bi,
            "min_bis_for_segment": normalized_min_bis_for_segment,
            "segment_step_bis": normalized_segment_step_bis,
            "min_bis_for_zhongshu": normalized_min_bis_for_zhongshu,
            "zhongshu_step_bis": normalized_zhongshu_step_bis,
        },
        generated_at=_utc_now(),
        fractals=fractals,
        bis=bis,
        segments=build_line_segments(bis, normalized_min_bis_for_segment, normalized_segment_step_bis),
        zhongshu=build_zhongshu(bis, normalized_min_bis_for_zhongshu, normalized_zhongshu_step_bis),
    )


@dataclass(frozen=True)
class _ChanKLine:
    index: int
    trade_date: str
    high: float
    low: float
    high_index: int
    high_trade_date: str
    low_index: int
    low_trade_date: str


def normalize_containment(bars: list[BarRecord]) -> list[_ChanKLine]:
    normalized: list[_ChanKLine] = []
    for index, bar in enumerate(bars):
        current = _ChanKLine(
            index=index,
            trade_date=bar.trade_date,
            high=bar.high,
            low=bar.low,
            high_index=index,
            high_trade_date=bar.trade_date,
            low_index=index,
            low_trade_date=bar.trade_date,
        )
        while normalized and _has_containment(normalized[-1], current):
            previous = normalized.pop()
            direction = _containment_direction(normalized[-1] if normalized else None, previous, current)
            current = _merge_contained_bars(previous, current, direction)
        normalized.append(current)
    return normalized


def raw_chan_klines(bars: list[BarRecord]) -> list[_ChanKLine]:
    return [
        _ChanKLine(
            index=index,
            trade_date=bar.trade_date,
            high=bar.high,
            low=bar.low,
            high_index=index,
            high_trade_date=bar.trade_date,
            low_index=index,
            low_trade_date=bar.trade_date,
        )
        for index, bar in enumerate(bars)
    ]


def _positive_int(value: int, fallback: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return fallback
    return normalized if normalized >= 1 else fallback


def _has_containment(left: _ChanKLine, right: _ChanKLine) -> bool:
    return (left.high >= right.high and left.low <= right.low) or (right.high >= left.high and right.low <= left.low)


def _containment_direction(
    prior: _ChanKLine | None,
    previous: _ChanKLine,
    current: _ChanKLine,
) -> str:
    if prior is not None:
        if previous.high >= prior.high and previous.low >= prior.low:
            return "up"
        if previous.high <= prior.high and previous.low <= prior.low:
            return "down"
    if current.high >= previous.high and current.low >= previous.low:
        return "up"
    if current.high <= previous.high and current.low <= previous.low:
        return "down"
    return "up"


def _merge_contained_bars(left: _ChanKLine, right: _ChanKLine, direction: str) -> _ChanKLine:
    if direction == "down":
        high, high_index, high_trade_date = _lower_high_point(left, right)
        low, low_index, low_trade_date = _lower_low_point(left, right)
    else:
        high, high_index, high_trade_date = _higher_high_point(left, right)
        low, low_index, low_trade_date = _higher_low_point(left, right)
    return _ChanKLine(
        index=right.index,
        trade_date=right.trade_date,
        high=high,
        low=low,
        high_index=high_index,
        high_trade_date=high_trade_date,
        low_index=low_index,
        low_trade_date=low_trade_date,
    )


def _higher_high_point(left: _ChanKLine, right: _ChanKLine) -> tuple[float, int, str]:
    if right.high >= left.high:
        return right.high, right.high_index, right.high_trade_date
    return left.high, left.high_index, left.high_trade_date


def _higher_low_point(left: _ChanKLine, right: _ChanKLine) -> tuple[float, int, str]:
    if right.low >= left.low:
        return right.low, right.low_index, right.low_trade_date
    return left.low, left.low_index, left.low_trade_date


def _lower_high_point(left: _ChanKLine, right: _ChanKLine) -> tuple[float, int, str]:
    if right.high <= left.high:
        return right.high, right.high_index, right.high_trade_date
    return left.high, left.high_index, left.high_trade_date


def _lower_low_point(left: _ChanKLine, right: _ChanKLine) -> tuple[float, int, str]:
    if right.low <= left.low:
        return right.low, right.low_index, right.low_trade_date
    return left.low, left.low_index, left.low_trade_date


def build_bi_segments(fractals: list[AnalysisPoint], min_bars: int = MIN_BARS_FOR_BI) -> list[ChanBiSegment]:
    selected: list[AnalysisPoint] = []
    for point in fractals:
        if not selected:
            selected.append(point)
            continue

        previous = selected[-1]
        if point.kind == previous.kind:
            if _is_more_extreme(point, previous):
                selected[-1] = point
            continue

        if point.index - previous.index < min_bars:
            continue

        selected.append(point)

    segments: list[ChanBiSegment] = []
    for index, (start, end) in enumerate(zip(selected, selected[1:]), start=1):
        segments.append(
            ChanBiSegment(
                index=index,
                start_index=start.index,
                end_index=end.index,
                start_trade_date=start.trade_date,
                end_trade_date=end.trade_date,
                start_price=start.price,
                end_price=end.price,
                direction="up" if end.kind == "top" else "down",
                start_kind=start.kind,
                end_kind=end.kind,
            )
        )
    return segments


def _is_more_extreme(point: AnalysisPoint, previous: AnalysisPoint) -> bool:
    if point.kind == "top":
        return point.price >= previous.price
    if point.kind == "bottom":
        return point.price <= previous.price
    return False


def build_line_segments(
    bis: list[ChanBiSegment],
    min_bis: int = MIN_BIS_FOR_SEGMENT,
    step_bis: int = SEGMENT_STEP_BIS,
) -> list[ChanLineSegment]:
    if min_bis < 1 or step_bis < 1:
        return []

    segments: list[ChanLineSegment] = []
    start = 0
    while start + min_bis <= len(bis):
        window = bis[start : start + min_bis]
        first = window[0]
        last = window[-1]
        segments.append(
            ChanLineSegment(
                index=len(segments) + 1,
                start_bi_index=first.index,
                end_bi_index=last.index,
                start_index=first.start_index,
                end_index=last.end_index,
                start_trade_date=first.start_trade_date,
                end_trade_date=last.end_trade_date,
                start_price=first.start_price,
                end_price=last.end_price,
                direction=last.direction,
                bi_count=len(window),
            )
        )
        start += step_bis
    return segments


def build_zhongshu(
    bis: list[ChanBiSegment],
    min_bis: int = MIN_BIS_FOR_ZHONGSHU,
    step_bis: int = ZHONGSHU_STEP_BIS,
) -> list[ChanZhongshu]:
    if min_bis < 1 or step_bis < 1:
        return []

    zones: list[ChanZhongshu] = []
    start = 0
    while start + min_bis <= len(bis):
        window = bis[start : start + min_bis]
        lows = [min(item.start_price, item.end_price) for item in window]
        highs = [max(item.start_price, item.end_price) for item in window]
        overlap_low = max(lows)
        overlap_high = min(highs)
        if overlap_low <= overlap_high:
            first = window[0]
            last = window[-1]
            zones.append(
                ChanZhongshu(
                    index=len(zones) + 1,
                    start_bi_index=first.index,
                    end_bi_index=last.index,
                    start_index=first.start_index,
                    end_index=last.end_index,
                    start_trade_date=first.start_trade_date,
                    end_trade_date=last.end_trade_date,
                    low=overlap_low,
                    high=overlap_high,
                    mid=(overlap_low + overlap_high) / 2,
                    bi_count=len(window),
                )
            )
        start += step_bis
    return zones


def detect_zigzag_waves(
    symbol: str,
    timeframe: str,
    bars: list[BarRecord],
    threshold_pct: float = 5.0,
    min_swing_bars: int = MIN_SWING_BARS,
) -> WaveAnalysisResponse:
    normalized_min_swing_bars = _positive_int(min_swing_bars, MIN_SWING_BARS)
    params = {"threshold_pct": threshold_pct, "min_swing_bars": normalized_min_swing_bars}
    if not bars:
        return WaveAnalysisResponse(
            symbol=symbol,
            timeframe=timeframe,
            algorithm="wave-zigzag",
            version=WAVE_ZIGZAG_VERSION,
            params=params,
            generated_at=_utc_now(),
            threshold_pct=threshold_pct,
            pivots=[],
        )

    threshold = max(threshold_pct, 0.1) / 100.0
    pivots: list[tuple[int, str, float]] = [(0, "start", bars[0].close)]
    trend: str | None = None
    candidate_index = 0
    candidate_price = bars[0].close

    for index, bar in enumerate(bars[1:], start=1):
        high = bar.high
        low = bar.low
        if trend is None:
            up_change = (high - candidate_price) / candidate_price
            down_change = (candidate_price - low) / candidate_price
            if up_change >= threshold and index >= normalized_min_swing_bars:
                trend = "up"
                candidate_index = index
                candidate_price = high
                pivots[0] = (0, "bottom", bars[0].low)
            elif down_change >= threshold and index >= normalized_min_swing_bars:
                trend = "down"
                candidate_index = index
                candidate_price = low
                pivots[0] = (0, "top", bars[0].high)
            continue

        if trend == "up":
            if high >= candidate_price:
                candidate_index = index
                candidate_price = high
            elif (candidate_price - low) / candidate_price >= threshold and candidate_index - pivots[-1][0] >= normalized_min_swing_bars:
                pivots.append((candidate_index, "top", candidate_price))
                trend = "down"
                candidate_index = index
                candidate_price = low
        else:
            if low <= candidate_price:
                candidate_index = index
                candidate_price = low
            elif (high - candidate_price) / candidate_price >= threshold and candidate_index - pivots[-1][0] >= normalized_min_swing_bars:
                pivots.append((candidate_index, "bottom", candidate_price))
                trend = "up"
                candidate_index = index
                candidate_price = high

    if pivots[-1][0] != candidate_index and candidate_index - pivots[-1][0] >= normalized_min_swing_bars:
        pivots.append((candidate_index, "top" if trend == "up" else "bottom", candidate_price))

    points = [
        WavePoint(
            index=index,
            trade_date=bars[index].trade_date,
            price=price,
            kind=kind,
            wave_no=wave_no,
        )
        for wave_no, (index, kind, price) in enumerate(pivots, start=1)
    ]
    return WaveAnalysisResponse(
        symbol=symbol,
        timeframe=timeframe,
        algorithm="wave-zigzag",
        version=WAVE_ZIGZAG_VERSION,
        params=params,
        generated_at=_utc_now(),
        threshold_pct=threshold_pct,
        pivots=points,
    )


def run_structure_backtest(
    symbol: str,
    timeframe: str,
    bars: list[BarRecord],
    strategy: str = STRUCTURE_BACKTEST_STRATEGY,
    analysis: ChanAnalysisResponse | None = None,
    wave_analysis: WaveAnalysisResponse | None = None,
    structure_source: str = "auto",
    manual_annotation_id: str | None = None,
    wave_threshold_pct: float = 5.0,
    wave_min_swing_bars: int = MIN_SWING_BARS,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    position_pct: float = 100.0,
    apply_limit_constraints: bool = False,
    limit_pct: float = 10.0,
) -> BacktestResponse:
    if strategy not in STRUCTURE_BACKTEST_STRATEGIES:
        raise ValueError(f"Unsupported backtest strategy: {strategy}")

    if strategy == STRUCTURE_BACKTEST_WAVE_STRATEGY:
        wave_analysis = wave_analysis or detect_zigzag_waves(symbol, timeframe, bars, wave_threshold_pct, wave_min_swing_bars)
        source_algorithm = wave_analysis.algorithm
        source_version = wave_analysis.version
        structure_counts = _wave_structure_counts(wave_analysis)
        signal_points, entry_signal_name, exit_signal_name, exit_reason = _wave_reversal_signal_points(
            wave_analysis.pivots
        ), "wave_bottom", "wave_top", "wave_top"
    else:
        analysis = analysis or detect_fractals(symbol, timeframe, bars)
        source_algorithm = analysis.algorithm
        source_version = analysis.version
        structure_counts = _chan_structure_counts(analysis)
        signal_points, entry_signal_name, exit_signal_name, exit_reason = _backtest_signals_for_strategy(
            strategy, analysis, bars
        )
    normalized_fee_bps = max(fee_bps, 0.0)
    normalized_slippage_bps = max(slippage_bps, 0.0)
    normalized_position_pct = min(max(position_pct, 0.0), 100.0)
    normalized_limit_pct = (
        min(max(limit_pct, 0.1), 30.0) if math.isfinite(limit_pct) else 10.0
    )
    trades: list[BacktestTrade] = []
    entry_index: int | None = None
    entry_signal: AnalysisPoint | None = None
    skipped_limit_up_entries = 0
    skipped_limit_down_exits = 0
    open_position: dict | None = None

    for point in signal_points:
        execution_index = point.index + 1
        if execution_index >= len(bars):
            continue

        if point.kind == "bottom" and entry_index is None:
            if apply_limit_constraints and _is_limit_up_bar(bars, execution_index, normalized_limit_pct):
                skipped_limit_up_entries += 1
                continue
            entry_index = execution_index
            entry_signal = point
            continue

        if point.kind == "top" and entry_index is not None and execution_index > entry_index:
            if apply_limit_constraints and _is_limit_down_bar(bars, execution_index, normalized_limit_pct):
                skipped_limit_down_exits += 1
                continue
            trades.append(
                _build_backtest_trade(
                    len(trades) + 1,
                    bars,
                    entry_index,
                    execution_index,
                    entry_signal,
                    point,
                    entry_signal_name,
                    exit_signal_name,
                    exit_reason,
                    normalized_fee_bps,
                    normalized_slippage_bps,
                    normalized_position_pct,
                )
            )
            entry_index = None
            entry_signal = None

    if entry_index is not None and entry_index < len(bars) - 1:
        forced_exit_index = len(bars) - 1
        if apply_limit_constraints and _is_limit_down_bar(bars, forced_exit_index, normalized_limit_pct):
            skipped_limit_down_exits += 1
            open_position = _build_open_position(bars, entry_index, entry_signal_name, "limit_down_exit_blocked")
        else:
            trades.append(
                _build_backtest_trade(
                    len(trades) + 1,
                    bars,
                    entry_index,
                    forced_exit_index,
                    entry_signal,
                    None,
                    entry_signal_name,
                    exit_signal_name,
                    "end_of_data",
                    normalized_fee_bps,
                    normalized_slippage_bps,
                    normalized_position_pct,
                )
            )
    elif entry_index is not None:
        open_position = _build_open_position(bars, entry_index, entry_signal_name, "no_exit_bar")

    params = {
        "entry_signal": entry_signal_name,
        "exit_signal": exit_signal_name,
        "execution_price": "next_bar_close",
        "source_algorithm": source_algorithm,
        "source_version": source_version,
        "structure_source": structure_source,
        "structure_counts": structure_counts,
        "strategy_condition_key": strategy,
        "strategy_condition": STRUCTURE_BACKTEST_CONDITIONS[strategy],
        "signal_count": len(signal_points),
        "entry_signal_count": sum(1 for point in signal_points if point.kind == "bottom"),
        "exit_signal_count": sum(1 for point in signal_points if point.kind == "top"),
        "fee_bps": normalized_fee_bps,
        "slippage_bps": normalized_slippage_bps,
        "position_pct": normalized_position_pct,
        "apply_limit_constraints": apply_limit_constraints,
        "limit_pct": normalized_limit_pct,
        "limit_rule": f"prev_close_{normalized_limit_pct:g}pct",
        "skipped_limit_up_entries": skipped_limit_up_entries,
        "skipped_limit_down_exits": skipped_limit_down_exits,
        "open_position_count": 1 if open_position else 0,
        "open_position": open_position,
    }
    if strategy == STRUCTURE_BACKTEST_WAVE_STRATEGY:
        params["wave_threshold_pct"] = wave_threshold_pct
        params["wave_min_swing_bars"] = wave_min_swing_bars
    elif analysis and analysis.params.get("derived_from_manual_fractals") is True:
        params["derived_from_manual_fractals"] = True

    equity_curve = _build_equity_curve(trades)
    return BacktestResponse(
        symbol=symbol,
        timeframe=timeframe,
        algorithm="structure-backtest",
        version=STRUCTURE_BACKTEST_VERSION,
        strategy=strategy,
        structure_source=structure_source,
        manual_annotation_id=manual_annotation_id,
        params=params,
        generated_at=_utc_now(),
        bars_tested=len(bars),
        trades=trades,
        equity_curve=equity_curve,
        summary=_summarize_backtest(trades, equity_curve),
    )


def _chan_structure_counts(analysis: ChanAnalysisResponse) -> dict[str, int]:
    return {
        "fractals": len(analysis.fractals),
        "bis": len(analysis.bis),
        "segments": len(analysis.segments),
        "zhongshu": len(analysis.zhongshu),
    }


def _wave_structure_counts(wave_analysis: WaveAnalysisResponse) -> dict[str, int]:
    return {
        "wave_pivots": len(wave_analysis.pivots),
        "wave_tops": sum(1 for point in wave_analysis.pivots if point.kind == "top"),
        "wave_bottoms": sum(1 for point in wave_analysis.pivots if point.kind == "bottom"),
    }


def _backtest_signals_for_strategy(
    strategy: str,
    analysis: ChanAnalysisResponse,
    bars: list[BarRecord],
) -> tuple[list[AnalysisPoint], str, str, str]:
    if strategy == STRUCTURE_BACKTEST_BI_STRATEGY:
        return _bi_reversal_signal_points(analysis.bis), "down_bi_end", "up_bi_end", "up_bi"
    if strategy == STRUCTURE_BACKTEST_ZHONGSHU_BREAKOUT_STRATEGY:
        return (
            _zhongshu_breakout_signal_points(analysis.zhongshu, bars),
            "zhongshu_breakout",
            "zhongshu_breakdown",
            "zhongshu_breakdown",
        )
    return analysis.fractals, "bottom_fractal", "top_fractal", "top_fractal"


def _bi_reversal_signal_points(bis: list[ChanBiSegment]) -> list[AnalysisPoint]:
    points: list[AnalysisPoint] = []
    for bi in bis:
        if bi.direction == "down":
            points.append(
                AnalysisPoint(index=bi.end_index, trade_date=bi.end_trade_date, price=bi.end_price, kind="bottom")
            )
        elif bi.direction == "up":
            points.append(
                AnalysisPoint(index=bi.end_index, trade_date=bi.end_trade_date, price=bi.end_price, kind="top")
            )
    return points


def _wave_reversal_signal_points(pivots: list[WavePoint]) -> list[AnalysisPoint]:
    points: list[AnalysisPoint] = []
    for pivot in pivots:
        if pivot.kind in {"bottom", "top"}:
            points.append(
                AnalysisPoint(index=pivot.index, trade_date=pivot.trade_date, price=pivot.price, kind=pivot.kind)
            )
    return points


def _zhongshu_breakout_signal_points(zhongshu: list[ChanZhongshu], bars: list[BarRecord]) -> list[AnalysisPoint]:
    points: list[AnalysisPoint] = []
    seen: set[tuple[int, str]] = set()
    for zone in zhongshu:
        state = "inside"
        for index in range(zone.end_index + 1, len(bars)):
            close = bars[index].close
            if close > zone.high and state != "above":
                key = (index, "bottom")
                if key not in seen:
                    points.append(AnalysisPoint(index=index, trade_date=bars[index].trade_date, price=close, kind="bottom"))
                    seen.add(key)
                state = "above"
            elif close < zone.low and state != "below":
                key = (index, "top")
                if key not in seen:
                    points.append(AnalysisPoint(index=index, trade_date=bars[index].trade_date, price=close, kind="top"))
                    seen.add(key)
                state = "below"
            elif zone.low <= close <= zone.high:
                state = "inside"
    return sorted(points, key=lambda item: item.index)


def _is_limit_up_bar(bars: list[BarRecord], index: int, limit_pct: float = 10.0) -> bool:
    if index <= 0 or index >= len(bars):
        return False
    previous_close = bars[index - 1].close
    if previous_close <= 0:
        return False
    threshold = max(limit_pct, 0.1) / 100
    return (bars[index].close - previous_close) / previous_close >= threshold - 0.001


def _is_limit_down_bar(bars: list[BarRecord], index: int, limit_pct: float = 10.0) -> bool:
    if index <= 0 or index >= len(bars):
        return False
    previous_close = bars[index - 1].close
    if previous_close <= 0:
        return False
    threshold = max(limit_pct, 0.1) / 100
    return (previous_close - bars[index].close) / previous_close >= threshold - 0.001


def _build_open_position(
    bars: list[BarRecord],
    entry_index: int,
    entry_signal_name: str,
    reason: str,
) -> dict:
    entry_bar = bars[entry_index]
    latest_bar = bars[-1]
    return {
        "entry_index": entry_index,
        "entry_trade_date": entry_bar.trade_date,
        "entry_price": entry_bar.close,
        "entry_signal": entry_signal_name,
        "latest_index": len(bars) - 1,
        "latest_trade_date": latest_bar.trade_date,
        "latest_close": latest_bar.close,
        "holding_bars": len(bars) - 1 - entry_index,
        "reason": reason,
    }


def _build_backtest_trade(
    index: int,
    bars: list[BarRecord],
    entry_index: int,
    exit_index: int,
    entry_signal: AnalysisPoint | None,
    exit_signal: AnalysisPoint | None,
    entry_signal_name: str,
    exit_signal_name: str,
    exit_reason: str,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    position_pct: float = 100.0,
) -> BacktestTrade:
    entry_bar = bars[entry_index]
    exit_bar = bars[exit_index]
    slippage_rate = slippage_bps / 10_000
    entry_price = entry_bar.close * (1 + slippage_rate)
    exit_price = exit_bar.close * (1 - slippage_rate)
    gross_return_pct = ((exit_price - entry_price) / entry_price) * 100
    net_full_position_return_pct = gross_return_pct - (fee_bps * 2 / 100)
    return_pct = net_full_position_return_pct * (position_pct / 100)
    return BacktestTrade(
        index=index,
        entry_index=entry_index,
        exit_index=exit_index,
        entry_trade_date=entry_bar.trade_date,
        exit_trade_date=exit_bar.trade_date,
        entry_price=round(entry_price, 4),
        exit_price=round(exit_price, 4),
        return_pct=round(return_pct, 4),
        holding_bars=exit_index - entry_index,
        entry_signal=entry_signal_name if entry_signal else "bottom",
        exit_signal=exit_signal_name if exit_signal else "end",
        exit_reason=exit_reason,
    )


def _build_equity_curve(trades: list[BacktestTrade]) -> list[BacktestEquityPoint]:
    equity = 1.0
    peak = 1.0
    points: list[BacktestEquityPoint] = []
    for trade in trades:
        equity *= 1 + trade.return_pct / 100
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100
        points.append(
            BacktestEquityPoint(
                trade_index=trade.index,
                trade_date=trade.exit_trade_date,
                equity=round(equity, 6),
                equity_return_pct=round((equity - 1) * 100, 4),
                drawdown_pct=round(drawdown, 4),
            )
        )
    return points


def _summarize_backtest(trades: list[BacktestTrade], equity_curve: list[BacktestEquityPoint] | None = None) -> BacktestSummary:
    if not trades:
        return BacktestSummary()

    wins = sum(1 for trade in trades if trade.return_pct > 0)
    losses = sum(1 for trade in trades if trade.return_pct < 0)
    curve = equity_curve if equity_curve is not None else _build_equity_curve(trades)
    total_return_pct = curve[-1].equity_return_pct if curve else 0.0
    max_drawdown = max((point.drawdown_pct for point in curve), default=0.0)
    holding_bars = sorted(trade.holding_bars for trade in trades)
    middle_index = len(holding_bars) // 2
    median_holding_bars = (
        holding_bars[middle_index]
        if len(holding_bars) % 2 == 1
        else (holding_bars[middle_index - 1] + holding_bars[middle_index]) / 2
    )

    return BacktestSummary(
        total_trades=len(trades),
        winning_trades=wins,
        losing_trades=losses,
        win_rate=round(wins / len(trades) * 100, 2),
        total_return_pct=round(total_return_pct, 4),
        average_return_pct=round(sum(trade.return_pct for trade in trades) / len(trades), 4),
        max_drawdown_pct=round(max_drawdown, 4),
        average_holding_bars=round(sum(trade.holding_bars for trade in trades) / len(trades), 2),
        min_holding_bars=holding_bars[0],
        max_holding_bars=holding_bars[-1],
        median_holding_bars=round(median_holding_bars, 2),
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
