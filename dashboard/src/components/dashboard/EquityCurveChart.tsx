import React, { useEffect, useRef, useMemo } from 'react';
import { createChart, ColorType, AreaSeries, LineSeries } from 'lightweight-charts';
import type { ISeriesApi } from 'lightweight-charts';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { cx } from '../../utils/cx';
import { useEquityCurve, useTrades } from '../../hooks/useApi';
import { Loader2 } from 'lucide-react';

/**
 * EquityCurveChart — uses backend equity-curve endpoint when available,
 * falls back to client-side computation from trades.
 * Includes a drawdown overlay (red line below zero).
 */
export const EquityCurveChart: React.FC<{ className?: string }> = ({ className }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
  const areaSeriesRef = useRef<ISeriesApi<'Area'> | null>(null);
  const ddSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const { data: backendCurve, loading: curveLoading } = useEquityCurve();
  const { data: trades, loading: tradesLoading } = useTrades();

  const loading = curveLoading || tradesLoading;

  // Build equity data: prefer backend, fallback to client-side
  const { equityData, drawdownData } = useMemo(() => {
    const INITIAL_BALANCE = 10000;

    // Try backend data first
    if (backendCurve && backendCurve.length > 0) {
      const eq = backendCurve.map(p => ({
        time: p.timestamp.split('T')[0],
        value: p.total_equity,
      }));
      const dd = backendCurve.map(p => ({
        time: p.timestamp.split('T')[0],
        value: -(p.drawdown_pct ?? 0) * 100, // negative percentage
      }));
      return { equityData: eq, drawdownData: dd };
    }

    // Fallback: compute from trades
    if (!trades || trades.length === 0) {
      const points = [];
      const today = new Date();
      for (let i = 29; i >= 0; i--) {
        const d = new Date(today);
        d.setDate(d.getDate() - i);
        points.push({ time: d.toISOString().split('T')[0], value: INITIAL_BALANCE });
      }
      return { equityData: points, drawdownData: [] };
    }

    const sorted = [...trades]
      .filter(t => t.fill_time && t.realized_pnl != null)
      .sort((a, b) => (a.fill_time ?? '').localeCompare(b.fill_time ?? ''));

    const dailyPnl: Record<string, number> = {};
    for (const t of sorted) {
      const date = t.fill_time!.split('T')[0];
      dailyPnl[date] = (dailyPnl[date] || 0) + (t.realized_pnl ?? 0);
    }

    const dates = Object.keys(dailyPnl).sort();
    let equity = INITIAL_BALANCE;
    let peak = INITIAL_BALANCE;
    const eq: { time: string; value: number }[] = [];
    const dd: { time: string; value: number }[] = [];

    for (const date of dates) {
      equity += dailyPnl[date];
      peak = Math.max(peak, equity);
      const drawdown = peak > 0 ? ((equity - peak) / peak) * 100 : 0;
      eq.push({ time: date, value: Math.round(equity * 100) / 100 });
      dd.push({ time: date, value: Math.round(drawdown * 100) / 100 });
    }

    return { equityData: eq, drawdownData: dd };
  }, [backendCurve, trades]);

  // 1. Initialize chart (run ONCE — mirrors ChartPanel.tsx's pattern).
  // Recreating the chart on every data update raced with React's own
  // reconciliation during the sign-in transition and caused
  // "Failed to execute 'insertBefore' on 'Node'" crashes.
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#64748b',
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: 'rgba(255, 255, 255, 0.03)' },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true },
      handleScroll: false,
      handleScale: false,
      height: 250,
    });

    chartRef.current = chart;

    areaSeriesRef.current = chart.addSeries(AreaSeries, {
      lineColor: '#10b981',
      topColor: 'rgba(16, 185, 129, 0.3)',
      bottomColor: 'rgba(16, 185, 129, 0.0)',
      lineWidth: 2,
      crosshairMarkerVisible: true,
      priceLineVisible: false,
    });

    ddSeriesRef.current = chart.addSeries(LineSeries, {
      color: 'rgba(239, 68, 68, 0.5)',
      lineWidth: 1,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
      priceScaleId: 'drawdown',
      lastValueVisible: false,
    });
    chart.priceScale('drawdown').applyOptions({
      scaleMargins: { top: 0.7, bottom: 0.0 },
      borderVisible: false,
    });

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };

    window.addEventListener('resize', handleResize);
    setTimeout(handleResize, 10);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      areaSeriesRef.current = null;
      ddSeriesRef.current = null;
    };
  }, []);

  // 2. Update series data whenever equity/drawdown data changes.
  useEffect(() => {
    if (!chartRef.current || !areaSeriesRef.current || equityData.length === 0) return;

    const isPositive = equityData[equityData.length - 1].value >= equityData[0].value;
    areaSeriesRef.current.applyOptions({
      lineColor: isPositive ? '#10b981' : '#ef4444',
      topColor: isPositive ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)',
      bottomColor: isPositive ? 'rgba(16, 185, 129, 0.0)' : 'rgba(239, 68, 68, 0.0)',
    });
    areaSeriesRef.current.setData(equityData);

    ddSeriesRef.current?.setData(drawdownData);

    chartRef.current.timeScale().fitContent();
  }, [equityData, drawdownData]);

  const initialBal = equityData[0]?.value ?? 0;
  const currentBal = equityData[equityData.length - 1]?.value ?? 0;
  const growth = currentBal - initialBal;
  const growthPct = initialBal > 0 ? (growth / initialBal) * 100 : 0;
  const currentDD = drawdownData.length > 0 ? drawdownData[drawdownData.length - 1]?.value : null;

  return (
    <Card className={cx("bg-slate-900/50 flex flex-col", className)}>
      <CardHeader className="py-4 border-b border-slate-800/50 flex flex-row items-center justify-between z-10">
        <CardTitle className="text-base flex items-center gap-3">
          Cumulative Equity
          {loading ? (
            <Loader2 className="animate-spin text-slate-400" size={14} />
          ) : (
            <span className={cx("text-xs font-bold px-2 py-0.5 rounded", growth >= 0 ? "bg-emerald-500/20 text-emerald-400" : "bg-rose-500/20 text-rose-400")}>
              {growth >= 0 ? '+' : ''}{growthPct.toFixed(2)}%
            </span>
          )}
        </CardTitle>
        <div className="flex items-center gap-3">
          {currentDD !== null && currentDD < 0 && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/30">
              DD {currentDD.toFixed(1)}%
            </span>
          )}
          <span className="font-mono text-lg font-bold text-slate-100">${currentBal.toLocaleString()}</span>
        </div>
      </CardHeader>

      <CardContent className="p-0 relative flex-1">
         <div
           ref={chartContainerRef}
           className="absolute inset-0 rounded-b-xl overflow-hidden"
         />
      </CardContent>
    </Card>
  );
};
