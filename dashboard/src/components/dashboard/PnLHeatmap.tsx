import React, { useMemo } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { cx } from '../../utils/cx';
import { useTrades } from '../../hooks/useApi';
import { Loader2 } from 'lucide-react';

const getBackgroundColor = (pnl: number) => {
  if (pnl === 0) return 'bg-slate-800/50';
  if (pnl > 800) return 'bg-emerald-400';
  if (pnl > 300) return 'bg-emerald-500/80';
  if (pnl > 0) return 'bg-emerald-600/50';
  if (pnl > -300) return 'bg-rose-600/50';
  if (pnl > -800) return 'bg-rose-500/80';
  return 'bg-rose-400';
};

export const PnLHeatmap: React.FC<{ className?: string }> = ({ className }) => {
  const { data: trades, loading, error } = useTrades();
  
  // Aggregate trades by date into daily PnL
  const data = useMemo(() => {
    if (!trades || trades.length === 0) return [];
    
    const dailyPnl: Record<string, number> = {};
    
    for (const t of trades) {
      if (!t.fill_time || t.realized_pnl == null) continue;
      const date = t.fill_time.split('T')[0]; // YYYY-MM-DD
      dailyPnl[date] = (dailyPnl[date] || 0) + t.realized_pnl;
    }
    
    // Fill in last 90 days (with 0 for no-trade days)
    const result = [];
    const today = new Date();
    for (let i = 89; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(d.getDate() - i);
      const dateStr = d.toISOString().split('T')[0];
      result.push({
        date: dateStr,
        pnl: dailyPnl[dateStr] || 0,
      });
    }
    
    return result;
  }, [trades]);
  
  const profitableDays = data.filter(d => d.pnl > 0).length;
  const losingDays = data.filter(d => d.pnl < 0).length;
  
  return (
    <Card className={cx("bg-slate-900/50 flex flex-col", className)}>
      <CardHeader className="py-4 border-b border-slate-800/50 flex flex-row items-center justify-between">
        <CardTitle className="text-base">90-Day Performance Matrix</CardTitle>
        <div className="flex gap-4 text-xs font-semibold">
           {loading && <Loader2 className="animate-spin text-slate-400" size={14} />}
           {!loading && (
             <>
               <span className="text-emerald-500">{profitableDays} Green Days</span>
               <span className="text-rose-500">{losingDays} Red Days</span>
             </>
           )}
        </div>
      </CardHeader>
      
      <CardContent className="p-5 flex flex-col gap-4 flex-1">
        {error && (
          <div className="text-center text-rose-400 text-xs py-4">
            ⚠️ {error}
          </div>
        )}

        {/* Heatmap Grid */}
        <div className="flex gap-[3px] flex-wrap mt-auto">
          {data.map((day, i) => (
            <div 
              key={i} 
              className={cx("w-[14px] h-[14px] rounded-[3px] group relative cursor-pointer transition-transform hover:scale-125 hover:z-10 ring-1 ring-slate-900/50 hover:ring-slate-300", getBackgroundColor(day.pnl))}
            >
               {/* Tooltip */}
               <div className="absolute opacity-0 group-hover:opacity-100 bottom-full left-1/2 -translate-x-1/2 mb-1 bg-slate-800 text-slate-100 text-[10px] font-mono px-2 py-1 rounded whitespace-nowrap z-20 shadow-xl pointer-events-none">
                 {day.date}: {day.pnl >= 0 ? '+' : ''}${day.pnl.toFixed(2)}
               </div>
            </div>
          ))}
        </div>
        
        {/* Legend */}
        <div className="flex items-center justify-end gap-2 text-[10px] text-slate-500 font-semibold mt-auto">
          <span>Loss</span>
          <div className="w-3 h-3 rounded-[2px] bg-rose-400" />
          <div className="w-3 h-3 rounded-[2px] bg-rose-500/80" />
          <div className="w-3 h-3 rounded-[2px] bg-rose-600/50" />
          <div className="w-3 h-3 rounded-[2px] bg-slate-800/50" />
          <div className="w-3 h-3 rounded-[2px] bg-emerald-600/50" />
          <div className="w-3 h-3 rounded-[2px] bg-emerald-500/80" />
          <div className="w-3 h-3 rounded-[2px] bg-emerald-400" />
          <span>Profit</span>
        </div>
      </CardContent>
    </Card>
  );
};
