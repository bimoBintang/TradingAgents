import React from 'react';
import { Card, CardHeader, CardTitle } from '../ui/Card';
import { cx } from '../../utils/cx';
import { usePortfolio } from '../../hooks/useApi';
import { Loader2 } from 'lucide-react';

export const OpenPositionsTable: React.FC<{ className?: string }> = ({ className }) => {
  const { data: portfolio, loading, error } = usePortfolio();
  const positions = portfolio?.open_positions ?? [];

  return (
    <Card className={cx("bg-slate-900/50 flex flex-col", className)}>
      <CardHeader className="py-5 border-b border-slate-800/50 flex flex-row items-center justify-between">
        <CardTitle className="text-lg">Active Portfolio</CardTitle>
        <div className="flex gap-2 items-center">
            <span className="text-xs font-semibold text-slate-400 bg-slate-800/50 px-2 py-1 rounded-md">
              {positions.length} position{positions.length !== 1 ? 's' : ''}
            </span>
            <button className="px-3 py-1.5 rounded-md text-xs font-semibold text-slate-300 border border-slate-700 hover:bg-slate-800 transition-colors">
              Export CSV
            </button>
        </div>
      </CardHeader>
      
      <div className="overflow-x-auto flex-1 h-full">
        {loading && (
          <div className="flex items-center justify-center py-12 text-slate-400 gap-2">
            <Loader2 className="animate-spin" size={18} /> Loading positions…
          </div>
        )}

        {error && (
          <div className="text-center py-12 text-rose-400 text-sm">
            ⚠️ Failed to load positions: {error}
          </div>
        )}

        {!loading && !error && positions.length === 0 && (
          <div className="text-center py-12 text-slate-500 text-sm">
            No open positions. Run an analysis to generate trades.
          </div>
        )}

        {!loading && positions.length > 0 && (
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-slate-400 bg-slate-950/50 sticky top-0 z-10 uppercase tracking-wider">
              <tr>
                <th className="px-5 py-4 font-semibold border-b border-slate-800">Instrument</th>
                <th className="px-5 py-4 font-semibold border-b border-slate-800">Side</th>
                <th className="px-5 py-4 font-semibold border-b border-slate-800">Quantity</th>
                <th className="px-5 py-4 font-semibold border-b border-slate-800">Entry Price</th>
                <th className="px-5 py-4 font-semibold border-b border-slate-800">Mark Price</th>
                <th className="px-5 py-4 font-semibold border-b border-slate-800 text-right">Unrealized PNL</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos, i) => {
                const pnlPct = pos.entry_price > 0
                  ? ((pos.current_price - pos.entry_price) / pos.entry_price) * 100 * (pos.side === 'SELL' ? -1 : 1)
                  : 0;

                return (
                  <tr key={`${pos.ticker}-${i}`} className="border-b border-slate-800/30 hover:bg-slate-800/20 transition-colors group">
                    <td className="px-5 py-4">
                      <span className="font-bold text-slate-200">{pos.ticker}</span>
                    </td>
                    
                    <td className="px-5 py-4">
                      <span className={cx(
                        "px-2 py-1 rounded text-[10px] font-black tracking-widest",
                        pos.side === 'BUY'
                          ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                          : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                      )}>
                        {pos.side === 'BUY' ? 'LONG' : 'SHORT'}
                      </span>
                    </td>
                    
                    <td className="px-5 py-4 font-mono text-slate-300 font-medium">
                      {pos.quantity}
                    </td>

                    <td className="px-5 py-4 font-mono text-slate-300 font-medium">
                      ${pos.entry_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>

                    <td className="px-5 py-4 font-mono text-slate-300 font-medium whitespace-nowrap">
                       ${pos.current_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>

                    <td className="px-5 py-4 text-right">
                      <div className="flex flex-col items-end">
                        <span className={cx("font-mono font-bold whitespace-nowrap", pos.unrealized_pnl >= 0 ? "text-emerald-400" : "text-rose-400")}>
                          {pos.unrealized_pnl >= 0 ? '+' : ''}${Math.abs(pos.unrealized_pnl).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </span>
                        <span className={cx("text-xs font-semibold", pnlPct >= 0 ? "text-emerald-500/70" : "text-rose-500/70")}>
                          {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                        </span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
};
