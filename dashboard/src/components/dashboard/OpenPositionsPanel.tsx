import React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { cx } from '../../utils/cx';
import type { Position } from '../../services/api';
import { Briefcase, Lock } from 'lucide-react';

interface OpenPositionsPanelProps {
  positions: Position[];
  className?: string;
}

export const OpenPositionsPanel: React.FC<OpenPositionsPanelProps> = ({ positions, className }) => {
  const fmt = (n: number) => n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 });
  const pnlColor = (n: number) => n >= 0 ? 'text-emerald-400' : 'text-rose-400';
  const pnlSign = (n: number) => n >= 0 ? '+' : '';

  return (
    <Card className={cx("bg-slate-900/50 flex flex-col shadow-xl border-slate-800", className)}>
      <CardHeader className="py-4 border-b border-slate-800/80 flex flex-row items-center justify-between shrink-0 bg-slate-950/20">
        <CardTitle className="text-base flex items-center gap-2.5 font-bold tracking-tight text-slate-100">
          <div className="p-1.5 rounded-md bg-amber-500/20 text-amber-400 border border-amber-500/30 shadow-inner">
            <Lock size={16} />
          </div>
          Open Positions
        </CardTitle>
        <div className="px-2.5 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider bg-slate-800/80 border border-slate-700/50 text-slate-300 shadow-inner flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
          {positions.length} Active
        </div>
      </CardHeader>
      
      <CardContent className="p-0 flex flex-col overflow-y-auto flex-1 scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-transparent">
        {positions.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center animate-in fade-in duration-500">
            <div className="w-16 h-16 rounded-full bg-slate-800/30 flex items-center justify-center mb-4 border border-slate-700/30">
              <Briefcase size={28} className="text-slate-500 opacity-40" />
            </div>
            <span className="font-semibold text-slate-300 text-sm">Portfolio is Empty</span>
            <span className="text-xs text-slate-500 mt-1 max-w-[200px] leading-relaxed">The AI agent is currently flat and waiting for ideal setups.</span>
          </div>
        ) : (
          <div className="flex flex-col divide-y divide-slate-800/50">
            {positions.map((pos, i) => {
              const pnlVal = pos.unrealized_pnl || 0;
              const badgeClass = pos.side === 'BUY' 
                ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' 
                : 'bg-rose-500/15 text-rose-400 border-rose-500/30';

              return (
                <div 
                  key={`${pos.ticker}-${i}`} 
                  className="p-4 hover:bg-slate-800/30 transition-all flex items-center justify-between group cursor-default"
                >
                  {/* Left Column: Asset Identity */}
                  <div className="flex flex-col h-full justify-center">
                    <div className="flex items-center gap-2">
                       <span className="font-bold text-slate-100 text-[15px] tracking-tight group-hover:text-white transition-colors">
                         {pos.ticker}
                       </span>
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      <span className={cx("px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border", badgeClass)}>
                        {pos.side}
                      </span>
                    </div>
                  </div>
                  
                  {/* Right Column: Real-time Valuation */}
                  <div className="flex flex-col items-end text-right h-full justify-center">
                    <span className={cx("font-mono font-bold text-sm tracking-tight", pnlColor(pnlVal))}>
                      {pnlSign(pnlVal)}${fmt(Math.abs(pnlVal))}
                    </span>
                    <div className="flex items-center justify-end text-[11px] text-slate-500 mt-1.5 font-medium tracking-wide">
                      <span className="text-slate-400">{pos.quantity}</span>
                      <span className="mx-1 text-slate-600">@</span>
                      <span className="mr-2">${fmt(pos.entry_price)}</span>
                      <span className="text-slate-600 mr-2">➔</span>
                      <span>Mkt: ${fmt(pos.current_price)}</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
};
