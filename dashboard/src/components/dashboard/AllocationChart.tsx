import React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { cx } from '../../utils/cx';
import { usePortfolio } from '../../hooks/useApi';
import { Loader2 } from 'lucide-react';

const COLORS = [
  { bgClass: 'bg-amber-500', label: 'Amber' },
  { bgClass: 'bg-emerald-500', label: 'Green' },
  { bgClass: 'bg-blue-500', label: 'Blue' },
  { bgClass: 'bg-rose-500', label: 'Red' },
  { bgClass: 'bg-purple-500', label: 'Purple' },
  { bgClass: 'bg-cyan-500', label: 'Cyan' },
  { bgClass: 'bg-orange-500', label: 'Orange' },
  { bgClass: 'bg-pink-500', label: 'Pink' },
];

export const AllocationChart: React.FC<{ className?: string }> = ({ className }) => {
  const { data: portfolio, loading } = usePortfolio();
  
  // Build allocation from real positions + cash
  const allocationData = React.useMemo(() => {
    const items: { asset: string; value: number; bgClass: string }[] = [];
    
    if (portfolio?.open_positions) {
      for (let i = 0; i < portfolio.open_positions.length; i++) {
        const pos = portfolio.open_positions[i];
        const marketValue = pos.quantity * pos.current_price;
        items.push({
          asset: pos.ticker,
          value: Math.abs(marketValue),
          bgClass: COLORS[i % COLORS.length].bgClass,
        });
      }
    }
    
    // Add cash as the last slice
    const cashBalance = portfolio?.cash_balance ?? 0;
    if (cashBalance > 0) {
      items.push({
        asset: 'Cash',
        value: cashBalance,
        bgClass: 'bg-slate-500',
      });
    }
    
    return items;
  }, [portfolio]);

  const totalValue = allocationData.reduce((acc, curr) => acc + curr.value, 0);

  return (
    <Card className={cx("bg-slate-900/50 flex flex-col", className)}>
      <CardHeader className="py-5 border-b border-slate-800/50">
        <CardTitle className="text-lg">Asset Allocation</CardTitle>
      </CardHeader>
      
      <CardContent className="p-6 flex flex-col items-center justify-center flex-1">
        
        {loading && (
          <div className="flex items-center gap-2 text-slate-400 py-8">
            <Loader2 className="animate-spin" size={16} /> Loading…
          </div>
        )}

        {!loading && allocationData.length === 0 && (
          <div className="text-slate-500 text-sm py-8">No assets in portfolio.</div>
        )}

        {!loading && allocationData.length > 0 && (
          <>
            {/* Stacked Bar */}
            <div className="w-full flex h-6 rounded-full overflow-hidden mb-8 shadow-inner ring-1 ring-slate-800">
              {allocationData.map((item, i) => {
                const percentage = totalValue > 0 ? (item.value / totalValue) * 100 : 0;
                return (
                  <div 
                    key={i} 
                    className={cx("h-full transition-all group relative cursor-pointer", item.bgClass)}
                    style={{ width: `${percentage}%` }}
                  >
                      <div className="absolute opacity-0 group-hover:opacity-100 transition-opacity bottom-full left-1/2 -translate-x-1/2 mb-2 bg-slate-800 text-white text-xs px-2 py-1 rounded whitespace-nowrap z-20 pointer-events-none">
                        {item.asset}: {percentage.toFixed(1)}%
                      </div>
                  </div>
                );
              })}
            </div>
            
            {/* Breakdown List */}
            <div className="w-full flex flex-col gap-3">
              {allocationData.map((item, i) => {
                 const percentage = totalValue > 0 ? (item.value / totalValue) * 100 : 0;
                 return (
                   <div key={i} className="flex items-center justify-between">
                     <div className="flex items-center gap-3">
                       <div className={cx("w-3 h-3 rounded-sm", item.bgClass)} />
                       <span className="font-semibold text-slate-300 text-sm">{item.asset}</span>
                     </div>
                     <div className="flex items-center gap-4">
                       <span className="font-mono text-slate-400 text-sm">${item.value.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                       <span className="font-mono font-bold text-slate-100 text-sm w-12 text-right">{percentage.toFixed(1)}%</span>
                     </div>
                   </div>
                 )
              })}
            </div>
          </>
        )}

      </CardContent>
    </Card>
  );
};
