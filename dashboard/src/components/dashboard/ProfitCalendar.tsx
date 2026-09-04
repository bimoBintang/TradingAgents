import React, { useMemo, useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { cx } from '../../utils/cx';
import { useTrades } from '../../hooks/useApi';
import { ChevronLeft, ChevronRight, Loader2 } from 'lucide-react';

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const cellTone = (pnl: number) => {
  if (pnl === 0) return 'bg-slate-800/40 border-slate-700/40 text-slate-500';
  if (pnl > 800) return 'bg-emerald-500/25 border-emerald-500/50 text-emerald-300';
  if (pnl > 300) return 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400';
  if (pnl > 0) return 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400';
  if (pnl > -300) return 'bg-rose-500/10 border-rose-500/20 text-rose-400';
  if (pnl > -800) return 'bg-rose-500/15 border-rose-500/30 text-rose-400';
  return 'bg-rose-500/25 border-rose-500/50 text-rose-300';
};

const fmtCompact = (n: number) =>
  `${n >= 0 ? '+' : '-'}$${Math.abs(n).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;

export const ProfitCalendar: React.FC<{ className?: string }> = ({ className }) => {
  const { data: trades, loading } = useTrades();
  const [cursor, setCursor] = useState(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1);
  });

  // Aggregate realized P&L + trade count per day (YYYY-MM-DD)
  const dailyStats = useMemo(() => {
    const map: Record<string, { pnl: number; count: number }> = {};
    for (const t of trades ?? []) {
      if (!t.fill_time || t.realized_pnl == null) continue;
      const date = t.fill_time.split('T')[0];
      if (!map[date]) map[date] = { pnl: 0, count: 0 };
      map[date].pnl += t.realized_pnl;
      map[date].count += 1;
    }
    return map;
  }, [trades]);

  const year = cursor.getFullYear();
  const month = cursor.getMonth();
  const today = new Date();
  const todayStr = today.toISOString().split('T')[0];

  const weeks = useMemo(() => {
    const firstDay = new Date(year, month, 1);
    const startOffset = firstDay.getDay(); // 0 = Sunday
    const daysInMonth = new Date(year, month + 1, 0).getDate();

    const cells: ({ dateStr: string; day: number } | null)[] = [];
    for (let i = 0; i < startOffset; i++) cells.push(null);
    for (let d = 1; d <= daysInMonth; d++) {
      const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
      cells.push({ dateStr, day: d });
    }
    while (cells.length % 7 !== 0) cells.push(null);

    const rows = [];
    for (let i = 0; i < cells.length; i += 7) rows.push(cells.slice(i, i + 7));
    return rows;
  }, [year, month]);

  const monthLabel = cursor.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });

  const monthTotal = useMemo(() => {
    let pnl = 0, tradingDays = 0, greenDays = 0, redDays = 0;
    for (const row of weeks) {
      for (const cell of row) {
        if (!cell) continue;
        const stat = dailyStats[cell.dateStr];
        if (!stat || stat.count === 0) continue;
        pnl += stat.pnl;
        tradingDays += 1;
        if (stat.pnl > 0) greenDays += 1;
        else if (stat.pnl < 0) redDays += 1;
      }
    }
    return { pnl, tradingDays, greenDays, redDays };
  }, [weeks, dailyStats]);

  return (
    <Card className={cx('bg-slate-900/50 flex flex-col', className)}>
      <CardHeader className="py-4 border-b border-slate-800/50 flex flex-row items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setCursor(new Date(year, month - 1, 1))}
            className="p-1.5 rounded-lg bg-slate-800/60 hover:bg-slate-700 text-slate-300 transition-colors"
            title="Previous month"
          >
            <ChevronLeft size={14} />
          </button>
          <CardTitle className="text-base w-[150px] text-center">{monthLabel}</CardTitle>
          <button
            onClick={() => setCursor(new Date(year, month + 1, 1))}
            className="p-1.5 rounded-lg bg-slate-800/60 hover:bg-slate-700 text-slate-300 transition-colors"
            title="Next month"
          >
            <ChevronRight size={14} />
          </button>
          <button
            onClick={() => setCursor(new Date(today.getFullYear(), today.getMonth(), 1))}
            className="ml-1 px-2 py-1 rounded-lg text-[10px] font-bold bg-slate-800/60 hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors"
          >
            Today
          </button>
        </div>

        <div className="flex items-center gap-3 text-xs font-semibold">
          {loading && <Loader2 className="animate-spin text-slate-400" size={14} />}
          {!loading && (
            <>
              <span className={monthTotal.pnl >= 0 ? 'text-emerald-500' : 'text-rose-500'}>
                {fmtCompact(monthTotal.pnl)}
              </span>
              <span className="text-slate-600">|</span>
              <span className="text-emerald-500">{monthTotal.greenDays}G</span>
              <span className="text-rose-500">{monthTotal.redDays}R</span>
            </>
          )}
        </div>
      </CardHeader>

      <CardContent className="p-4 flex flex-col gap-2">
        {/* Weekday header */}
        <div className="grid grid-cols-7 gap-1.5">
          {WEEKDAYS.map((w) => (
            <div key={w} className="text-center text-[10px] font-bold uppercase tracking-wider text-slate-500 pb-1">
              {w}
            </div>
          ))}
        </div>

        {/* Calendar grid */}
        <div className="flex flex-col gap-1.5">
          {weeks.map((row, ri) => (
            <div key={ri} className="grid grid-cols-7 gap-1.5">
              {row.map((cell, ci) => {
                if (!cell) return <div key={ci} className="aspect-square rounded-lg" />;
                const stat = dailyStats[cell.dateStr];
                const isToday = cell.dateStr === todayStr;
                return (
                  <div
                    key={ci}
                    className={cx(
                      'aspect-square rounded-lg border p-1.5 flex flex-col justify-between transition-transform hover:scale-[1.04] hover:z-10 cursor-default',
                      stat && stat.count > 0 ? cellTone(stat.pnl) : 'bg-slate-800/20 border-slate-800/40 text-slate-600',
                      isToday && 'ring-2 ring-blue-500/70',
                    )}
                    title={stat && stat.count > 0 ? `${cell.dateStr}: ${fmtCompact(stat.pnl)} (${stat.count} trade${stat.count > 1 ? 's' : ''})` : cell.dateStr}
                  >
                    <span className="text-[10px] font-semibold">{cell.day}</span>
                    {stat && stat.count > 0 && (
                      <span className="text-[11px] font-mono font-bold leading-none self-end">
                        {fmtCompact(stat.pnl)}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Legend */}
        <div className="flex items-center justify-end gap-2 text-[10px] text-slate-500 font-semibold mt-2">
          <span>Loss</span>
          <div className="w-3 h-3 rounded-[2px] bg-rose-500/25 border border-rose-500/50" />
          <div className="w-3 h-3 rounded-[2px] bg-rose-500/10 border border-rose-500/20" />
          <div className="w-3 h-3 rounded-[2px] bg-slate-800/40 border border-slate-700/40" />
          <div className="w-3 h-3 rounded-[2px] bg-emerald-500/10 border border-emerald-500/20" />
          <div className="w-3 h-3 rounded-[2px] bg-emerald-500/25 border border-emerald-500/50" />
          <span>Profit</span>
        </div>
      </CardContent>
    </Card>
  );
};
