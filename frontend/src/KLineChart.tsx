import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import {
  BusinessDay,
  CandlestickData,
  ColorType,
  CandlestickSeries,
  LogicalRange,
  HistogramSeries,
  HistogramData,
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  LineSeries,
  LineData,
  MouseEventParams,
  SeriesMarker,
  Time,
  createChart,
  createSeriesMarkers,
} from "lightweight-charts";
import { AnnotationRecord, BacktestTrade, BarRecord, ChanAnalysis, WaveAnalysis } from "./api";

export type ChartClickAnchor = {
  tradeDate: string;
  price: number;
};

export type ManualDrawLine = {
  id: string;
  start: ChartClickAnchor;
  end: ChartClickAnchor;
};

type PointerPosition = {
  x: number;
  y: number;
};

type ResolvedAnchor = {
  anchor: ChartClickAnchor;
  barIndex: number | null;
};

type ManualLineWidth = 1 | 2 | 3 | 4;

const PRICE_PANE_BOTTOM_RATIO = 0.78;

type Props = {
  bars: BarRecord[];
  analysis: ChanAnalysis | null;
  waveAnalysis: WaveAnalysis | null;
  annotations: AnnotationRecord[];
  backtestTrades: BacktestTrade[];
  layers: {
    volume: boolean;
    fractals: boolean;
    bi: boolean;
    segments: boolean;
    zhongshu: boolean;
    wave: boolean;
    annotations: boolean;
    backtest: boolean;
  };
  theme: "light" | "dark";
  emptyMessage: string;
  fitContentToken: string;
  hasMoreHistory: boolean;
  isLoadingHistory: boolean;
  onLoadMoreHistory: () => void;
  manualLines: ManualDrawLine[];
  manualLineColor: string;
  manualLineWidth: number;
  lineDrawingMode: boolean;
  onLineDrawingHint?: (message: string) => void;
  onCreateManualLine?: (start: ChartClickAnchor, end: ChartClickAnchor) => void;
  onChartClick?: (anchor: ChartClickAnchor) => void;
};

export type KLineChartHandle = {
  takeScreenshotDataUrl: () => string | null;
};

export const KLineChart = forwardRef<KLineChartHandle, Props>(function KLineChart(
  {
    bars,
    analysis,
    waveAnalysis,
    annotations,
    backtestTrades,
    layers,
    theme,
    emptyMessage,
    fitContentToken,
    hasMoreHistory,
    isLoadingHistory,
    onLoadMoreHistory,
    manualLines,
    manualLineColor,
    manualLineWidth,
    lineDrawingMode,
    onLineDrawingHint,
    onCreateManualLine,
    onChartClick,
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const topSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bottomSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const biSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const segmentSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const zhongshuHighSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const zhongshuLowSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const waveSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const waveMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const annotationMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const backtestMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const manualLineSeriesRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const previewLineSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const chartBarsRef = useRef<BarRecord[]>([]);
  const historyStateRef = useRef({ hasMoreHistory, isLoadingHistory, onLoadMoreHistory });
  const chartClickHandlerRef = useRef<Props["onChartClick"]>(undefined);
  const lineDrawingModeRef = useRef<boolean>(lineDrawingMode);
  const lineDrawingHintHandlerRef = useRef<Props["onLineDrawingHint"]>(onLineDrawingHint);
  const createManualLineHandlerRef = useRef<Props["onCreateManualLine"]>(onCreateManualLine);
  const pendingLineStartRef = useRef<ResolvedAnchor | null>(null);
  const fittedTokenRef = useRef<string | null>(null);
  const userNavigatedRef = useRef(false);
  const dragStartRef = useRef<PointerPosition | null>(null);
  const suppressNextClickRef = useRef(false);
  const [renderError, setRenderError] = useState<string | null>(null);

  useEffect(() => {
    historyStateRef.current = { hasMoreHistory, isLoadingHistory, onLoadMoreHistory };
  }, [hasMoreHistory, isLoadingHistory, onLoadMoreHistory]);

  useEffect(() => {
    chartClickHandlerRef.current = onChartClick;
  }, [onChartClick]);

  useEffect(() => {
    lineDrawingModeRef.current = lineDrawingMode;
    if (!lineDrawingMode) {
      pendingLineStartRef.current = null;
      previewLineSeriesRef.current?.setData([]);
    }
  }, [lineDrawingMode]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) {
      return;
    }
    chart.applyOptions({
      handleScroll: true,
      handleScale: true,
    });
  }, [lineDrawingMode]);

  useEffect(() => {
    createManualLineHandlerRef.current = onCreateManualLine;
  }, [onCreateManualLine]);

  useEffect(() => {
    lineDrawingHintHandlerRef.current = onLineDrawingHint;
  }, [onLineDrawingHint]);

  useImperativeHandle(
    ref,
    () => ({
      takeScreenshotDataUrl: () => chartRef.current?.takeScreenshot(true).toDataURL("image/png") ?? null,
    }),
    [],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const palette = chartPalette("light");
    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: palette.background },
        textColor: palette.text,
        fontFamily: "Inter, Roboto, system-ui, sans-serif",
      },
      localization: {
        locale: "zh-CN",
        dateFormat: "yyyy-MM-dd",
        timeFormatter: (value: Time) => formatCrosshairTimeLabel(value),
      },
      grid: {
        vertLines: { color: palette.grid },
        horzLines: { color: palette.grid },
      },
      rightPriceScale: {
        borderColor: palette.border,
        autoScale: true,
      },
      timeScale: {
        borderColor: palette.border,
      },
      crosshair: {
        mode: 1,
      },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#d32f2f",
      downColor: "#1b8f5a",
      borderUpColor: "#d32f2f",
      borderDownColor: "#1b8f5a",
      wickUpColor: "#d32f2f",
      wickDownColor: "#1b8f5a",
    });
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.78,
        bottom: 0,
      },
    });
    const topSeries = chart.addSeries(LineSeries, {
      color: "#b3261e",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const bottomSeries = chart.addSeries(LineSeries, {
      color: "#006a60",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const biSeries = chart.addSeries(LineSeries, {
      color: "#344767",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const segmentSeries = chart.addSeries(LineSeries, {
      color: "#1f1f1f",
      lineWidth: 3,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const zhongshuHighSeries = chart.addSeries(LineSeries, {
      color: "#7d5260",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const zhongshuLowSeries = chart.addSeries(LineSeries, {
      color: "#7d5260",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const waveSeries = chart.addSeries(LineSeries, {
      color: "#6750a4",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const annotationMarkers = createSeriesMarkers(candleSeries, [], {
      zOrder: "top",
    });
    const waveMarkers = createSeriesMarkers(candleSeries, [], {
      zOrder: "aboveSeries",
    });
    const backtestMarkers = createSeriesMarkers(candleSeries, [], {
      zOrder: "top",
    });
    const manualLineSeries = manualLineSeriesRef.current;
    const previewLineSeries = chart.addSeries(LineSeries, {
      color: "rgba(255, 143, 0, 0.72)",
      lineWidth: 2,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    previewLineSeriesRef.current = previewLineSeries;

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    topSeriesRef.current = topSeries;
    bottomSeriesRef.current = bottomSeries;
    biSeriesRef.current = biSeries;
    segmentSeriesRef.current = segmentSeries;
    zhongshuHighSeriesRef.current = zhongshuHighSeries;
    zhongshuLowSeriesRef.current = zhongshuLowSeries;
    waveSeriesRef.current = waveSeries;
    waveMarkersRef.current = waveMarkers;
    annotationMarkersRef.current = annotationMarkers;
    backtestMarkersRef.current = backtestMarkers;

    let resizeFrame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        chart.applyOptions({
          width: container.clientWidth,
          height: container.clientHeight,
        });
      });
    });
    observer.observe(container);
    const markUserNavigated = () => {
      userNavigatedRef.current = true;
    };
    const nearestBarFromCoordinate = (x: number): { bar: BarRecord; index: number } | null => {
      const currentChart = chartRef.current;
      if (!currentChart || chartBarsRef.current.length === 0) {
        return null;
      }
      const logical = currentChart.timeScale().coordinateToLogical(x);
      if (logical === null || !Number.isFinite(logical)) {
        return null;
      }
      const index = Math.max(0, Math.min(chartBarsRef.current.length - 1, Math.round(logical)));
      const bar = chartBarsRef.current[index];
      if (!bar) {
        return null;
      }
      return { bar, index };
    };
    const anchorFromClickParam = (
      param: MouseEventParams<Time>,
      enforcePricePane: boolean,
      requireNearestBar: boolean,
    ): ResolvedAnchor | null => {
      if (!param.point) {
        return null;
      }
      const currentChart = chartRef.current;
      const currentCandleSeries = candleSeriesRef.current;
      if (!currentChart || !currentCandleSeries) {
        return null;
      }
      const nearestBar = nearestBarFromCoordinate(param.point.x);
      if (requireNearestBar && !nearestBar) {
        return null;
      }
      const timeFromPoint = param.time ?? currentChart.timeScale().coordinateToTime(param.point.x);
      const time = timeFromPoint ?? (nearestBar ? toChartTime(nearestBar.bar.trade_date) : null);
      if (time === null) {
        return null;
      }
      const fallbackPrice = nearestBar ? nearestBar.bar.close : null;
      const pricePaneBottom = container.clientHeight * PRICE_PANE_BOTTOM_RATIO;
      const inPricePane = param.point.y <= pricePaneBottom;
      const price = currentCandleSeries.coordinateToPrice(param.point.y);
      const usePointerPrice = !enforcePricePane || inPricePane;
      const resolvedPrice =
        usePointerPrice && price !== null && Number.isFinite(price) ? price : fallbackPrice;
      if (resolvedPrice === null || !Number.isFinite(resolvedPrice)) {
        return null;
      }
      if (lineDrawingModeRef.current) {
        console.info("[KLineChart] line-anchor-resolve", {
          source: usePointerPrice ? "pointer-price" : "nearest-bar-close",
          enforcePricePane,
          inPricePane,
          y: param.point.y,
          pricePaneBottom,
          pointerPrice: price,
          fallbackPrice,
        });
      }
      return {
        anchor: {
          tradeDate: nearestBar?.bar.trade_date ?? chartTimeToString(time),
          price: resolvedPrice,
        },
        barIndex: nearestBar?.index ?? null,
      };
    };
    const adjustSameBarAnchor = (start: ResolvedAnchor, end: ResolvedAnchor): ResolvedAnchor | null => {
      const bars = chartBarsRef.current;
      if (!bars.length || start.barIndex === null) {
        return null;
      }
      const currentIndex = start.barIndex;
      const fallbackNext = bars[currentIndex + 1];
      const fallbackPrev = bars[currentIndex - 1];
      const preferred =
        end.barIndex !== null && end.barIndex > currentIndex
          ? fallbackNext ?? fallbackPrev
          : fallbackPrev ?? fallbackNext;
      if (!preferred) {
        return null;
      }
      const adjustedIndex = bars.indexOf(preferred);
      return {
        anchor: {
          tradeDate: preferred.trade_date,
          price: end.anchor.price,
        },
        barIndex: adjustedIndex >= 0 ? adjustedIndex : null,
      };
    };
    const clearPreviewLine = () => {
      previewLineSeriesRef.current?.setData([]);
    };
    const showPreviewLine = (start: ResolvedAnchor, end: ResolvedAnchor) => {
      const previewSeries = previewLineSeriesRef.current;
      if (!previewSeries) {
        return;
      }
      const first = {
        time: toChartTime(start.anchor.tradeDate),
        value: start.anchor.price,
      };
      const second = {
        time: toChartTime(end.anchor.tradeDate),
        value: end.anchor.price,
      };
      if (
        !isValidChartTime(first.time) ||
        !isValidChartTime(second.time) ||
        !Number.isFinite(first.value) ||
        !Number.isFinite(second.value)
      ) {
        clearPreviewLine();
        return;
      }
      const ordered =
        chartTimeOrder(first.time) <= chartTimeOrder(second.time)
          ? [first, second]
          : [second, first];
      previewSeries.setData(ordered);
    };
    const handleAnchorSelection = (resolved: ResolvedAnchor) => {
      if (lineDrawingModeRef.current) {
        console.info("[KLineChart] line-anchor", resolved);
        const pendingStart = pendingLineStartRef.current;
        if (!pendingStart) {
          pendingLineStartRef.current = resolved;
          clearPreviewLine();
          lineDrawingHintHandlerRef.current?.("已记录起点，请再点击一次选择终点。");
          return;
        }
        let finalEnd = resolved;
        if (pendingStart.anchor.tradeDate === resolved.anchor.tradeDate) {
          const adjusted = adjustSameBarAnchor(pendingStart, resolved);
          if (adjusted) {
            finalEnd = adjusted;
            lineDrawingHintHandlerRef.current?.("终点自动吸附到相邻 K 线，已完成划线。");
            console.info("[KLineChart] line-anchor-adjusted", {
              reason: "same-trade-date",
              start: pendingStart,
              end: resolved,
              adjusted: finalEnd,
            });
          } else {
            lineDrawingHintHandlerRef.current?.("终点请点击不同交易时间位置。");
            return;
          }
        }
        pendingLineStartRef.current = null;
        clearPreviewLine();
        createManualLineHandlerRef.current?.(pendingStart.anchor, finalEnd.anchor);
        lineDrawingHintHandlerRef.current?.("已完成一条手工划线。");
        return;
      }
      chartClickHandlerRef.current?.(resolved.anchor);
    };
    const anchorFromPointerEvent = (event: PointerEvent, enforcePricePane: boolean): ResolvedAnchor | null => {
      const currentChart = chartRef.current;
      const currentCandleSeries = candleSeriesRef.current;
      if (!currentChart || !currentCandleSeries) {
        return null;
      }
      const rect = container.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const time = currentChart.timeScale().coordinateToTime(x);
      const price = currentCandleSeries.coordinateToPrice(y);
      const nearestBar = nearestBarFromCoordinate(x);
      if (enforcePricePane && !nearestBar) {
        return null;
      }
      const fallbackPrice = nearestBar ? nearestBar.bar.close : null;
      if (time === null) {
        return null;
      }
      const pricePaneBottom = rect.height * PRICE_PANE_BOTTOM_RATIO;
      const inPricePane = y <= pricePaneBottom;
      const usePointerPrice = !enforcePricePane || inPricePane;
      const resolvedPrice =
        usePointerPrice && price !== null && Number.isFinite(price) ? price : fallbackPrice;
      if (resolvedPrice === null || !Number.isFinite(resolvedPrice)) {
        return null;
      }
      if (lineDrawingModeRef.current) {
        console.info("[KLineChart] line-anchor-resolve", {
          source: usePointerPrice ? "pointer-price" : "nearest-bar-close",
          enforcePricePane,
          inPricePane,
          y,
          pricePaneBottom,
          pointerPrice: price,
          fallbackPrice,
        });
      }
      return {
        anchor: {
          tradeDate: nearestBar?.bar.trade_date ?? chartTimeToString(time as Time),
          price: resolvedPrice,
        },
        barIndex: nearestBar?.index ?? null,
      };
    };
    const handlePointerDown = (event: PointerEvent) => {
      markUserNavigated();
      if (event.button === 0) {
        dragStartRef.current = { x: event.clientX, y: event.clientY };
      } else {
        dragStartRef.current = null;
      }
      if (lineDrawingModeRef.current) {
        return;
      }
      if (event.button !== 0 || (!lineDrawingModeRef.current && !chartClickHandlerRef.current)) {
        return;
      }
    };
    const handlePointerUp = (event: PointerEvent) => {
      const start = dragStartRef.current;
      dragStartRef.current = null;
      const moved = start ? Math.hypot(event.clientX - start.x, event.clientY - start.y) : 0;
      if (lineDrawingModeRef.current) {
        if (moved > 8) {
          return;
        }
        const anchor = anchorFromPointerEvent(event, true);
        if (!anchor) {
          console.warn("[KLineChart] pointerup ignored in drawing mode: cannot resolve anchor", {
            clientX: event.clientX,
            clientY: event.clientY,
          });
          lineDrawingHintHandlerRef.current?.("未命中有效 K 线，请在蜡烛附近点击。");
          return;
        }
        suppressNextClickRef.current = true;
        handleAnchorSelection(anchor);
        return;
      }
      const onClick = chartClickHandlerRef.current;
      if (!start || (!onClick && !lineDrawingModeRef.current)) {
        return;
      }
      if (moved > 8) {
        return;
      }
      const anchor = anchorFromPointerEvent(event, false);
      if (!anchor) {
        return;
      }
      suppressNextClickRef.current = true;
      handleAnchorSelection(anchor);
    };
    const handlePointerMove = (event: PointerEvent) => {
      if (!lineDrawingModeRef.current) {
        return;
      }
      const pendingStart = pendingLineStartRef.current;
      if (!pendingStart) {
        clearPreviewLine();
        return;
      }
      const anchor = anchorFromPointerEvent(event, true);
      if (!anchor) {
        clearPreviewLine();
        return;
      }
      const previewEnd =
        pendingStart.anchor.tradeDate === anchor.anchor.tradeDate
          ? adjustSameBarAnchor(pendingStart, anchor) ?? anchor
          : anchor;
      showPreviewLine(pendingStart, previewEnd);
    };
    const handlePointerLeave = () => {
      clearPreviewLine();
    };
    container.addEventListener("pointerdown", markUserNavigated);
    container.addEventListener("pointerdown", handlePointerDown);
    container.addEventListener("pointerup", handlePointerUp);
    container.addEventListener("pointermove", handlePointerMove);
    container.addEventListener("pointerleave", handlePointerLeave);
    container.addEventListener("wheel", markUserNavigated, { passive: true });
    container.addEventListener("touchstart", markUserNavigated, { passive: true });
    const logicalRangeHandler = (range: LogicalRange | null) => {
      const candleSeriesForRange = candleSeriesRef.current;
      if (!range || !candleSeriesForRange) {
        return;
      }
      const { hasMoreHistory: canLoad, isLoadingHistory: loading, onLoadMoreHistory: loadMore } = historyStateRef.current;
      if (!canLoad || loading || !userNavigatedRef.current) {
        return;
      }
      const barsInfo = candleSeriesForRange.barsInLogicalRange(range);
      if (barsInfo && barsInfo.barsBefore < 50) {
        loadMore();
      }
    };
    const clickHandler = (param: MouseEventParams<Time>) => {
      if (suppressNextClickRef.current) {
        suppressNextClickRef.current = false;
        return;
      }
      if ((!chartClickHandlerRef.current && !lineDrawingModeRef.current) || !param.point) {
        return;
      }
      const anchor = anchorFromClickParam(param, lineDrawingModeRef.current, lineDrawingModeRef.current);
      if (!anchor) {
        console.warn("[KLineChart] click ignored: cannot resolve anchor", {
          hasPoint: Boolean(param.point),
          hasTime: param.time !== undefined,
        });
        lineDrawingHintHandlerRef.current?.("未命中有效 K 线，请在蜡烛附近点击。");
        return;
      }
      handleAnchorSelection(anchor);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(logicalRangeHandler);
    chart.subscribeClick(clickHandler);

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(logicalRangeHandler);
      chart.unsubscribeClick(clickHandler);
      container.removeEventListener("pointerdown", markUserNavigated);
      container.removeEventListener("pointerdown", handlePointerDown);
      container.removeEventListener("pointerup", handlePointerUp);
      container.removeEventListener("pointermove", handlePointerMove);
      container.removeEventListener("pointerleave", handlePointerLeave);
      container.removeEventListener("wheel", markUserNavigated);
      container.removeEventListener("touchstart", markUserNavigated);
      cancelAnimationFrame(resizeFrame);
      observer.disconnect();
      waveMarkers.detach();
      waveMarkersRef.current = null;
      annotationMarkers.detach();
      annotationMarkersRef.current = null;
      backtestMarkers.detach();
      backtestMarkersRef.current = null;
      for (const series of manualLineSeries.values()) {
        chart.removeSeries(series);
      }
      manualLineSeries.clear();
      chart.removeSeries(previewLineSeries);
      previewLineSeriesRef.current = null;
      chart.remove();
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) {
      return;
    }
    const palette = chartPalette(theme);
    chart.applyOptions({
      layout: {
        background: { type: ColorType.Solid, color: palette.background },
        textColor: palette.text,
      },
      grid: {
        vertLines: { color: palette.grid },
        horzLines: { color: palette.grid },
      },
      rightPriceScale: {
        borderColor: palette.border,
      },
      timeScale: {
        borderColor: palette.border,
      },
    });
  }, [theme]);

  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    const volumeSeries = volumeSeriesRef.current;
    const topSeries = topSeriesRef.current;
    const bottomSeries = bottomSeriesRef.current;
    const biSeries = biSeriesRef.current;
    const segmentSeries = segmentSeriesRef.current;
    const zhongshuHighSeries = zhongshuHighSeriesRef.current;
    const zhongshuLowSeries = zhongshuLowSeriesRef.current;
    const waveSeries = waveSeriesRef.current;
    if (
      !candleSeries ||
      !volumeSeries ||
      !topSeries ||
      !bottomSeries ||
      !biSeries ||
      !segmentSeries ||
      !zhongshuHighSeries ||
      !zhongshuLowSeries ||
      !waveSeries
    ) {
      return;
    }
    setRenderError(null);
    const chartBars = normalizeBarsForChart(bars);
    const invalidBars = chartBars.filter(
      (bar) =>
        !Number.isFinite(bar.open) ||
        !Number.isFinite(bar.high) ||
        !Number.isFinite(bar.low) ||
        !Number.isFinite(bar.close) ||
        !isValidChartTime(toChartTime(bar.trade_date)),
    );
    const validBars = invalidBars.length > 0 ? chartBars.filter((bar) => !invalidBars.includes(bar)) : chartBars;
    const highValues = validBars.map((bar) => bar.high);
    const lowValues = validBars.map((bar) => bar.low);
    const minLow = lowValues.length > 0 ? Math.min(...lowValues) : null;
    const maxHigh = highValues.length > 0 ? Math.max(...highValues) : null;
    const duplicateCount = chartBars.length - validBars.length;
    const containerWidth = containerRef.current?.clientWidth ?? 0;
    const containerHeight = containerRef.current?.clientHeight ?? 0;
    chartBarsRef.current = validBars;
    console.info("[KLineChart] render-input", {
      bars: bars.length,
      chartBars: chartBars.length,
      validBars: validBars.length,
      invalidBars: invalidBars.length,
      dupDropped: duplicateCount,
      first: validBars[0]?.trade_date ?? null,
      last: validBars.at(-1)?.trade_date ?? null,
      minLow,
      maxHigh,
      containerWidth,
      containerHeight,
      timeframeHint: validBars[0]?.timeframe ?? null,
    });
    const candles: CandlestickData[] = validBars.map((bar) => ({
      time: toChartTime(bar.trade_date),
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));
    const volumes: HistogramData[] = validBars.map((bar) => ({
      time: toChartTime(bar.trade_date),
      value: bar.volume,
      color: bar.close >= bar.open ? "rgba(211, 47, 47, 0.34)" : "rgba(27, 143, 90, 0.34)",
    }));
    try {
      candleSeries.setData(candles);
      volumeSeries.setData(layers.volume ? volumes : []);
      candleSeries.priceScale().applyOptions({ autoScale: true, mode: 0 });
      chartRef.current?.applyOptions({
        rightPriceScale: {
          autoScale: true,
          mode: 0,
        },
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error("[KLineChart] setData failed", {
        message,
        bars: bars.length,
        chartBars: chartBars.length,
        validBars: validBars.length,
        invalidBars: invalidBars.length,
        first: validBars[0]?.trade_date ?? null,
        last: validBars.at(-1)?.trade_date ?? null,
      });
      setRenderError(message);
      return;
    }

    const topPoints: LineData[] = [];
    const bottomPoints: LineData[] = [];
    for (const point of analysis?.fractals ?? []) {
      const item = {
        time: toChartTime(point.trade_date),
        value: point.price,
      };
      if (point.kind === "top") {
        topPoints.push(item);
      } else {
        bottomPoints.push(item);
      }
    }
    topSeries.setData(layers.fractals ? normalizeLineData(topPoints) : []);
    bottomSeries.setData(layers.fractals ? normalizeLineData(bottomPoints) : []);
    biSeries.setData(layers.bi ? buildBiLineData(analysis) : []);
    segmentSeries.setData(layers.segments ? buildSegmentLineData(analysis) : []);
    zhongshuHighSeries.setData(layers.zhongshu ? buildZhongshuBoundaryData(analysis, "high") : []);
    zhongshuLowSeries.setData(layers.zhongshu ? buildZhongshuBoundaryData(analysis, "low") : []);
    waveSeries.setData(
      layers.wave
        ? normalizeLineData(
            (waveAnalysis?.pivots ?? []).map((point) => ({
              time: toChartTime(point.trade_date),
              value: point.price,
            })),
          )
        : [],
    );
    waveMarkersRef.current?.setMarkers(layers.wave ? buildWaveMarkers(waveAnalysis) : []);
  }, [bars, analysis, waveAnalysis, layers, theme]);

  useEffect(() => {
    const annotationMarkers = annotationMarkersRef.current;
    if (!annotationMarkers) {
      return;
    }
    annotationMarkers.setMarkers(layers.annotations ? buildAnnotationMarkers(annotations, bars) : []);
  }, [annotations, bars, layers.annotations]);

  useEffect(() => {
    const backtestMarkers = backtestMarkersRef.current;
    if (!backtestMarkers) {
      return;
    }
    backtestMarkers.setMarkers(layers.backtest ? buildBacktestMarkers(backtestTrades) : []);
  }, [backtestTrades, layers.backtest]);

  useEffect(() => {
    const previewLineSeries = previewLineSeriesRef.current;
    if (!previewLineSeries) {
      return;
    }
    previewLineSeries.applyOptions({
      color: toPreviewLineColor(manualLineColor),
      lineWidth: normalizeLineWidth(manualLineWidth),
    });
  }, [manualLineColor, manualLineWidth]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) {
      return;
    }
    const lineColor = normalizeLineColor(manualLineColor);
    const lineWidth = normalizeLineWidth(manualLineWidth);
    const seriesMap = manualLineSeriesRef.current;
    const activeIds = new Set(manualLines.map((line) => line.id));
    for (const [id, series] of seriesMap.entries()) {
      if (!activeIds.has(id)) {
        chart.removeSeries(series);
        seriesMap.delete(id);
      }
    }
    for (const line of manualLines) {
      const existing = seriesMap.get(line.id);
      const series =
        existing ??
        chart.addSeries(LineSeries, {
          color: lineColor,
          lineWidth,
          priceLineVisible: false,
          lastValueVisible: false,
        });
      if (!existing) {
        seriesMap.set(line.id, series);
      } else {
        series.applyOptions({
          color: lineColor,
          lineWidth,
        });
      }
      const first = {
        time: toChartTime(line.start.tradeDate),
        value: line.start.price,
      };
      const second = {
        time: toChartTime(line.end.tradeDate),
        value: line.end.price,
      };
      const ordered =
        chartTimeOrder(first.time) <= chartTimeOrder(second.time)
          ? [first, second]
          : [second, first];
      console.info("[KLineChart] line-series-update", {
        id: line.id,
        start: line.start,
        end: line.end,
      });
      series.setData(ordered);
    }
  }, [manualLines, manualLineColor, manualLineWidth]);

  useEffect(() => {
    if (bars.length > 0 && fittedTokenRef.current !== fitContentToken) {
      userNavigatedRef.current = false;
      candleSeriesRef.current?.priceScale().applyOptions({ autoScale: true, mode: 0 });
      chartRef.current?.applyOptions({
        rightPriceScale: {
          autoScale: true,
          mode: 0,
        },
      });
      chartRef.current?.timeScale().fitContent();
      fittedTokenRef.current = fitContentToken;
    }
  }, [fitContentToken, bars.length]);

  return (
    <div className="chart-frame">
      <div className={lineDrawingMode ? "kline-chart line-drawing-mode" : "kline-chart"} ref={containerRef} />
      {bars.length === 0 && (
        <div className="empty-chart">
          <strong>暂无 K 线数据</strong>
          <span>{emptyMessage}</span>
        </div>
      )}
      {renderError && (
        <div className="chart-error-inline">
          渲染错误：{renderError}
        </div>
      )}
    </div>
  );
});

function toChartTime(value: string): Time {
  if (value.includes("T")) {
    return Math.floor(new Date(value).getTime() / 1000) as Time;
  }
  const [yearPart, monthPart, dayPart] = value.split("-");
  const year = Number(yearPart);
  const month = Number(monthPart);
  const day = Number(dayPart);
  if (Number.isInteger(year) && Number.isInteger(month) && Number.isInteger(day)) {
    return { year, month, day } as BusinessDay;
  }
  return value;
}

function chartTimeToString(time: Time): string {
  if (typeof time === "number") {
    const value = new Date(time * 1000);
    return `${value.getUTCFullYear()}-${padTimePart(value.getUTCMonth() + 1)}-${padTimePart(value.getUTCDate())}T${padTimePart(value.getUTCHours())}:${padTimePart(value.getUTCMinutes())}`;
  }
  if (typeof time === "string") {
    return time;
  }
  return `${time.year}-${padTimePart(time.month)}-${padTimePart(time.day)}`;
}

function padTimePart(value: number): string {
  return String(value).padStart(2, "0");
}

function normalizeBarsForChart(bars: BarRecord[]): BarRecord[] {
  const byTime = new Map<string, BarRecord>();
  for (const bar of bars) {
    byTime.set(chartTimeKey(toChartTime(bar.trade_date)), bar);
  }
  return Array.from(byTime.values()).sort((left, right) => chartTimeOrder(toChartTime(left.trade_date)) - chartTimeOrder(toChartTime(right.trade_date)));
}

function normalizeLineData(points: LineData[]): LineData[] {
  const byTime = new Map<string, LineData>();
  for (const point of points) {
    byTime.set(chartTimeKey(point.time), point);
  }
  return Array.from(byTime.values()).sort((left, right) => chartTimeOrder(left.time) - chartTimeOrder(right.time));
}

function buildWaveMarkers(waveAnalysis: WaveAnalysis | null): SeriesMarker<Time>[] {
  return (waveAnalysis?.pivots ?? []).map((point) => ({
    id: `wave-${point.wave_no}`,
    time: toChartTime(point.trade_date),
    position: point.kind === "bottom" ? "belowBar" : "aboveBar",
    shape: point.kind === "bottom" ? "arrowUp" : "arrowDown",
    color: "#6750a4",
    text: `W${point.wave_no}`,
    size: 0.8,
  }));
}

function buildBiLineData(analysis: ChanAnalysis | null): LineData[] {
  const points = new Map<string, LineData>();
  for (const segment of analysis?.bis ?? []) {
    points.set(`${segment.start_trade_date}:${segment.start_price}`, {
      time: toChartTime(segment.start_trade_date),
      value: segment.start_price,
    });
    points.set(`${segment.end_trade_date}:${segment.end_price}`, {
      time: toChartTime(segment.end_trade_date),
      value: segment.end_price,
    });
  }
  return normalizeLineData(Array.from(points.values()));
}

function buildSegmentLineData(analysis: ChanAnalysis | null): LineData[] {
  const points = new Map<string, LineData>();
  for (const segment of analysis?.segments ?? []) {
    points.set(`${segment.start_trade_date}:${segment.start_price}`, {
      time: toChartTime(segment.start_trade_date),
      value: segment.start_price,
    });
    points.set(`${segment.end_trade_date}:${segment.end_price}`, {
      time: toChartTime(segment.end_trade_date),
      value: segment.end_price,
    });
  }
  return normalizeLineData(Array.from(points.values()));
}

function buildZhongshuBoundaryData(analysis: ChanAnalysis | null, boundary: "high" | "low"): LineData[] {
  const points = new Map<string, LineData>();
  for (const zone of analysis?.zhongshu ?? []) {
    const value = zone[boundary];
    points.set(`${zone.start_trade_date}:${value}`, {
      time: toChartTime(zone.start_trade_date),
      value,
    });
    points.set(`${zone.end_trade_date}:${value}`, {
      time: toChartTime(zone.end_trade_date),
      value,
    });
  }
  return normalizeLineData(Array.from(points.values()));
}

function buildAnnotationMarkers(annotations: AnnotationRecord[], bars: BarRecord[]): SeriesMarker<Time>[] {
  const fallbackDate = bars.at(-1)?.trade_date ?? null;
  if (!fallbackDate) {
    return [];
  }
  const availableTimes = new Set(bars.map((bar) => bar.trade_date));
  return annotations
    .filter((annotation) => annotation.overlay_type !== "wave" && annotation.overlay_type !== "chan" && annotation.overlay_type !== "review_note")
    .map((annotation) => {
      const anchor = annotationAnchor(annotation);
      const tradeDate = anchor && availableTimes.has(anchor) ? anchor : fallbackDate;
      const price = annotationPrice(annotation);
      const baseMarker = {
        id: annotation.id,
        time: toChartTime(tradeDate),
        shape: "circle" as const,
        color: annotation.payload.confirmed === true ? "#146c43" : "#6750a4",
        text: markerText(annotation),
        size: annotation.payload.locked === true ? 1.2 : 1,
      };
      if (price === null) {
        return {
          ...baseMarker,
          position: "aboveBar" as const,
        };
      }
      return {
        ...baseMarker,
        position: "atPriceTop" as const,
        price,
      };
    })
    .sort((left, right) => chartTimeOrder(left.time) - chartTimeOrder(right.time));
}

function buildBacktestMarkers(trades: BacktestTrade[]): SeriesMarker<Time>[] {
  return trades
    .flatMap((trade) => [
      {
        id: `backtest-entry-${trade.index}`,
        time: toChartTime(trade.entry_trade_date),
        position: "atPriceBottom" as const,
        price: trade.entry_price,
        shape: "arrowUp" as const,
        color: "#0b6bcb",
        text: `买 #${trade.index}`,
        size: 1.1,
      },
      {
        id: `backtest-exit-${trade.index}`,
        time: toChartTime(trade.exit_trade_date),
        position: "atPriceTop" as const,
        price: trade.exit_price,
        shape: "arrowDown" as const,
        color: trade.return_pct >= 0 ? "#146c43" : "#ba1a1a",
        text: `卖 #${trade.index} ${formatMarkerReturn(trade.return_pct)}`,
        size: 1.1,
      },
    ])
    .sort((left, right) => chartTimeOrder(left.time) - chartTimeOrder(right.time));
}

function formatMarkerReturn(value: number): string {
  if (!Number.isFinite(value)) {
    return "";
  }
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(1)}%`;
}

function annotationAnchor(annotation: AnnotationRecord): string | null {
  const value = annotation.payload.trade_date ?? annotation.payload.time ?? annotation.payload.date;
  return typeof value === "string" && value.length > 0 ? value : null;
}

function markerText(annotation: AnnotationRecord): string {
  const note = String(annotation.payload.note ?? "标注");
  const prefix = annotation.payload.locked === true ? "锁定" : "标注";
  return `${prefix}: ${note.length > 18 ? `${note.slice(0, 18)}...` : note}`;
}

function annotationPrice(annotation: AnnotationRecord): number | null {
  const value = annotation.payload.price;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function chartTimeOrder(time: Time): number {
  if (typeof time === "number") {
    return time;
  }
  if (typeof time === "string") {
    return new Date(time).getTime();
  }
  return new Date(`${time.year}-${time.month}-${time.day}`).getTime();
}

function chartTimeKey(time: Time): string {
  if (typeof time === "number" || typeof time === "string") {
    return String(time);
  }
  return `${time.year}-${padTimePart(time.month)}-${padTimePart(time.day)}`;
}

function formatCrosshairTimeLabel(time: Time): string {
  if (typeof time === "number") {
    const value = new Date(time * 1000);
    return `${value.getFullYear()}-${padTimePart(value.getMonth() + 1)}-${padTimePart(value.getDate())} ${padTimePart(value.getHours())}:${padTimePart(value.getMinutes())}`;
  }
  if (typeof time === "string") {
    if (!time.includes("T")) {
      return time;
    }
    const value = new Date(time);
    if (Number.isNaN(value.getTime())) {
      return time.replace("T", " ").slice(0, 16);
    }
    return `${value.getFullYear()}-${padTimePart(value.getMonth() + 1)}-${padTimePart(value.getDate())} ${padTimePart(value.getHours())}:${padTimePart(value.getMinutes())}`;
  }
  return `${time.year}-${padTimePart(time.month)}-${padTimePart(time.day)}`;
}

function isValidChartTime(time: Time): boolean {
  if (typeof time === "number") {
    return Number.isFinite(time) && time > 0;
  }
  if (typeof time === "string") {
    return time.length > 0;
  }
  return Number.isInteger(time.year) && Number.isInteger(time.month) && Number.isInteger(time.day);
}

function normalizeLineColor(value: string): string {
  const normalized = value.trim();
  return /^#[0-9a-fA-F]{6}$/.test(normalized) ? normalized.toLowerCase() : "#ff8f00";
}

function normalizeLineWidth(value: number): ManualLineWidth {
  if (!Number.isFinite(value)) {
    return 2;
  }
  const rounded = Math.max(1, Math.min(4, Math.round(value)));
  if (rounded === 1 || rounded === 2 || rounded === 3 || rounded === 4) {
    return rounded;
  }
  return 2;
}

function toPreviewLineColor(color: string): string {
  const normalized = normalizeLineColor(color);
  const r = Number.parseInt(normalized.slice(1, 3), 16);
  const g = Number.parseInt(normalized.slice(3, 5), 16);
  const b = Number.parseInt(normalized.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, 0.72)`;
}

function chartPalette(theme: "light" | "dark") {
  if (theme === "dark") {
    return {
      background: "#141218",
      text: "#e6e0e9",
      grid: "#2f2a35",
      border: "#49454f",
    };
  }
  return {
    background: "#fffbff",
    text: "#1d1b20",
    grid: "#ece6f0",
    border: "#cac4d0",
  };
}
