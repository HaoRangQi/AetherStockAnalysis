import { useEffect, useRef } from "react";
import {
  CandlestickData,
  ColorType,
  CandlestickSeries,
  HistogramSeries,
  HistogramData,
  IChartApi,
  ISeriesApi,
  LineSeries,
  LineData,
  Time,
  createChart,
} from "lightweight-charts";
import { BarRecord, ChanAnalysis, WaveAnalysis } from "./api";

type Props = {
  bars: BarRecord[];
  analysis: ChanAnalysis | null;
  waveAnalysis: WaveAnalysis | null;
  layers: {
    volume: boolean;
    fractals: boolean;
    wave: boolean;
  };
  theme: "light" | "dark";
  emptyMessage: string;
};

export function KLineChart({ bars, analysis, waveAnalysis, layers, theme, emptyMessage }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const topSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bottomSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const waveSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }
    const palette = chartPalette("light");
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: palette.background },
        textColor: palette.text,
        fontFamily: "Inter, Roboto, system-ui, sans-serif",
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
    const waveSeries = chart.addSeries(LineSeries, {
      color: "#6750a4",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    topSeriesRef.current = topSeries;
    bottomSeriesRef.current = bottomSeries;
    waveSeriesRef.current = waveSeries;

    const observer = new ResizeObserver(() => {
      if (!containerRef.current) {
        return;
      }
      chart.applyOptions({
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
      });
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
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
    const waveSeries = waveSeriesRef.current;
    if (!candleSeries || !volumeSeries || !topSeries || !bottomSeries || !waveSeries) {
      return;
    }
    const candles: CandlestickData[] = bars.map((bar) => ({
      time: toChartTime(bar.trade_date),
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));
    const volumes: HistogramData[] = bars.map((bar) => ({
      time: toChartTime(bar.trade_date),
      value: bar.volume,
      color: bar.close >= bar.open ? "rgba(211, 47, 47, 0.34)" : "rgba(27, 143, 90, 0.34)",
    }));
    candleSeries.setData(candles);
    volumeSeries.setData(layers.volume ? volumes : []);

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
    topSeries.setData(layers.fractals ? topPoints : []);
    bottomSeries.setData(layers.fractals ? bottomPoints : []);
    waveSeries.setData(
      layers.wave
        ? (waveAnalysis?.pivots ?? []).map((point) => ({
            time: toChartTime(point.trade_date),
            value: point.price,
          }))
        : [],
    );
    chartRef.current?.timeScale().fitContent();
  }, [bars, analysis, waveAnalysis, layers]);

  return (
    <div className="chart-frame">
      <div className="kline-chart" ref={containerRef} />
      {bars.length === 0 && (
        <div className="empty-chart">
          <strong>暂无 K 线数据</strong>
          <span>{emptyMessage}</span>
        </div>
      )}
    </div>
  );
}

function toChartTime(value: string): Time {
  if (value.includes("T")) {
    return Math.floor(new Date(value).getTime() / 1000) as Time;
  }
  return value as Time;
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
