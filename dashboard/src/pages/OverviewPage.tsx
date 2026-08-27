import React, { useCallback, useRef } from 'react';
import { ChartPanel } from '../components/dashboard/ChartPanel';
import { TradingViewPanel } from '../components/dashboard/TradingViewPanel';
import type { ChartPanelHandle } from '../components/dashboard/ChartPanel';
import { MarketSelector } from '../components/dashboard/MarketSelector';
import { Card, CardContent } from '../components/ui/Card';
import { Alert, AlertDescription } from '../components/ui/Alert';
import { TradeActivityPanel } from '../components/dashboard/TradeActivityPanel';
import { OpenPositionsPanel } from '../components/dashboard/OpenPositionsPanel';
import { AgentInsights } from '../components/dashboard/AgentInsights';
import PredictionPanel from '../components/dashboard/PredictionPanel';
import { usePortfolio } from '../hooks/useApi';
import { usePortfolioWS, useChartControlWS } from '../hooks/useWebSocket';
import { Wallet, TrendingUp, TrendingDown, Target, ShieldAlert, Activity, DollarSign, Wifi, WifiOff } from 'lucide-react';

interface OverviewPageProps {
  activeTicker: string;
  setActiveTicker: (ticker: string) => void;
}

export const OverviewPage: React.FC<OverviewPageProps> = ({ activeTicker, setActiveTicker }) => {
  // WebSocket for real-time portfolio updates
  const { data: wsPortfolio, status: wsStatus } = usePortfolioWS();

  // Fase 7 — MCP-driven chart control. ChartPanel owns timeframe/
  // indicator state internally, so those commands go through this ref;
  // `ticker` is owned here (activeTicker), so set_view's ticker just
  // calls setActiveTicker directly.
  const chartPanelRef = useRef<ChartPanelHandle>(null);
  const { sendState: sendChartState } = useChartControlWS({
    onSetView: (ticker, timeframe, indicator) => {
      if (ticker) setActiveTicker(ticker);
      if (timeframe) chartPanelRef.current?.setTimeframe(timeframe);
      if (indicator) chartPanelRef.current?.setActiveIndicator(indicator);
    },
    onAnnotatePatterns: () => chartPanelRef.current?.triggerPatternDetection(),
    onHighlightPriceLevel: (_ticker, price, label, color) =>
      chartPanelRef.current?.highlightPriceLevel(price, label, color),
    onClearAiHighlights: () => chartPanelRef.current?.clearAiHighlights(),
  });
  const handleChartStateChange = useCallback(
    (state: { ticker: string; timeframe: string; activeIndicator: string }) => sendChartState(state),
    [sendChartState],
  );
  // SWR fallback (also used while WS is connecting)
  const { data: swrPortfolio, loading: pLoading, error: pError } = usePortfolio();
  // Use WS data when connected, otherwise SWR
  const portfolio = wsStatus === 'connected' ? wsPortfolio : swrPortfolio;
  const isLive = wsStatus === 'connected';

  const fmt = (n: number) => n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pnlColor = (n: number) => n >= 0 ? 'text-emerald-500' : 'text-rose-400';
  const pnlSign = (n: number) => n >= 0 ? '+' : '';

  return (
    <>
      <div className="grid grid-cols-12 gap-4 lg:gap-6">
        {/* TOP SECTION: Metrics & Info */}
        <div className="col-span-12 flex flex-col gap-4 lg:gap-6">
          
          {/* CONNECTION STATUS + METRICS ROW */}
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              {isLive ? (
                <span className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-[10px] font-bold">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  LIVE
                </span>
              ) : wsStatus === 'connecting' ? (
                <span className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-400 text-[10px] font-bold">
                  <Wifi size={10} className="animate-pulse" />
                  CONNECTING
                </span>
              ) : (
                <span className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-slate-500/10 border border-slate-500/30 text-slate-400 text-[10px] font-bold">
                  <WifiOff size={10} />
                  POLLING
                </span>
              )}
            </div>
          </div>

          <div className="flex overflow-x-auto snap-x snap-mandatory gap-4 lg:gap-6 pb-2 -mx-4 px-4 lg:mx-0 lg:px-0 lg:grid lg:grid-cols-4 lg:overflow-visible scrollbar-hide">
            
            {/* Total Equity Card */}
            <Card className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50 min-w-[260px] lg:min-w-0 snap-center shrink-0 shadow-lg relative overflow-hidden group">
              <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                <Wallet size={48} className="text-blue-400" />
              </div>
              <CardContent className="p-5 relative z-10">
                <div className="flex items-center gap-2 mb-2">
                  <span className="p-1.5 rounded-lg bg-blue-500/10 text-blue-400">
                    <DollarSign size={16} />
                  </span>
                  <span className="text-sm font-semibold text-slate-300">Total Equity</span>
                </div>
                <div className="text-2xl font-mono font-bold mt-1 text-white">
                  {pLoading ? <span className="animate-pulse text-slate-600">—</span> : `$${fmt(portfolio.total_equity)}`}
                </div>
                <div className={`text-xs font-semibold flex items-center gap-1 mt-2 px-2 py-1 rounded-full w-fit bg-slate-800/50 border border-slate-700/50 ${pnlColor(portfolio.total_pnl)}`}>
                  {portfolio.total_pnl >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                  {pnlSign(portfolio.total_pnl)}${fmt(Math.abs(portfolio.total_pnl))} All-time
                </div>
              </CardContent>
            </Card>
            
            {/* Daily P&L Card */}
            <Card className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50 min-w-[260px] lg:min-w-0 snap-center shrink-0 shadow-lg relative overflow-hidden group">
              <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                <Activity size={48} className={(portfolio.daily_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'} />
              </div>
              <CardContent className="p-5 relative z-10">
                <div className="flex items-center gap-2 mb-2">
                  <span className={`p-1.5 rounded-lg ${(portfolio.daily_pnl ?? 0) >= 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
                    {(portfolio.daily_pnl ?? 0) >= 0 ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
                  </span>
                  <span className="text-sm font-semibold text-slate-300">Daily P&L</span>
                </div>
                <div className={`text-2xl font-mono font-bold mt-1 ${(portfolio.daily_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {pLoading ? <span className="animate-pulse text-slate-600">—</span> : `${pnlSign(portfolio.daily_pnl ?? 0)}$${fmt(Math.abs(portfolio.daily_pnl ?? 0))}`}
                </div>
                <div className="text-xs text-slate-400 font-medium mt-2 flex items-center gap-1">
                  Today's performance
                </div>
              </CardContent>
            </Card>
            
            {/* Win Rate Card */}
            <Card className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50 min-w-[260px] lg:min-w-0 snap-center shrink-0 shadow-lg relative overflow-hidden group">
              <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                <Target size={48} className="text-purple-400" />
              </div>
              <CardContent className="p-5 relative z-10">
                <div className="flex items-center gap-2 mb-2">
                  <span className="p-1.5 rounded-lg bg-purple-500/10 text-purple-400">
                    <Target size={16} />
                  </span>
                  <span className="text-sm font-semibold text-slate-300">Win Rate</span>
                </div>
                <div className="text-2xl font-mono font-bold mt-1 text-white">
                  {pLoading ? <span className="animate-pulse text-slate-600">—</span> : `${(portfolio.win_rate * 100).toFixed(1)}%`}
                </div>
                <div className="text-xs text-slate-400 font-medium mt-2">
                  Based on {portfolio.total_trades} total trades
                </div>
              </CardContent>
            </Card>
            
            {/* Max Drawdown Card */}
            <Card className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50 min-w-[260px] lg:min-w-0 snap-center shrink-0 shadow-lg relative overflow-hidden group">
              <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                <ShieldAlert size={48} className="text-rose-400" />
              </div>
              <CardContent className="p-5 relative z-10">
                <div className="flex items-center gap-2 mb-2">
                  <span className="p-1.5 rounded-lg bg-rose-500/10 text-rose-400">
                    <ShieldAlert size={16} />
                  </span>
                  <span className="text-sm font-semibold text-slate-300">Max Drawdown</span>
                </div>
                <div className="text-2xl font-mono font-bold mt-1 text-rose-400">
                  {pLoading ? <span className="animate-pulse text-slate-600">—</span> : `-${((Number(portfolio?.max_drawdown_pct) || 0) * 100).toFixed(1)}%`}
                </div>
                <div className="text-xs text-slate-400 font-medium mt-2">
                  Historical maximum loss
                </div>
              </CardContent>
            </Card>
            
          </div>

          {/* API Error Banner */}
          {pError && (
            <Alert variant="warning" title="Backend Unavailable">
              <AlertDescription>
                <span className="font-mono">{pError}</span> &mdash; showing fallback data. Please ensure the backend server is running.
              </AlertDescription>
            </Alert>
          )}

        </div>
          {/* NEW FULL WIDTH CHART PANEL */}
          <ChartPanel ref={chartPanelRef} ticker={activeTicker} onStateChange={handleChartStateChange} />

          {/* TRADINGVIEW TELEMETRY & VISION PANEL */}
          <TradingViewPanel activeTicker={activeTicker} className="mt-4" />
      </div>

      <div className="grid grid-cols-12 gap-4 mt-6">
        <MarketSelector 
          activeTicker={activeTicker} 
          onSelectTicker={setActiveTicker}
          className="col-span-12 lg:col-span-3 h-[400px]"
        />

        {/* OPEN POSITIONS PANEL */}
        <OpenPositionsPanel 
          positions={portfolio?.open_positions ?? []} 
          className="col-span-12 lg:col-span-4 h-[400px]" 
        />

        {/* LIVE AI SIGNALS / BOT ALERTS PANEL */}
        <AgentInsights ticker={activeTicker} className="col-span-12 lg:col-span-5 h-[400px]" />
      </div>
      
      {/* MID ROW: EVENT TAPE (FULL WIDTH) */}
      <div className="grid grid-cols-12 gap-4 mt-4">
        <TradeActivityPanel ticker={activeTicker} className="col-span-12 h-[300px]" />
      </div>

      {/* BOTTOM ROW: PREDICTION MARKETS FULL-WIDTH */}
      <div className="mt-4 pb-8 w-full">
        <PredictionPanel ticker={activeTicker} />
      </div>
    </>
  );
};
