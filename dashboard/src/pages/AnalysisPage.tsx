import React, { useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
import { api } from '../services/api';
import { useAnalysisWS } from '../hooks/useWebSocket';
import { useAnalyzeResult } from '../hooks/useApi';
import {
  Search, Play, Loader2, CheckCircle2, XCircle, Clock,
  TrendingUp, TrendingDown, FileText, BarChart3, Globe, Link2,
  AlertTriangle,
} from 'lucide-react';

const POPULAR_TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'AAPL', 'NVDA', 'TSLA', 'MSFT', 'GOOGL'];

const REPORT_TABS = [
  { key: 'market_report', label: 'Market', icon: BarChart3 },
  { key: 'quant_report', label: 'Quant', icon: FileText },
  { key: 'onchain_report', label: 'On-Chain', icon: Link2 },
  { key: 'macro_geo_report', label: 'Macro', icon: Globe },
  { key: 'correlation_report', label: 'Correlation', icon: TrendingUp },
] as const;

export const AnalysisPage: React.FC = () => {
  const [ticker, setTicker] = useState('BTC-USD');
  const [autoExecute, setAutoExecute] = useState(false);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activeReport, setActiveReport] = useState<string>('market_report');
  const [history, setHistory] = useState<{ taskId: string; ticker: string; time: string }[]>([]);

  // WebSocket for real-time progress
  const { data: wsData, status: wsStatus } = useAnalysisWS(activeTaskId);
  // SWR polling fallback
  const { data: swrData } = useAnalyzeResult(activeTaskId);

  // Normalize data from either source into a common shape
  const rawData: Record<string, any> | null | undefined = wsStatus === 'connected' && wsData ? wsData : swrData;
  const currentStatus: string = rawData?.status ?? 'idle';

  const handleSubmit = async () => {
    if (isSubmitting || !ticker.trim()) return;
    setIsSubmitting(true);
    try {
      const resp = await api.analyze(ticker.toUpperCase(), autoExecute);
      setActiveTaskId(resp.task_id);
      setHistory(prev => [
        { taskId: resp.task_id, ticker: ticker.toUpperCase(), time: new Date().toLocaleTimeString() },
        ...prev.slice(0, 9),
      ]);
    } catch (err) {
      console.error('Analysis submit failed:', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  const statusConfig: Record<string, { icon: React.ReactNode; color: string; label: string; bg: string }> = {
    idle: { icon: <Clock size={16} />, color: 'text-slate-400', label: 'Ready', bg: 'bg-slate-500/10' },
    queued: { icon: <Clock size={16} className="animate-pulse" />, color: 'text-amber-400', label: 'Queued', bg: 'bg-amber-500/10' },
    running: { icon: <Loader2 size={16} className="animate-spin" />, color: 'text-blue-400', label: 'Analyzing...', bg: 'bg-blue-500/10' },
    completed: { icon: <CheckCircle2 size={16} />, color: 'text-emerald-400', label: 'Completed', bg: 'bg-emerald-500/10' },
    failed: { icon: <XCircle size={16} />, color: 'text-rose-400', label: 'Failed', bg: 'bg-rose-500/10' },
    not_found: { icon: <AlertTriangle size={16} />, color: 'text-slate-400', label: 'Not Found', bg: 'bg-slate-500/10' },
  };

  const sc = statusConfig[currentStatus] ?? statusConfig.idle;

  const decision = rawData?.decision;
  const reports = rawData?.reports;
  const orderResult = rawData?.order_result;
  const error = rawData?.error;

  return (
    <div className="flex flex-col gap-6">

      {/* ── Submit Section ─────────────────────────────── */}
      <Card className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50">
        <CardHeader className="py-4 border-b border-slate-800/50">
          <CardTitle className="text-base flex items-center gap-2">
            <Search size={18} className="text-blue-400" />
            Run Analysis
          </CardTitle>
        </CardHeader>
        <CardContent className="p-5">
          <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end">
            {/* Ticker Input */}
            <div className="flex-1 w-full">
              <label className="block text-xs font-semibold text-slate-400 mb-2">Ticker Symbol</label>
              <input
                type="text"
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase())}
                onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
                placeholder="e.g. BTC-USD"
                className="w-full px-4 py-2.5 rounded-lg bg-slate-950/50 border border-slate-700 text-white font-mono placeholder:text-slate-600 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30 transition-all"
              />
              <div className="flex flex-wrap gap-1.5 mt-2">
                {POPULAR_TICKERS.map((t) => (
                  <button
                    key={t}
                    onClick={() => setTicker(t)}
                    className={`px-2 py-0.5 rounded text-[10px] font-bold border transition-all ${
                      ticker === t
                        ? 'bg-blue-500/20 text-blue-400 border-blue-500/30'
                        : 'bg-slate-800/50 text-slate-500 border-slate-700/50 hover:text-slate-300'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>

            {/* Auto-execute Toggle */}
            <div className="flex items-center gap-2 shrink-0">
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoExecute}
                  onChange={(e) => setAutoExecute(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600" />
              </label>
              <span className="text-xs text-slate-400 font-medium">Auto-execute</span>
            </div>

            {/* Submit Button */}
            <button
              onClick={handleSubmit}
              disabled={isSubmitting || !ticker.trim() || currentStatus === 'running'}
              className="shrink-0 flex items-center gap-2 px-5 py-2.5 rounded-lg font-bold text-sm transition-all disabled:opacity-40 disabled:cursor-not-allowed bg-blue-600 hover:bg-blue-700 text-white shadow-[0_0_20px_rgba(37,99,235,0.3)] hover:shadow-[0_0_25px_rgba(37,99,235,0.5)]"
            >
              {isSubmitting ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
              {isSubmitting ? 'Submitting...' : 'Run Analysis'}
            </button>
          </div>
        </CardContent>
      </Card>

      {/* ── Progress Section ──────────────────────────── */}
      {activeTaskId && (
        <Card className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50">
          <CardContent className="p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className={`flex items-center gap-1.5 ${sc.color}`}>
                  {sc.icon}
                  <span className="text-sm font-bold">{sc.label}</span>
                </span>
                <span className="text-xs text-slate-500 font-mono">{activeTaskId.slice(0, 8)}...</span>
              </div>
              {wsStatus === 'connected' && (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-[9px] font-bold">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  LIVE
                </span>
              )}
            </div>

            {/* Progress Bar */}
            <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-1000 ease-out ${
                  currentStatus === 'completed' ? 'w-full bg-emerald-500' :
                  currentStatus === 'failed' ? 'w-full bg-rose-500' :
                  currentStatus === 'running' ? 'w-2/3 bg-blue-500 animate-pulse' :
                  currentStatus === 'queued' ? 'w-1/6 bg-amber-500 animate-pulse' :
                  'w-0'
                }`}
              />
            </div>

            {error && (
              <div className="mt-3 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs">
                {error.includes("Could not resolve authentication method") || error.includes("api_key") ? (
                  <div className="flex flex-col gap-1">
                    <strong className="flex items-center gap-1.5 text-sm"><AlertTriangle size={14}/> Missing API Key</strong>
                    <span className="opacity-90 leading-relaxed font-sans">
                      The AI Provider's API Key is not configured. Please go to <b>System Settings &rarr; AI Language Models</b> to add your API Key before running an analysis.
                    </span>
                  </div>
                ) : (
                  <span className="font-mono">{error}</span>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── Results Section ───────────────────────────── */}
      {currentStatus === 'completed' && decision && (
        <>
          {/* Decision Card */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card className={`backdrop-blur-md border ${
              decision === 'BUY' ? 'bg-emerald-900/20 border-emerald-500/30' :
              decision === 'SELL' ? 'bg-rose-900/20 border-rose-500/30' :
              'bg-slate-900/40 border-slate-700/50'
            }`}>
              <CardContent className="p-5 text-center">
                <div className="text-xs font-semibold text-slate-400 mb-1">Decision</div>
                <div className={`text-3xl font-black ${
                  decision === 'BUY' ? 'text-emerald-400' :
                  decision === 'SELL' ? 'text-rose-400' : 'text-amber-400'
                }`}>
                  {typeof decision === 'string' ? decision : JSON.stringify(decision)}
                </div>
                <div className="flex items-center justify-center gap-1 mt-2">
                  {decision === 'BUY' ? <TrendingUp size={14} className="text-emerald-400" /> : decision === 'SELL' ? <TrendingDown size={14} className="text-rose-400" /> : null}
                </div>
              </CardContent>
            </Card>

            {orderResult && (
              <>
                <Card className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50">
                  <CardContent className="p-5 text-center">
                    <div className="text-xs font-semibold text-slate-400 mb-1">Filled Price</div>
                    <div className="text-2xl font-mono font-bold text-white">
                      ${orderResult.filled_price?.toLocaleString('en-US', { minimumFractionDigits: 2 }) ?? '—'}
                    </div>
                    <div className="text-[10px] text-slate-500 mt-1">{orderResult.ticker} × {orderResult.filled_quantity}</div>
                  </CardContent>
                </Card>
                <Card className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50">
                  <CardContent className="p-5 text-center">
                    <div className="text-xs font-semibold text-slate-400 mb-1">Order Status</div>
                    <div className={`text-xl font-bold ${orderResult.status === 'filled' ? 'text-emerald-400' : 'text-amber-400'}`}>
                      {orderResult.status?.toUpperCase() ?? '—'}
                    </div>
                    <div className="text-[10px] text-slate-500 font-mono mt-1">{orderResult.order_id?.slice(0, 12) ?? ''}</div>
                  </CardContent>
                </Card>
              </>
            )}
          </div>

          {/* Reports Tabs */}
          {reports && (
            <Card className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50">
              <CardHeader className="py-3 border-b border-slate-800/50">
                <div className="flex gap-1 overflow-x-auto scrollbar-hide">
                  {REPORT_TABS.map(({ key, label, icon: Icon }) => (
                    <button
                      key={key}
                      onClick={() => setActiveReport(key)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold whitespace-nowrap transition-all ${
                        activeReport === key
                          ? 'bg-blue-600/15 text-blue-400 border border-blue-500/30'
                          : 'text-slate-500 hover:text-slate-300 border border-transparent'
                      }`}
                    >
                      <Icon size={13} />
                      {label}
                    </button>
                  ))}
                </div>
              </CardHeader>
              <CardContent className="p-5">
                <div className="prose prose-invert prose-sm max-w-none text-slate-300 leading-relaxed whitespace-pre-wrap font-mono text-xs">
                  {reports[activeReport] ?? (
                    <span className="text-slate-600 italic">No data for this report.</span>
                  )}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* ── History ────────────────────────────────────── */}
      {history.length > 0 && (
        <Card className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50">
          <CardHeader className="py-3 border-b border-slate-800/50">
            <CardTitle className="text-sm">Recent Analyses</CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            <div className="flex flex-col gap-2">
              {history.map((h) => (
                <button
                  key={h.taskId}
                  onClick={() => setActiveTaskId(h.taskId)}
                  className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs transition-all border ${
                    activeTaskId === h.taskId
                      ? 'bg-blue-600/10 border-blue-500/30 text-blue-400'
                      : 'bg-slate-950/30 border-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                  }`}
                >
                  <span className="font-bold">{h.ticker}</span>
                  <span className="font-mono text-slate-500">{h.time}</span>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};
