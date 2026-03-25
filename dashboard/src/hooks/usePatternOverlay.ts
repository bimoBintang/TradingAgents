/**
 * usePatternOverlay — manages LineSeries lifecycle for chart pattern overlays.
 *
 * Accepts a React ref to the chart (not the chart instance directly)
 * so it always has access to the current chart even after mount.
 */

import { useRef, useCallback, useEffect } from 'react';
import { LineSeries, LineStyle } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, Time, LineWidth } from 'lightweight-charts';
import type { ChartPattern, PatternPoint } from '../types/patterns';

// ── Color & Style Config per Pattern Type ────────────────────────────

const PATTERN_STYLES = {
  head_and_shoulders: {
    body:     { color: '#7F77DD', lineWidth: 2 as LineWidth, lineStyle: LineStyle.Dashed },
    neckline: { color: '#7F77DD', lineWidth: 1 as LineWidth, lineStyle: LineStyle.Dotted },
  },
  rising_wedge: {
    upper: { color: '#E24B4A', lineWidth: 2 as LineWidth, lineStyle: LineStyle.Solid },
    lower: { color: '#F09595', lineWidth: 2 as LineWidth, lineStyle: LineStyle.Solid },
  },
  falling_wedge: {
    upper: { color: '#1D9E75', lineWidth: 2 as LineWidth, lineStyle: LineStyle.Solid },
    lower: { color: '#9FE1CB', lineWidth: 2 as LineWidth, lineStyle: LineStyle.Solid },
  },
} as const;

// ── Helper: Unix seconds → 'YYYY-MM-DD' (matches OHLCV normalizeTime) ───

function unixToDateStr(ts: number): string {
  const d = new Date(ts * 1000);
  const yyyy = d.getUTCFullYear();
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(d.getUTCDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

// ── Helper: build sorted + deduplicated time/value data ──────────────

function buildSeriesData(points: PatternPoint[], labels: string[]) {
  const filtered = points
    .filter(p => labels.includes(p.label))
    .sort((a, b) => a.time - b.time);

  const seen = new Set<string>();
  const result: { time: Time; value: number }[] = [];
  for (const p of filtered) {
    const dateStr = unixToDateStr(p.time);
    if (!seen.has(dateStr)) {
      seen.add(dateStr);
      result.push({ time: dateStr as Time, value: p.price });
    }
  }
  return result;
}

// ── Hook ─────────────────────────────────────────────────────────────

export function usePatternOverlay(chartRef: React.MutableRefObject<IChartApi | null>) {
  const seriesRefs = useRef<ISeriesApi<'Line'>[]>([]);

  const clearPatterns = useCallback(() => {
    const chart = chartRef.current;
    if (!chart) return;
    for (const s of seriesRefs.current) {
      try { chart.removeSeries(s); } catch { /* already removed */ }
    }
    seriesRefs.current = [];
  }, [chartRef]);

  const addLine = useCallback(
    (data: { time: Time; value: number }[], opts: { color: string; lineWidth: LineWidth; lineStyle: number }) => {
      const chart = chartRef.current;
      if (!chart || data.length < 2) return;
      const series = chart.addSeries(LineSeries, {
        color: opts.color,
        lineWidth: opts.lineWidth,
        lineStyle: opts.lineStyle,
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceLineVisible: false,
      });
      series.setData(data);
      seriesRefs.current.push(series);
    },
    [chartRef],
  );

  const drawPatterns = useCallback(
    (patterns: ChartPattern[]) => {
      clearPatterns();
      for (const pattern of patterns) {
        const pts = pattern.points;

        if (pattern.type === 'head_and_shoulders') {
          const style = PATTERN_STYLES.head_and_shoulders;
          addLine(buildSeriesData(pts, ['left_shoulder', 'head', 'right_shoulder']), style.body);
          addLine(buildSeriesData(pts, ['neckline_left', 'neckline_right']), style.neckline);
        }

        if (pattern.type === 'rising_wedge') {
          const style = PATTERN_STYLES.rising_wedge;
          addLine(buildSeriesData(pts, ['upper_start', 'upper_end']), style.upper);
          addLine(buildSeriesData(pts, ['lower_start', 'lower_end']), style.lower);
        }

        if (pattern.type === 'falling_wedge') {
          const style = PATTERN_STYLES.falling_wedge;
          addLine(buildSeriesData(pts, ['upper_start', 'upper_end']), style.upper);
          addLine(buildSeriesData(pts, ['lower_start', 'lower_end']), style.lower);
        }
      }
    },
    [addLine, clearPatterns],
  );

  // Auto-cleanup when component unmounts
  useEffect(() => {
    return () => { clearPatterns(); };
  }, [clearPatterns]);

  return { drawPatterns, clearPatterns };
}
