import React, { useMemo } from 'react';
import { Card, CardContent } from '../components/ui/Card';
import { EquityCurveChart } from '../components/dashboard/EquityCurveChart';
import { useTrades, usePortfolio, usePerformance } from '../hooks/useApi';

export const JournalPage: React.FC = () => {
  const { data: trades } = useTrades();
  const { data: portfolio, loading } = usePortfolio();
  const { data: perf, loading: perfLoading } = usePerformance();

  const fmt = (n: number) => n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // Compute stats from real trades
  const stats = useMemo(() => {
    if (!trades || trades.length === 0) {
      return { profitFactor: 0, avgWin: 0, avgLoss: 0, longWR: 0, shortWR: 0, rr: '0:0' };
    }

    let grossProfit = 0, grossLoss = 0;
    let winCount = 0, lossCount = 0;
    let longWins = 0, longTotal = 0, shortWins = 0, shortTotal = 0;
    let totalWin = 0, totalLoss = 0;

    for (const t of trades) {
      const pnl = t.realized_pnl ?? 0;
      const action = t.action ?? '';

      if (pnl > 0) {
        grossProfit += pnl;
        winCount++;
        totalWin += pnl;
      } else if (pnl < 0) {
        grossLoss += Math.abs(pnl);
        lossCount++;
        totalLoss += Math.abs(pnl);
      }

      if (action === 'BUY') {
        longTotal++;
        if (pnl > 0) longWins++;
      } else if (action === 'SELL') {
        shortTotal++;
        if (pnl > 0) shortWins++;
      }
    }

    const avgWin = winCount > 0 ? totalWin / winCount : 0;
    const avgLoss = lossCount > 0 ? totalLoss / lossCount : 0;
    const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;
    const longWR = longTotal > 0 ? (longWins / longTotal) * 100 : 0;
    const shortWR = shortTotal > 0 ? (shortWins / shortTotal) * 100 : 0;
    const rrRatio = avgLoss > 0 ? (avgWin / avgLoss).toFixed(1) : '∞';

    return { profitFactor, avgWin, avgLoss, longWR, shortWR, rrRatio };
  }, [trades]);

  return (
    <div className="flex flex-col gap-6 h-full pb-8">
      
      {/* Top Analytics Row */}
      <div className="grid grid-cols-12 gap-6">
        <EquityCurveChart className="col-span-12 min-h-[320px]" />
      </div>

      {/* Performance Metrics Row 1 — from real data */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <Card className="bg-slate-900/50">
          <CardContent className="p-5">
            <span className="text-sm font-medium text-slate-400">Profit Factor</span>
            <div className={`text-2xl font-mono font-bold mt-2 ${stats.profitFactor >= 1.5 ? 'text-emerald-400' : stats.profitFactor >= 1 ? 'text-amber-400' : 'text-rose-400'}`}>
              {loading ? '—' : stats.profitFactor === Infinity ? '∞' : stats.profitFactor.toFixed(2)}
            </div>
            <div className="text-sm text-slate-500 font-medium mt-1">
              Gross Profit / Gross Loss
            </div>
          </CardContent>
        </Card>
        
        <Card className="bg-slate-900/50">
          <CardContent className="p-5">
            <span className="text-sm font-medium text-slate-400">Avg Win vs Avg Loss</span>
            <div className="flex items-baseline gap-2 mt-2">
              <span className="text-xl font-mono font-bold text-emerald-500">
                {loading ? '—' : `+$${fmt(stats.avgWin)}`}
              </span>
              <span className="text-lg font-mono font-bold text-slate-600">/</span>
              <span className="text-xl font-mono font-bold text-rose-500">
                {loading ? '—' : `-$${fmt(stats.avgLoss)}`}
              </span>
            </div>
            <div className="text-sm text-slate-500 font-medium mt-1">
              Risk Reward Ratio 1:{stats.rrRatio}
            </div>
          </CardContent>
        </Card>
        
        <Card className="bg-slate-900/50">
          <CardContent className="p-5">
            <span className="text-sm font-medium text-slate-400">Long Win Rate</span>
            <div className="text-2xl font-mono font-bold mt-2 text-slate-100">
              {loading ? '—' : `${stats.longWR.toFixed(1)}%`}
            </div>
            <div className={`text-sm font-medium mt-1 ${stats.longWR > stats.shortWR ? 'text-emerald-500' : 'text-rose-500'}`}>
              {stats.longWR > stats.shortWR
                ? `+${(stats.longWR - stats.shortWR).toFixed(1)}% higher than short WR`
                : `${(stats.longWR - stats.shortWR).toFixed(1)}% lower than short WR`}
            </div>
          </CardContent>
        </Card>
        
        <Card className="bg-slate-900/50">
          <CardContent className="p-5">
            <span className="text-sm font-medium text-slate-400">Max Drawdown</span>
            <div className="text-2xl font-mono font-bold mt-2 text-rose-400">
              {loading ? '—' : `-${((Number(portfolio?.max_drawdown_pct) || 0) * 100).toFixed(1)}%`}
            </div>
            <div className="text-sm text-slate-500 font-medium mt-1">
              Based on {portfolio?.total_trades ?? 0} trades
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Performance Metrics Row 2 — from backend /api/journal/performance */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <Card className="bg-slate-900/50 border border-slate-800/50">
          <CardContent className="p-5">
            <span className="text-sm font-medium text-slate-400">Sharpe Ratio</span>
            <div className={`text-2xl font-mono font-bold mt-2 ${(perf.sharpe_ratio ?? 0) >= 1.5 ? 'text-emerald-400' : (perf.sharpe_ratio ?? 0) >= 1.0 ? 'text-amber-400' : 'text-rose-400'}`}>
              {perfLoading ? '—' : perf.sharpe_ratio.toFixed(2)}
            </div>
            <div className="text-sm text-slate-500 font-medium mt-1">
              {(perf.sharpe_ratio ?? 0) >= 2.0 ? 'Excellent' : (perf.sharpe_ratio ?? 0) >= 1.0 ? 'Good' : 'Needs improvement'}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-slate-900/50 border border-slate-800/50">
          <CardContent className="p-5">
            <span className="text-sm font-medium text-slate-400">Best Trade</span>
            <div className="text-2xl font-mono font-bold mt-2 text-emerald-400">
              {perfLoading ? '—' : `+$${fmt(perf.best_trade)}`}
            </div>
            <div className="text-sm text-slate-500 font-medium mt-1">
              Largest single profit
            </div>
          </CardContent>
        </Card>

        <Card className="bg-slate-900/50 border border-slate-800/50">
          <CardContent className="p-5">
            <span className="text-sm font-medium text-slate-400">Worst Trade</span>
            <div className="text-2xl font-mono font-bold mt-2 text-rose-400">
              {perfLoading ? '—' : `-$${fmt(Math.abs(perf.worst_trade))}`}
            </div>
            <div className="text-sm text-slate-500 font-medium mt-1">
              Largest single loss
            </div>
          </CardContent>
        </Card>

        <Card className="bg-slate-900/50 border border-slate-800/50">
          <CardContent className="p-5">
            <span className="text-sm font-medium text-slate-400">Total Trades</span>
            <div className="text-2xl font-mono font-bold mt-2 text-white">
              {perfLoading ? '—' : perf.total_trades}
            </div>
            <div className="text-sm text-slate-500 font-medium mt-1">
              Win rate: {perfLoading ? '—' : `${(perf.win_rate * 100).toFixed(1)}%`}
            </div>
          </CardContent>
        </Card>
      </div>

    </div>
  );
};
