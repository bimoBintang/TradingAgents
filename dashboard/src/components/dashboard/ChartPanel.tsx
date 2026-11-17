import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import {
  createChart,
  ColorType,
  CrosshairMode,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  LineStyle,
} from 'lightweight-charts';
import type { IPriceLine, LineWidth, Time } from 'lightweight-charts';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { Select } from '../ui/Select';
import { useOHLCV } from '../../hooks/useApi';
import { useOhlcvWS } from '../../hooks/useWebSocket';
import { Loader2 } from 'lucide-react';

// ── Ticker Display Names ─────────────────────────────────────────────

const getTickerName = (ticker: string) => {
  if (ticker === 'BTC-USD') return 'Bitcoin';
  if (ticker === 'ETH-USD') return 'Ethereum';
  if (ticker === 'SOL-USD') return 'Solana';
  if (ticker === 'TSLA') return 'Tesla Inc.';
  if (ticker === 'NVDA') return 'NVIDIA Corp.';
  return '';
};

// Normalize date strings for Lightweight Charts.
//
// Daily candles: 'yyyy-mm-dd' (strip any time/timezone suffix).
// Intraday candles (1H/30M/15M/5M) MUST keep time-of-day — the backend
// already sends full 'yyyy-mm-ddTHH:MM:SS' for these (api/routers/
// market_data.py), but this used to unconditionally truncate to the date
// portion regardless of timeframe, which collapsed every candle in a day
// onto one point (the dedup pass below then dropped all but the first).
// Lightweight Charts needs a UNIX timestamp (seconds) to place sub-daily
// points correctly, so intraday times are converted rather than truncated.
const normalizeTime = (d: string, intraday: boolean): Time => {
  if (!intraday) return d.split('T')[0] as Time;
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(d) ? d : `${d}Z`; // assume UTC if no offset given
  return Math.floor(new Date(iso).getTime() / 1000) as Time;
};

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

// ── Indicator Options ────────────────────────────────────────────────

const INDICATOR_OPTIONS = [
  { label: 'SMA + Bollinger + RSI', value: 'all' },
  { label: 'Moving Averages (SMA)', value: 'sma' },
  { label: 'Bollinger Bands', value: 'bb' },
  { label: 'RSI Only', value: 'rsi' },
  { label: 'Price Only', value: 'none' },
];

// ── ChartPanel Component ─────────────────────────────────────────────

/**
 * Imperative controls for AI-driven chart control (see mcp_server/tools_chart.py
 * + api/chart_control.py). `ticker` is owned by the parent (OverviewPage).
 */
export interface ChartPanelHandle {
  setTimeframe: (tf: string) => void;
  highlightPriceLevel: (price: number, label: string, color?: string) => void;
  clearAiHighlights: () => void;
}

interface ChartPanelProps {
  ticker: string;
  /** Fires whenever ticker/timeframe/activeIndicator changes (reported over /ws/chart-control). */
  onStateChange?: (state: { ticker: string; timeframe: string; activeIndicator: string }) => void;
  /** ccxt exchange id when a live broker is configured: candles then stream
   * from that exchange via /ws/ohlcv instead of the yfinance REST poll. */
  liveExchange?: string | null;
}

export const ChartPanel = forwardRef<ChartPanelHandle, ChartPanelProps>(({ ticker, onStateChange, liveExchange }, ref) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
  const seriesRef = useRef<Record<string, any>>({});
  const aiHighlightLinesRef = useRef<IPriceLine[]>([]);

  const [activeIndicator, setActiveIndicator] = useState('all');
  const [timeframe, setTimeframe] = useState('1D');

  const intervalMap: Record<string, string> = {
    '1D': '1d', '1H': '1h', '30M': '30m', '15M': '15m', '5M': '5m',
  };

  const { data: ohlcv, loading: ohlcvLoading } = useOHLCV(ticker, intervalMap[timeframe] ?? '1d');
  // Live exchange feed supersedes the yfinance candles when available.
  const { candles: liveCandles, status: liveStatus } = useOhlcvWS(
    ticker, intervalMap[timeframe] ?? '1d', !!liveExchange,
  );

  // 1. Initialize chart (once)
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

    seriesRef.current.candlestick = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981', downColor: '#ef4444', borderVisible: false,
      wickUpColor: '#10b981', wickDownColor: '#ef4444',
    });
    seriesRef.current.volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' }, priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({ autoScale: true, scaleMargins: { top: 0.6, bottom: 0.3 } });

    seriesRef.current.sma20 = chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 2, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false });
    seriesRef.current.sma50 = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 2, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false });
    seriesRef.current.bbUpper = chart.addSeries(LineSeries, { color: 'rgba(167, 139, 250, 0.6)', lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false });
    seriesRef.current.bbLower = chart.addSeries(LineSeries, { color: 'rgba(167, 139, 250, 0.6)', lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false });
    seriesRef.current.rsi = chart.addSeries(LineSeries, { color: '#d946ef', lineWidth: 2, crosshairMarkerVisible: true, priceScaleId: 'rsi', priceLineVisible: false });
    seriesRef.current.rsiUpper = chart.addSeries(LineSeries, { color: 'rgba(255, 255, 255, 0.2)', lineWidth: 1, lineStyle: 2, priceScaleId: 'rsi', lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    seriesRef.current.rsiLower = chart.addSeries(LineSeries, { color: 'rgba(255, 255, 255, 0.2)', lineWidth: 1, lineStyle: 2, priceScaleId: 'rsi', lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    chart.priceScale('rsi').applyOptions({ autoScale: true, borderColor: 'rgba(255, 255, 255, 0.1)', scaleMargins: { top: 0.8, bottom: 0 } });

    const handleResize = () => {
      if (chartContainerRef.current) chart.applyOptions({ width: chartContainerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);
    return () => { window.removeEventListener('resize', handleResize); chart.remove(); chartRef.current = null; };
  }, []);

  // 2. Load candles: live exchange feed when it has data, else yfinance REST.
  const sourceCandles = liveCandles && liveCandles.length > 0 ? liveCandles : ohlcv?.candles;
  useEffect(() => {
    if (!chartRef.current || !seriesRef.current.candlestick || !sourceCandles || sourceCandles.length === 0) return;
    const intraday = (intervalMap[timeframe] ?? '1d') !== '1d';
    // Normalize time and deduplicate (timezone edge can create duplicate days)
    const seen = new Set<string | number>();
    const normalized = sourceCandles
      .map((c: any) => ({ ...c, time: normalizeTime(c.time, intraday) }))
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ohlcv, liveCandles, timeframe]);

  // 3. Indicator visibility
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

  // 4. A level highlighted on one ticker/timeframe means nothing on another.
  useEffect(() => {
    const cs = seriesRef.current.candlestick;
    if (cs) {
      aiHighlightLinesRef.current.forEach(l => cs.removePriceLine(l));
      aiHighlightLinesRef.current = [];
    }
  }, [ticker, timeframe]);

  useImperativeHandle(ref, () => ({
    setTimeframe: (tf: string) => setTimeframe(tf),
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

  useEffect(() => {
    onStateChange?.({ ticker, timeframe, activeIndicator });
  }, [ticker, timeframe, activeIndicator, onStateChange]);

  return (
    <Card className="col-span-12 flex flex-col bg-slate-900/50">
      <CardHeader className="py-4 border-b border-slate-800/50 flex flex-row items-center justify-between">
        <div className="flex items-center gap-6">
          <CardTitle className="text-xl flex items-center gap-3">
            {ticker}
            <span className="text-slate-400 font-normal text-sm">{getTickerName(ticker)}</span>
            {ohlcvLoading && <Loader2 size={14} className="animate-spin text-slate-500" />}
            {liveExchange && (
              <span
                className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                  liveStatus === 'connected'
                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                    : 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
                }`}
                title={`Live candles from ${liveExchange}`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${liveStatus === 'connected' ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
                {liveStatus === 'connected' ? liveExchange.toUpperCase() : 'Connecting…'}
              </span>
            )}
          </CardTitle>
          <Select options={INDICATOR_OPTIONS} value={activeIndicator} onChange={setActiveIndicator} className="w-48" />
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
