import React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { ArrowUpRight, ArrowDownRight, ArrowRight, Loader2, Inbox } from 'lucide-react';
import { cx } from '../../utils/cx';
import { useTrades } from '../../hooks/useApi';

interface TradeActivityPanelProps {
  ticker: string;
  className?: string;
}

/**
 * TradeActivityPanel — Rendered as a high-end prop-firm order tape (Execution Feed)
 */
export const TradeActivityPanel: React.FC<TradeActivityPanelProps> = ({ ticker, className }) => {
  const { data: trades, loading, error } = useTrades();

  // Filter trades relevant to this ticker (or show all if none match)
  const relevantTrades = trades?.filter(t => t.ticker === ticker) ?? [];
  const displayTrades = relevantTrades.length > 0 ? relevantTrades.slice(-5).reverse() : (trades ?? []).slice(-5).reverse();

  const formatTime = (isoString?: string): string => {
    if (!isoString) return 'Unknown';
    try {
      const d = new Date(isoString);
      const now = new Date();
      const diffMs = now.getTime() - d.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      if (diffMins < 60) return `${diffMins}m ago`;
      const diffHours = Math.floor(diffMins / 60);
      if (diffHours < 24) return `${diffHours}h ago`;
      const diffDays = Math.floor(diffHours / 24);
      return `${diffDays}d ago`;
    } catch {
      return isoString.split('T')[1]?.slice(0, 5) || isoString;
    }
  };

  return (
    <Card className={cx("border-slate-800 bg-slate-900/50 flex flex-col shadow-xl", className)}>
      <CardHeader className="py-4 border-b border-slate-800/80 flex flex-row items-center justify-between shrink-0 bg-slate-950/20">
        <CardTitle className="text-base flex items-center gap-2.5 font-bold tracking-tight text-slate-100">
          <div className="p-1.5 rounded-md bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">
            <ArrowRight size={16} className="-rotate-45" />
          </div>
          Trade Activity
        </CardTitle>
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 bg-slate-800/80 border border-slate-700/50 px-2.5 py-1 rounded-md shadow-inner">
          {ticker}
        </span>
      </CardHeader>
      
      <CardContent className="p-0 flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-transparent">
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 text-slate-500 gap-3">
            <Loader2 className="animate-spin text-indigo-500" size={24} />
            <span className="text-xs font-medium uppercase tracking-widest animate-pulse">Syncing orders...</span>
          </div>
        )}

        {error && !loading && (
          <div className="flex items-center justify-center py-12 text-rose-400 text-sm font-medium bg-rose-500/5 border-b border-rose-500/10">
            ⚠️ Connection to Order Broker failed
          </div>
        )}

        {!loading && !error && displayTrades.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-slate-500 text-sm text-center">
            <div className="w-12 h-12 rounded-full bg-slate-800/40 flex items-center justify-center mb-3 border border-slate-700/30">
              <Inbox size={22} className="text-slate-400 opacity-50" />
            </div>
            <span className="font-medium text-slate-300">No trading activity found</span>
            <span className="text-xs text-slate-600 mt-1">AI agent hasn't executed trades yet.</span>
          </div>
        )}

        <div className="flex flex-col divide-y divide-slate-800/60">
          {displayTrades.map((trade, idx) => {
            const isBuy = trade.action === 'BUY';
            const iconClass = isBuy ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shadow-[0_0_10px_rgba(16,185,129,0.1)]' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20 shadow-[0_0_10px_rgba(244,63,94,0.1)]';
            const textTypeClass = isBuy ? 'text-emerald-500' : 'text-rose-500';
            
            const pnlValue = trade.realized_pnl;
            const hasPnl = pnlValue != null && pnlValue !== 0;
            const isPnlPositive = (pnlValue || 0) >= 0;
            const pnlStr = hasPnl ? `${isPnlPositive ? '+' : '-'} $${Math.abs(pnlValue!).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : null;

            return (
              <div
                key={trade.id ?? idx}
                className="p-4 hover:bg-slate-800/30 transition-all flex items-center justify-between group cursor-default"
              >
                {/* LEFT: Identity & Size */}
                <div className="flex items-center gap-4">
                  <div className={cx("p-2.5 rounded-xl shrink-0 transition-transform group-hover:scale-110", iconClass)}>
                    {isBuy ? <ArrowUpRight size={20} strokeWidth={2.5} /> : <ArrowDownRight size={20} strokeWidth={2.5} />}
                  </div>
                  <div>
                    <div className="font-bold text-slate-100 text-[15px] tracking-tight group-hover:text-white transition-colors">
                      {trade.ticker}
                    </div>
                    <div className="text-[11px] font-bold uppercase tracking-wider text-slate-500 mt-1 flex items-center gap-1.5">
                      <span className={textTypeClass}>{trade.action}</span>
                      <span className="text-slate-700">•</span>
                      <span className="text-slate-400">{trade.filled_qty} Units</span>
                    </div>
                  </div>
                </div>
                
                {/* RIGHT: Price & Execution PnL */}
                <div className="text-right flex flex-col items-end">
                  <div className="font-mono text-[14px] font-bold text-slate-200 group-hover:text-white transition-colors">
                    ${trade.fill_price?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })}
                  </div>
                  <div className="flex items-center gap-2 mt-1.5 align-middle">
                    <span className="text-[10px] font-medium text-slate-500 tracking-wider">
                      {formatTime(trade.fill_time)}
                    </span>
                    {hasPnl && (
                      <span className={cx(
                        "text-[10px] font-bold font-mono px-1.5 py-0.5 rounded-md border",
                        isPnlPositive 
                          ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' 
                          : 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                      )}>
                        {pnlStr}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        
        {!loading && displayTrades.length > 0 && (
          <div className="p-3 bg-slate-900 border-t border-slate-800/80">
            <button className="w-full py-2.5 rounded-lg text-xs font-bold text-slate-400 bg-slate-950/50 hover:bg-slate-800 hover:text-slate-200 hover:shadow-md border border-slate-800/80 transition-all uppercase tracking-widest flex items-center justify-center gap-2">
              All Orders <ArrowRight size={14} />
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
