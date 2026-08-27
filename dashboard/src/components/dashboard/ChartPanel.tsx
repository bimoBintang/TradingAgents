import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { 
  createChart, 
  ColorType, 
  CrosshairMode, 
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  LineStyle,
} from 'lightweight-charts';
import type { ISeriesApi, IPriceLine, LineWidth } from 'lightweight-charts';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { Select } from '../ui/Select';
import {
  useOHLCV, useFibonacci,
  useFVG, useIFVG, useLiquiditySweeps,
  useOrderFlow, useAnchoredVWAP, useVolumeProfile,
} from '../../hooks/useApi';
import { usePatternOverlay } from '../../hooks/usePatternOverlay';
import type { PatternResponse } from '../../types/patterns';
import { Loader2, Sparkles, X } from 'lucide-react';

// ── Ticker Display Names ─────────────────────────────────────────────

const getTickerName = (ticker: string) => {
  if (ticker === 'BTC-USD') return 'Bitcoin';
  if (ticker === 'ETH-USD') return 'Ethereum';
  if (ticker === 'SOL-USD') return 'Solana';
  if (ticker === 'TSLA') return 'Tesla Inc.';
  return 'NVIDIA Corp.';
};

// Normalize date strings for Lightweight Charts:
// Daily chart expects 'yyyy-mm-dd', strip any time/timezone suffix.
const normalizeTime = (d: string) => d.split('T')[0];

// ── SMA / BB / RSI calculation from OHLCV candles ────────────────────

const computeIndicators = (candles: { time: string; open: number; high: number; low: number; close: number }[]) => {
  const sma20: { time: string; value: number }[] = [];
  const sma50: { time: string; value: number }[] = [];
  const bbUpper: { time: string; value: number }[] = [];
  const bbLower: { time: string; value: number }[] = [];
  const rsiData: { time: string; value: number }[] = [];
  const gains: number[] = [];
  const losses: number[] = [];

  for (let i = 0; i < candles.length; i++) {
    const time = candles[i].time;
    if (i >= 19) {
      const window20 = candles.slice(i - 19, i + 1).map(c => c.close);
      const sum20 = window20.reduce((acc, val) => acc + val, 0);
      const mean20 = sum20 / 20;
      sma20.push({ time, value: mean20 });
      const variance = window20.reduce((acc, val) => acc + Math.pow(val - mean20, 2), 0) / 20;
      const stdDev = Math.sqrt(variance);
      bbUpper.push({ time, value: mean20 + (2 * stdDev) });
      bbLower.push({ time, value: mean20 - (2 * stdDev) });
    }
    if (i >= 49) {
      const sum50 = candles.slice(i - 49, i + 1).reduce((acc, val) => acc + val.close, 0);
      sma50.push({ time, value: sum50 / 50 });
    }
    if (i > 0) {
      const change = candles[i].close - candles[i - 1].close;
      gains.push(Math.max(0, change));
      losses.push(Math.max(0, -change));
    }
    if (i >= 14) {
      const rsWindowGains = gains.slice(i - 14, i);
      const rsWindowLosses = losses.slice(i - 14, i);
      const avgGain = rsWindowGains.reduce((a, b) => a + b, 0) / 14;
      const avgLoss = rsWindowLosses.reduce((a, b) => a + b, 0) / 14;
      let rsi = 100;
      if (avgLoss !== 0) { rsi = 100 - (100 / (1 + avgGain / avgLoss)); }
      rsiData.push({ time, value: rsi });
    }
  }
  return { sma20, sma50, bbUpper, bbLower, rsiData };
};

// ── Fibonacci Price Line Config ──────────────────────────────────────

const FIB_LINE_STYLES: Record<string, { color: string; lineWidth: number; lineStyle: number }> = {
  '0.0%':   { color: '#ffffff', lineWidth: 1, lineStyle: LineStyle.Solid },
  '23.6%':  { color: '#22d3ee', lineWidth: 1, lineStyle: LineStyle.Dashed },
  '38.2%':  { color: '#22d3ee', lineWidth: 1, lineStyle: LineStyle.Dashed },
  '50.0%':  { color: '#f59e0b', lineWidth: 2, lineStyle: LineStyle.Dashed },
  '61.8%':  { color: '#f97316', lineWidth: 2, lineStyle: LineStyle.Solid },
  '78.6%':  { color: '#ef4444', lineWidth: 1, lineStyle: LineStyle.Dashed },
  '100.0%': { color: '#ffffff', lineWidth: 1, lineStyle: LineStyle.Solid },
  '127.2%': { color: '#a855f7', lineWidth: 1, lineStyle: LineStyle.Dotted },
  '161.8%': { color: '#a855f7', lineWidth: 1, lineStyle: LineStyle.Dotted },
  '261.8%': { color: '#a855f7', lineWidth: 1, lineStyle: LineStyle.Dotted },
};

// ── Indicator Options ────────────────────────────────────────────────

const INDICATOR_OPTIONS = [
  { label: 'Show All Indicators', value: 'all' },
  { label: 'Moving Averages (SMA)', value: 'sma' },
  { label: 'Bollinger Bands', value: 'bb' },
  { label: 'RSI Only', value: 'rsi' },
  { label: 'Fibonacci Levels', value: 'fib' },
  { label: 'Fair Value Gaps', value: 'fvg' },
  { label: 'Liquidity Sweeps', value: 'sweep' },
  { label: 'Order Flow Delta', value: 'flow' },
  { label: 'Anchored VWAP', value: 'vwap' },
  { label: 'Volume Profile', value: 'vpro' },
  { label: 'SMC Suite (All)', value: 'smc' },
  { label: 'Clear Chart (Price Only)', value: 'none' },
];

// ── ChartPanel Component ─────────────────────────────────────────────

/**
 * Imperative controls exposed for remote/MCP-driven control (Fase 7 —
 * see mcp_server/tools_chart.py + api/chart_control.py). `ticker` is
 * deliberately NOT settable here — it's owned by the parent
 * (OverviewPage's activeTicker), which is the one thing set_chart_view
 * changes outside of this ref.
 */
export interface ChartPanelHandle {
  setTimeframe: (tf: string) => void;
  setActiveIndicator: (indicator: string) => void;
  triggerPatternDetection: () => void;
  highlightPriceLevel: (price: number, label: string, color?: string) => void;
  clearAiHighlights: () => void;
}

interface ChartPanelProps {
  ticker: string;
  /** Fires whenever ticker/timeframe/activeIndicator changes, so a
   * parent can report the combined state over /ws/chart-control. */
  onStateChange?: (state: { ticker: string; timeframe: string; activeIndicator: string }) => void;
}

export const ChartPanel = forwardRef<ChartPanelHandle, ChartPanelProps>(({ ticker, onStateChange }, ref) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
  const seriesRef = useRef<Record<string, any>>({});

  // Fibonacci refs
  const fibLinesRef = useRef<IPriceLine[]>([]);

  // SMC refs
  const fvgLinesRef = useRef<IPriceLine[]>([]);
  const ifvgLinesRef = useRef<IPriceLine[]>([]);
  const sweepLinesRef = useRef<IPriceLine[]>([]);
  const flowSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const vwapSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const vproLinesRef = useRef<IPriceLine[]>([]);
  // AI-drawn price-line highlights (Fase 7's highlight_price_level MCP
  // tool) — kept separate from the overlay refs above so they persist
  // independently of `activeIndicator` and can be cleared on their own.
  const aiHighlightLinesRef = useRef<IPriceLine[]>([]);

  const [activeIndicator, setActiveIndicator] = useState('all');
  const [timeframe, setTimeframe] = useState('1D');

  // Pattern overlay state
  const [isDetecting, setIsDetecting] = useState(false);
  const [hasPatterns, setHasPatterns] = useState(false);
  const [patternError, setPatternError] = useState<string | null>(null);
  const { drawPatterns, clearPatterns } = usePatternOverlay(chartRef);

  const intervalMap: Record<string, string> = {
    '1D': '1d', '1H': '1h', '30M': '30m', '15M': '15m', '5M': '5m',
  };

  // Data hooks
  const { data: ohlcv, loading: ohlcvLoading } = useOHLCV(ticker, intervalMap[timeframe] ?? '1d');
  const { data: fibData } = useFibonacci(ticker);
  const { data: fvgData } = useFVG(ticker);
  const { data: ifvgData } = useIFVG(ticker);
  const { data: sweepData } = useLiquiditySweeps(ticker);
  const { data: flowData } = useOrderFlow(ticker);
  const { data: vwapData } = useAnchoredVWAP(ticker);
  const { data: vproData } = useVolumeProfile(ticker);

  // Helper: should show a particular overlay
  // 'all' = traditional only (SMA/BB/RSI/Fib). 'smc' = all 6 SMC overlays.
  const TRADITIONAL = ['sma', 'bb', 'rsi', 'fib'];
  const SMC_KEYS = ['fvg', 'sweep', 'flow', 'vwap', 'vpro'];
  const shouldShow = (key: string) => {
    if (activeIndicator === 'none') return false;
    if (activeIndicator === 'all') return TRADITIONAL.includes(key);
    if (activeIndicator === 'smc') return SMC_KEYS.includes(key);
    return activeIndicator === key;
  };

  // 1. Initialize Chart (Run ONCE)
  useEffect(() => {
    if (!chartContainerRef.current) return;
    
    const chart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: 'rgba(255, 255, 255, 0.03)' }, horzLines: { color: 'rgba(255, 255, 255, 0.03)' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: 'rgba(255, 255, 255, 0.1)', autoScale: true },
      timeScale: { borderColor: 'rgba(255, 255, 255, 0.1)', timeVisible: true },
      height: 400,
    });
    chartRef.current = chart;
    chart.priceScale('right').applyOptions({ scaleMargins: { top: 0.1, bottom: 0.3 } });

    // Core series
    seriesRef.current.candlestick = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981', downColor: '#ef4444', borderVisible: false,
      wickUpColor: '#10b981', wickDownColor: '#ef4444',
    });
    seriesRef.current.volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' }, priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({ autoScale: true, scaleMargins: { top: 0.6, bottom: 0.3 } });

    // Traditional indicators
    seriesRef.current.sma20 = chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 2, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false });
    seriesRef.current.sma50 = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 2, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false });
    seriesRef.current.bbUpper = chart.addSeries(LineSeries, { color: 'rgba(167, 139, 250, 0.6)', lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false });
    seriesRef.current.bbLower = chart.addSeries(LineSeries, { color: 'rgba(167, 139, 250, 0.6)', lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false });
    seriesRef.current.rsi = chart.addSeries(LineSeries, { color: '#d946ef', lineWidth: 2, crosshairMarkerVisible: true, priceScaleId: 'rsi', priceLineVisible: false });
    seriesRef.current.rsiUpper = chart.addSeries(LineSeries, { color: 'rgba(255, 255, 255, 0.2)', lineWidth: 1, lineStyle: 2, priceScaleId: 'rsi', lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    seriesRef.current.rsiLower = chart.addSeries(LineSeries, { color: 'rgba(255, 255, 255, 0.2)', lineWidth: 1, lineStyle: 2, priceScaleId: 'rsi', lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    chart.priceScale('rsi').applyOptions({ autoScale: true, borderColor: 'rgba(255, 255, 255, 0.1)', scaleMargins: { top: 0.8, bottom: 0 } });

    // SMC series (created once, data set later)
    seriesRef.current.orderFlow = chart.addSeries(HistogramSeries, {
      priceScaleId: 'orderflow', priceFormat: { type: 'volume' },
    });
    chart.priceScale('orderflow').applyOptions({ autoScale: true, scaleMargins: { top: 0.7, bottom: 0.15 } });
    flowSeriesRef.current = seriesRef.current.orderFlow;

    seriesRef.current.vwapLine = chart.addSeries(LineSeries, {
      color: '#8b5cf6', lineWidth: 2, crosshairMarkerVisible: false,
      lastValueVisible: true, priceLineVisible: false,
    });
    vwapSeriesRef.current = seriesRef.current.vwapLine;

    const handleResize = () => {
      if (chartContainerRef.current) chart.applyOptions({ width: chartContainerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);
    return () => { window.removeEventListener('resize', handleResize); chart.remove(); chartRef.current = null; };
  }, []);
  
  // 2. Load OHLCV Data
  useEffect(() => {
    if (!chartRef.current || !seriesRef.current.candlestick || !ohlcv || ohlcv.candles.length === 0) return;
    const candles = ohlcv.candles;
    // Normalize time and deduplicate (timezone edge can create duplicate days)
    const seen = new Set<string>();
    const normalized = candles
      .map((c: any) => ({ ...c, time: normalizeTime(c.time) }))
      .filter((c: any) => {
        if (seen.has(c.time)) return false;
        seen.add(c.time);
        return true;
      });
    seriesRef.current.candlestick.setData(normalized);
    seriesRef.current.volume.setData(normalized.map((c: any) => ({
      time: c.time, value: c.volume,
      color: c.close >= c.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
    })));
    const indicators = computeIndicators(normalized);
    seriesRef.current.sma20.setData(indicators.sma20);
    seriesRef.current.sma50.setData(indicators.sma50);
    seriesRef.current.bbUpper.setData(indicators.bbUpper);
    seriesRef.current.bbLower.setData(indicators.bbLower);
    seriesRef.current.rsi.setData(indicators.rsiData);
    seriesRef.current.rsiUpper.setData(normalized.map((c: any) => ({ time: c.time, value: 70 })));
    seriesRef.current.rsiLower.setData(normalized.map((c: any) => ({ time: c.time, value: 30 })));
    chartRef.current.timeScale().fitContent();
  }, [ohlcv]);

  // 3. Fibonacci Price Lines
  useEffect(() => {
    if (!seriesRef.current.candlestick) return;
    const cs = seriesRef.current.candlestick;
    fibLinesRef.current.forEach(l => cs.removePriceLine(l));
    fibLinesRef.current = [];
    if (!shouldShow('fib') || !fibData?.levels) return;
    for (const level of fibData.levels) {
      const style = FIB_LINE_STYLES[level.label] ?? { color: '#64748b', lineWidth: 1, lineStyle: LineStyle.Dotted };
      fibLinesRef.current.push(cs.createPriceLine({
        price: level.price, color: style.color, lineWidth: style.lineWidth as LineWidth,
        lineStyle: style.lineStyle, axisLabelVisible: true,
        title: `${level.label} (${level.type === 'extension' ? 'EXT' : 'RET'})`,
      }));
    }
  }, [fibData, activeIndicator]);

  // 4. FVG Price Lines — max 5 nearest unfilled zones
  // LIMITATION: No native zone fill in LC v4. Rendering as boundary lines.
  useEffect(() => {
    if (!seriesRef.current.candlestick) return;
    const cs = seriesRef.current.candlestick;
    fvgLinesRef.current.forEach(l => cs.removePriceLine(l));
    fvgLinesRef.current = [];
    if (!shouldShow('fvg') || !fvgData?.fvgs) return;
    const unfilled = fvgData.fvgs.filter(f => !f.is_filled);
    // Sort by proximity to current price (use midpoint of gap)
    const lastPrice = ohlcv?.candles?.length ? ohlcv.candles[ohlcv.candles.length - 1].close : 0;
    const sorted = [...unfilled].sort((a, b) => {
      const midA = (a.top + a.bottom) / 2;
      const midB = (b.top + b.bottom) / 2;
      return Math.abs(midA - lastPrice) - Math.abs(midB - lastPrice);
    });
    for (const fvg of sorted.slice(0, 5)) {
      const color = fvg.type === 'bullish' ? '#10b981' : '#ef4444';
      const label = fvg.type === 'bullish' ? 'FVG↑' : 'FVG↓';
      fvgLinesRef.current.push(cs.createPriceLine({
        price: fvg.top, color, lineWidth: 1 as LineWidth, lineStyle: LineStyle.Dashed,
        axisLabelVisible: false, title: label,
      }));
      fvgLinesRef.current.push(cs.createPriceLine({
        price: fvg.bottom, color, lineWidth: 1 as LineWidth, lineStyle: LineStyle.Dashed,
        axisLabelVisible: false, title: '',
      }));
    }
  }, [fvgData, activeIndicator, ohlcv]);

  // 5. IFVG Price Lines — max 3 most recent (amber)
  useEffect(() => {
    if (!seriesRef.current.candlestick) return;
    const cs = seriesRef.current.candlestick;
    ifvgLinesRef.current.forEach(l => cs.removePriceLine(l));
    ifvgLinesRef.current = [];
    if (!shouldShow('fvg') || !ifvgData?.ifvgs) return;
    for (const ifvg of ifvgData.ifvgs.slice(-3)) {
      ifvgLinesRef.current.push(cs.createPriceLine({
        price: ifvg.top, color: '#f59e0b', lineWidth: 1 as LineWidth, lineStyle: LineStyle.Dotted,
        axisLabelVisible: false, title: 'IFVG',
      }));
      ifvgLinesRef.current.push(cs.createPriceLine({
        price: ifvg.bottom, color: '#f59e0b', lineWidth: 1 as LineWidth, lineStyle: LineStyle.Dotted,
        axisLabelVisible: false, title: '',
      }));
    }
  }, [ifvgData, activeIndicator]);

  // 6. Liquidity Sweep Price Lines — max 5 most recent, no axis label
  useEffect(() => {
    if (!seriesRef.current.candlestick) return;
    const cs = seriesRef.current.candlestick;
    sweepLinesRef.current.forEach(l => cs.removePriceLine(l));
    sweepLinesRef.current = [];
    if (!shouldShow('sweep') || !sweepData?.sweeps) return;
    for (const sweep of sweepData.sweeps.slice(-5)) {
      const arrow = sweep.type === 'buy_side' ? '↑' : '↓';
      sweepLinesRef.current.push(cs.createPriceLine({
        price: sweep.sweep_price, color: '#ec4899', lineWidth: 2 as LineWidth,
        lineStyle: LineStyle.Solid, axisLabelVisible: false,
        title: `Sweep ${arrow}`,
      }));
    }
  }, [sweepData, activeIndicator]);

  // 7. Order Flow Delta Histogram
  useEffect(() => {
    if (!flowSeriesRef.current) return;
    const show = shouldShow('flow');
    flowSeriesRef.current.applyOptions({ visible: show });
    if (!show || !flowData?.flow) {
      flowSeriesRef.current.setData([]);
      return;
    }
    flowSeriesRef.current.setData(flowData.flow.map(f => ({
      time: normalizeTime(f.date),
      value: Math.abs(f.delta),
      color: f.delta >= 0 ? 'rgba(16, 185, 129, 0.6)' : 'rgba(239, 68, 68, 0.6)',
    })));
  }, [flowData, activeIndicator]);

  // 8. Anchored VWAP Line
  useEffect(() => {
    if (!vwapSeriesRef.current) return;
    const show = shouldShow('vwap');
    vwapSeriesRef.current.applyOptions({ visible: show });
    if (!show || !vwapData?.vwap_values) {
      vwapSeriesRef.current.setData([]);
      return;
    }
    vwapSeriesRef.current.setData(vwapData.vwap_values.map(v => ({
      time: normalizeTime(v.date), value: v.vwap,
    })));
  }, [vwapData, activeIndicator]);

  // 9. Volume Profile — POC, VAH, VAL as price lines
  useEffect(() => {
    if (!seriesRef.current.candlestick) return;
    const cs = seriesRef.current.candlestick;
    vproLinesRef.current.forEach(l => cs.removePriceLine(l));
    vproLinesRef.current = [];
    if (!shouldShow('vpro') || !vproData) return;
    vproLinesRef.current.push(cs.createPriceLine({
      price: vproData.poc_price, color: '#3b82f6', lineWidth: 2 as LineWidth,
      lineStyle: LineStyle.Solid, axisLabelVisible: true, title: `POC $${vproData.poc_price.toFixed(2)}`,
    }));
    vproLinesRef.current.push(cs.createPriceLine({
      price: vproData.vah_price, color: '#60a5fa', lineWidth: 1 as LineWidth,
      lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `VAH $${vproData.vah_price.toFixed(2)}`,
    }));
    vproLinesRef.current.push(cs.createPriceLine({
      price: vproData.val_price, color: '#60a5fa', lineWidth: 1 as LineWidth,
      lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `VAL $${vproData.val_price.toFixed(2)}`,
    }));
  }, [vproData, activeIndicator]);

  // 10. Traditional Indicator Visibility
  useEffect(() => {
    if (!chartRef.current || !seriesRef.current.candlestick) return;
    const r = seriesRef.current;
    const showAll = activeIndicator === 'all';
    r.sma20.applyOptions({ visible: showAll || activeIndicator === 'sma' });
    r.sma50.applyOptions({ visible: showAll || activeIndicator === 'sma' });
    r.bbUpper.applyOptions({ visible: showAll || activeIndicator === 'bb' });
    r.bbLower.applyOptions({ visible: showAll || activeIndicator === 'bb' });
    r.rsi.applyOptions({ visible: showAll || activeIndicator === 'rsi' });
    r.rsiUpper.applyOptions({ visible: showAll || activeIndicator === 'rsi' });
    r.rsiLower.applyOptions({ visible: showAll || activeIndicator === 'rsi' });
  }, [activeIndicator]);

  // 11. Auto-clear patterns AND AI highlights when ticker or timeframe
  // changes — a price level highlighted on AAPL doesn't mean anything
  // once the chart has switched to BTC-USD.
  useEffect(() => {
    clearPatterns();
    setHasPatterns(false);
    setPatternError(null);
    const cs = seriesRef.current.candlestick;
    if (cs) {
      aiHighlightLinesRef.current.forEach(l => cs.removePriceLine(l));
      aiHighlightLinesRef.current = [];
    }
  }, [ticker, timeframe, clearPatterns]);

  // Shared by the "Auto-Detect" button (toggle: detect, or clear if
  // already showing) and the remote/MCP trigger (always re-detect —
  // see triggerPatternDetection in the imperative handle below, which
  // calls this directly rather than through the toggle).
  const detectAndDrawPatterns = async () => {
    setIsDetecting(true);
    setPatternError(null);
    try {
      const res = await fetch(`http://localhost:8000/api/market-data/patterns/${ticker}?timeframe=${intervalMap[timeframe] ?? '1d'}`);
      if (!res.ok) throw new Error(await res.text());
      const data: PatternResponse = await res.json();
      drawPatterns(data.patterns);
      setHasPatterns(data.patterns.length > 0);
      if (data.patterns.length === 0) {
        setPatternError('Tidak ada pola terdeteksi');
        setTimeout(() => setPatternError(null), 3000);
      }
    } catch (e: any) {
      setPatternError(e.message ?? 'Detection failed');
    } finally {
      setIsDetecting(false);
    }
  };

  const handleDetectPatterns = () => {
    if (hasPatterns) {
      clearPatterns();
      setHasPatterns(false);
      return;
    }
    detectAndDrawPatterns();
  };

  // ── Imperative handle (Fase 7 — remote/MCP chart control) ──────────
  useImperativeHandle(ref, () => ({
    setTimeframe: (tf: string) => setTimeframe(tf),
    setActiveIndicator: (indicator: string) => setActiveIndicator(indicator),
    triggerPatternDetection: () => { detectAndDrawPatterns(); },
    highlightPriceLevel: (price: number, label: string, color = '#f59e0b') => {
      const cs = seriesRef.current.candlestick;
      if (!cs) return;
      aiHighlightLinesRef.current.push(cs.createPriceLine({
        price, color, lineWidth: 2 as LineWidth, lineStyle: LineStyle.Solid,
        axisLabelVisible: true, title: `[AI] ${label}`,
      }));
    },
    clearAiHighlights: () => {
      const cs = seriesRef.current.candlestick;
      if (!cs) return;
      aiHighlightLinesRef.current.forEach(l => cs.removePriceLine(l));
      aiHighlightLinesRef.current = [];
    },
  }), []);

  // Report combined chart state up (OverviewPage forwards this over
  // /ws/chart-control) whenever what's displayed changes.
  useEffect(() => {
    onStateChange?.({ ticker, timeframe, activeIndicator });
  }, [ticker, timeframe, activeIndicator, onStateChange]);

  // SMC info badges
  const smcBadges = (
    <div className="flex items-center gap-2 text-[10px] font-bold tracking-wider ml-2">
      {fibData && (shouldShow('fib')) && (
        <span className={fibData.trend_direction === 'bullish' ? 'text-emerald-400' : fibData.trend_direction === 'bearish' ? 'text-rose-400' : 'text-slate-400'}>
          {fibData.trend_direction.toUpperCase()}
        </span>
      )}
      {fibData?.in_golden_zone && shouldShow('fib') && (
        <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30">GOLDEN</span>
      )}
      {flowData?.summary && shouldShow('flow') && (
        <span className={flowData.summary.pressure === 'buying' ? 'text-emerald-400' : flowData.summary.pressure === 'selling' ? 'text-rose-400' : 'text-slate-400'}>
          {flowData.summary.pressure.toUpperCase()}
        </span>
      )}
      {vwapData && shouldShow('vwap') && (
        <span className={vwapData.current_deviation_pct > 0 ? 'text-emerald-400' : 'text-rose-400'}>
          VWAP {vwapData.current_deviation_pct > 0 ? '+' : ''}{vwapData.current_deviation_pct.toFixed(1)}%
        </span>
      )}
      {vproData && shouldShow('vpro') && (
        <span className="text-blue-400">POC ${vproData.poc_price.toFixed(2)}</span>
      )}
    </div>
  );
  
  return (
    <Card className="col-span-12 flex flex-col bg-slate-900/50">
      <CardHeader className="py-4 border-b border-slate-800/50 flex flex-row items-center justify-between">
        <div className="flex items-center gap-6">
          <CardTitle className="text-xl flex items-center gap-3">
            {ticker}
            <span className="text-slate-400 font-normal text-sm">{getTickerName(ticker)}</span>
            {ohlcvLoading && <Loader2 size={14} className="animate-spin text-slate-500" />}
          </CardTitle>
          <div className="flex items-center gap-3">
             <Select options={INDICATOR_OPTIONS} value={activeIndicator} onChange={setActiveIndicator} className="w-48" />
             <div className="flex space-x-3 ml-2 text-[10px] uppercase font-bold tracking-wider">
               {(shouldShow('sma')) && <><span className="text-blue-500">SMA 20</span><span className="text-amber-500">SMA 50</span></>}
               {(shouldShow('bb')) && <span className="text-purple-400">BB(20,2)</span>}
               {(shouldShow('rsi')) && <span className="text-fuchsia-500">RSI(14)</span>}
               {(shouldShow('fib')) && <span className="text-orange-400">FIB</span>}
               {(shouldShow('fvg')) && <span className="text-green-400">FVG</span>}
               {(shouldShow('sweep')) && <span className="text-pink-400">SWEEP</span>}
               {(shouldShow('flow')) && <span className="text-emerald-400">FLOW</span>}
               {(shouldShow('vwap')) && <span className="text-violet-400">VWAP</span>}
               {(shouldShow('vpro')) && <span className="text-blue-400">VPRO</span>}
             </div>
             {smcBadges}
             <button
               onClick={handleDetectPatterns}
               disabled={isDetecting}
               className={`flex items-center gap-1.5 ml-2 px-3 py-1.5 rounded-md text-xs font-bold border transition-all ${
                 hasPatterns
                   ? 'bg-purple-500/20 text-purple-300 border-purple-500/40 hover:bg-purple-500/30'
                   : isDetecting
                     ? 'bg-slate-800/50 text-slate-400 border-slate-700 cursor-not-allowed opacity-60'
                     : 'bg-slate-800/50 text-slate-300 border-slate-700 hover:bg-slate-700 hover:text-white'
               }`}
             >
               {isDetecting ? (
                 <><Loader2 size={13} className="animate-spin" /> Mendeteksi...</>
               ) : hasPatterns ? (
                 <><X size={13} /> Hapus Pola</>
               ) : (
                 <><Sparkles size={13} /> Auto-Detect</>
               )}
             </button>
             {patternError && (
               <span className="text-[10px] text-amber-400 ml-2 animate-pulse">{patternError}</span>
             )}
          </div>
        </div>
        <div className="flex gap-1.5 bg-slate-900 overflow-hidden pl-1 pr-1 py-1 rounded-md border border-slate-800">
          {['1D', '1H', '30M', '15M', '5M'].map(tf => (
            <button key={tf} onClick={() => setTimeframe(tf)}
              className={`px-3 py-1 rounded text-xs font-bold transition-colors ${tf === timeframe ? 'bg-blue-600 text-white shadow-sm' : 'bg-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800'}`}>
              {tf}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div ref={chartContainerRef} className="w-full h-[400px] relative overflow-hidden rounded-b-xl" />
      </CardContent>
    </Card>
  );
});

ChartPanel.displayName = 'ChartPanel';
