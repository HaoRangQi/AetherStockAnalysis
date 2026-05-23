from __future__ import annotations

from .schemas import AnalysisPoint, BarRecord, ChanAnalysisResponse, WaveAnalysisResponse, WavePoint


def detect_fractals(symbol: str, timeframe: str, bars: list[BarRecord]) -> ChanAnalysisResponse:
    fractals: list[AnalysisPoint] = []
    for index in range(1, len(bars) - 1):
        prev_bar = bars[index - 1]
        bar = bars[index]
        next_bar = bars[index + 1]
        if bar.high > prev_bar.high and bar.high > next_bar.high:
            fractals.append(
                AnalysisPoint(index=index, trade_date=bar.trade_date, price=bar.high, kind="top")
            )
        if bar.low < prev_bar.low and bar.low < next_bar.low:
            fractals.append(
                AnalysisPoint(index=index, trade_date=bar.trade_date, price=bar.low, kind="bottom")
            )
    return ChanAnalysisResponse(
        symbol=symbol,
        timeframe=timeframe,
        algorithm="chan-fractal",
        version="0.1.0",
        fractals=fractals,
    )


def detect_zigzag_waves(
    symbol: str,
    timeframe: str,
    bars: list[BarRecord],
    threshold_pct: float = 5.0,
) -> WaveAnalysisResponse:
    if not bars:
        return WaveAnalysisResponse(
            symbol=symbol,
            timeframe=timeframe,
            algorithm="wave-zigzag",
            version="0.1.0",
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
            if up_change >= threshold:
                trend = "up"
                candidate_index = index
                candidate_price = high
                pivots[0] = (0, "bottom", bars[0].low)
            elif down_change >= threshold:
                trend = "down"
                candidate_index = index
                candidate_price = low
                pivots[0] = (0, "top", bars[0].high)
            continue

        if trend == "up":
            if high >= candidate_price:
                candidate_index = index
                candidate_price = high
            elif (candidate_price - low) / candidate_price >= threshold:
                pivots.append((candidate_index, "top", candidate_price))
                trend = "down"
                candidate_index = index
                candidate_price = low
        else:
            if low <= candidate_price:
                candidate_index = index
                candidate_price = low
            elif (high - candidate_price) / candidate_price >= threshold:
                pivots.append((candidate_index, "bottom", candidate_price))
                trend = "up"
                candidate_index = index
                candidate_price = high

    if pivots[-1][0] != candidate_index:
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
        version="0.1.0",
        threshold_pct=threshold_pct,
        pivots=points,
    )
