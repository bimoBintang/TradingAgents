import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { Activity, ShieldCheck, Cpu, Code, Eye, EyeOff, RefreshCw, Send, CheckCircle2, AlertCircle } from 'lucide-react';
import { cx } from '../../utils/cx';

interface TradingViewPanelProps {
  activeTicker: string;
  className?: string;
}

export const TradingViewPanel: React.FC<TradingViewPanelProps> = ({ activeTicker, className }) => {
  const [ticker, setTicker] = useState(activeTicker || 'BTCUSDT');
  const [timeframe, setTimeframe] = useState('1h');
  const [loading, setLoading] = useState(false);
  const [mcpStatus, setMcpStatus] = useState<any>({ is_connected: false, mode: 'FALLBACK_QUANTITATIVE_TA' });
  const [analysisData, setAnalysisData] = useState<any>(null);
  
  // Pine Script Injector State
  const [pineCode, setPineCode] = useState(`//@version=5
strategy("CMAOP_RSI_Breakout", overlay=true)
rsiVal = ta.rsi(close, 14)
if (rsiVal < 30)
    strategy.entry("RSI_Long", strategy.long)
if (rsiVal > 70)
    strategy.close("RSI_Long")`);
  const [injecting, setInjecting] = useState(false);
  const [injectMessage, setInjectMessage] = useState<string | null>(null);
  const [injectSuccess, setInjectSuccess] = useState<boolean | null>(null);

  // Fetch MCP CDP Status
  const fetchMcpStatus = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/tradingview/mcp-status');
      if (res.ok) {
        const data = await res.json();
        setMcpStatus(data);
      }
    } catch (err) {
      setMcpStatus({ is_connected: false, mode: 'FALLBACK_QUANTITATIVE_TA' });
    }
  };

  // Fetch Combined Analysis
  const fetchAnalysis = async () => {
    setLoading(true);
    try {
      const cleanTicker = ticker.replace('-', '').toUpperCase();
      const res = await fetch(`http://localhost:8000/api/tradingview/analysis?ticker=${cleanTicker}&timeframe=${timeframe}`);
      if (res.ok) {
        const data = await res.json();
        setAnalysisData(data);
      }
    } catch (err) {
      console.error('Failed to fetch TradingView analysis:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMcpStatus();
    fetchAnalysis();
  }, [ticker, timeframe]);

  // Inject Pine Script Handler
  const handleInjectPineScript = async () => {
    setInjecting(true);
    setInjectMessage(null);
    setInjectSuccess(null);
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      const clerk = (window as any).Clerk;
      if (clerk && clerk.session) {
        const token = await clerk.session.getToken();
        if (token) headers['Authorization'] = `Bearer ${token}`;
      }

      const res = await fetch('http://localhost:8000/api/tradingview/pinescript', {
        method: 'POST',
        headers,
        body: JSON.stringify({ code: pineCode, script_name: 'CMAOP_RSI_Breakout' }),
      });
      const data = await res.json();
      if (res.ok) {
        setInjectSuccess(true);
        setInjectMessage(data.message || 'Script compiled & injected successfully!');
      } else {
        setInjectSuccess(false);
        setInjectMessage(data.detail || 'Syntax error or injection failed.');
      }
    } catch (err) {
      setInjectSuccess(false);
      setInjectMessage('Error connecting to backend API.');
    } finally {
      setInjecting(false);
    }
  };

  const ta = analysisData?.quantitative_ta;
  const vision = analysisData?.chart_vision_report;

  return (
    <Card className={cx("border-slate-800 bg-slate-900/60 backdrop-blur-md flex flex-col", className)}>
      {/* Header */}
      <CardHeader className="px-5 py-3.5 border-b border-slate-800/80 flex flex-row items-center justify-between">
        <div className="flex items-center gap-3">
          <CardTitle className="text-base flex items-center gap-2 text-slate-100 font-semibold">
            <Activity size={18} className="text-cyan-400" />
            TradingView Telemetry & Vision
          </CardTitle>

          {/* Timeframe Selector */}
          <div className="flex items-center bg-slate-800/60 rounded-lg p-0.5 border border-slate-700/50 text-xs">
            {['15m', '1h', '4h', '1d'].map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-2.5 py-1 rounded-md transition-all font-medium ${
                  timeframe === tf ? 'bg-blue-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        {/* CDP Connection Status Badge */}
        <div className="flex items-center gap-2">
          {mcpStatus.is_connected ? (
            <span className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 animate-pulse">
              <Cpu size={12} /> Live CDP Desktop (Port 9222)
            </span>
          ) : (
            <span className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/30">
              <ShieldCheck size={12} /> Quantitative Fallback (60s Cache)
            </span>
          )}

          <button
            onClick={() => { fetchMcpStatus(); fetchAnalysis(); }}
            disabled={loading}
            className="p-1.5 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 transition-colors"
            title="Refresh Analysis"
          >
            <RefreshCw size={14} className={loading ? "animate-spin text-cyan-400" : ""} />
          </button>
        </div>
      </CardHeader>

      <CardContent className="p-5 space-y-5 flex-1 overflow-y-auto">
        {/* Top Section: TA Signals + Vision Analysis */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          
          {/* Card 1: Quantitative Indicators (tradingview-ta) */}
          <div className="p-4 rounded-xl bg-slate-800/40 border border-slate-700/40 space-y-3">
            <div className="flex items-center justify-between border-b border-slate-700/30 pb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Technical Recommendation</span>
              <span className={`text-xs px-2.5 py-0.5 rounded-full font-bold uppercase ${
                ta?.recommendation?.includes('BUY') ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' :
                ta?.recommendation?.includes('SELL') ? 'bg-rose-500/20 text-rose-400 border border-rose-500/40' :
                'bg-slate-700 text-slate-300'
              }`}>
                {ta?.recommendation || 'LOADING...'}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="bg-slate-900/40 p-2.5 rounded-lg border border-slate-800">
                <span className="text-slate-400 block text-[10px]">RSI (14)</span>
                <span className="text-sm font-bold font-mono text-slate-100">
                  {ta?.indicators?.RSI ? ta.indicators.RSI.toFixed(1) : '--'}
                </span>
              </div>
              <div className="bg-slate-900/40 p-2.5 rounded-lg border border-slate-800">
                <span className="text-slate-400 block text-[10px]">MACD</span>
                <span className="text-sm font-bold font-mono text-slate-100">
                  {ta?.indicators?.['MACD.macd'] ? ta.indicators['MACD.macd'].toFixed(2) : '--'}
                </span>
              </div>
              <div className="bg-slate-900/40 p-2.5 rounded-lg border border-slate-800">
                <span className="text-slate-400 block text-[10px]">EMA 20</span>
                <span className="text-sm font-bold font-mono text-slate-100">
                  ${ta?.indicators?.EMA20 ? ta.indicators.EMA20.toLocaleString() : '--'}
                </span>
              </div>
              <div className="bg-slate-900/40 p-2.5 rounded-lg border border-slate-800">
                <span className="text-slate-400 block text-[10px]">SMA 50</span>
                <span className="text-sm font-bold font-mono text-slate-100">
                  ${ta?.indicators?.SMA50 ? ta.indicators.SMA50.toLocaleString() : '--'}
                </span>
              </div>
            </div>
          </div>

          {/* Card 2: ChartVisionAgent Report */}
          <div className="p-4 rounded-xl bg-slate-800/40 border border-slate-700/40 space-y-3">
            <div className="flex items-center justify-between border-b border-slate-700/30 pb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Eye size={14} className="text-cyan-400" /> ChartVisionAgent Report
              </span>
              <span className="text-xs text-cyan-400 font-bold">
                {vision?.visual_confidence != null ? `${(vision.visual_confidence * 100).toFixed(0)}% Confidence` : '--'}
              </span>
            </div>

            {vision?.mode === 'UNAVAILABLE' ? (
              // Honest empty state — no screenshot to analyze (CDP not
              // connected, no client-side fallback screenshot either).
              // Previously this fell through to fabricated defaults
              // ('SIDEWAYS' trend, 'Analyzing...' pattern) instead of
              // saying plainly that nothing was actually analyzed.
              <div className="flex flex-col items-center justify-center gap-1.5 py-4 text-center">
                <EyeOff size={18} className="text-slate-500" />
                <span className="text-xs font-semibold text-slate-400">Vision analysis unavailable</span>
                <span className="text-[10px] text-slate-500 max-w-[220px]" title={vision?.rationale}>
                  No chart screenshot to analyze right now
                </span>
              </div>
            ) : (
              <div className="space-y-2 text-xs">
                <div className="flex justify-between items-center bg-slate-900/40 px-3 py-1.5 rounded-lg">
                  <span className="text-slate-400">Primary Trend:</span>
                  <span className={`font-bold ${vision?.primary_trend === 'BULLISH' ? 'text-emerald-400' : vision?.primary_trend === 'BEARISH' ? 'text-rose-400' : 'text-slate-300'}`}>
                    {vision?.primary_trend ?? '--'}
                  </span>
                </div>
                <div className="flex justify-between items-center bg-slate-900/40 px-3 py-1.5 rounded-lg">
                  <span className="text-slate-400">Chart Pattern:</span>
                  <span className="font-medium text-slate-200">{vision?.chart_pattern ?? '--'}</span>
                </div>
                <div className="flex justify-between items-center bg-slate-900/40 px-3 py-1.5 rounded-lg">
                  <span className="text-slate-400">Support / Resistance:</span>
                  <span className="font-mono text-slate-300 text-[11px]">
                    ${vision?.key_support ? Number(vision.key_support).toFixed(0) : '--'} / ${vision?.key_resistance ? Number(vision.key_resistance).toFixed(0) : '--'}
                  </span>
                </div>
              </div>
            )}
          </div>

        </div>

        {/* Bottom Section: Pine Script Strategy Injector */}
        <div className="p-4 rounded-xl bg-slate-800/40 border border-slate-700/40 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
              <Code size={14} className="text-blue-400" /> Pine Script Strategy Injector (v5)
            </span>
            <span className="text-[10px] text-slate-500">Syntax validated before CDP commit</span>
          </div>

          <textarea
            value={pineCode}
            onChange={(e) => setPineCode(e.target.value)}
            rows={4}
            className="w-full p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono text-emerald-400 focus:outline-none focus:border-blue-500/50 transition-colors"
            placeholder="Write Pine Script here..."
          />

          <div className="flex items-center justify-between">
            {injectMessage ? (
              <div className={`flex items-center gap-1.5 text-xs font-medium ${injectSuccess ? 'text-emerald-400' : 'text-rose-400'}`}>
                {injectSuccess ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
                {injectMessage}
              </div>
            ) : <div />}

            <button
              onClick={handleInjectPineScript}
              disabled={injecting}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold flex items-center gap-2 transition-all shadow-md shadow-blue-600/20 disabled:opacity-50"
            >
              {injecting ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
              Inject to TradingView Desktop
            </button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
