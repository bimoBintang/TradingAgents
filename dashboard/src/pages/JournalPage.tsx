import React, { useState, useMemo, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
import { PnLHeatmap } from '../components/dashboard/PnLHeatmap';
import { ProfitCalendar } from '../components/dashboard/ProfitCalendar';
import { EquityCurveChart } from '../components/dashboard/EquityCurveChart';
import { useTrades, usePortfolio, usePerformance, useJournalNote, useJournalHistory } from '../hooks/useApi';
import { api } from '../services/api';
import { Download, Loader2, Check } from 'lucide-react';

export const JournalPage: React.FC = () => {
  const [csvLoading, setCsvLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  
  const today = new Date().toISOString().split('T')[0];
  const [selectedDate, setSelectedDate] = useState(today);
  
  const { data: noteData, loading: noteLoading, mutate } = useJournalNote(selectedDate);
  const { data: historyData, loading: historyLoading, mutate: mutateHistory } = useJournalHistory();
  const [noteText, setNoteText] = useState('');

  // Sync state when data loads or date changes
  useEffect(() => {
    if (noteData && !noteLoading) {
      setNoteText(noteData.content || '');
    } else if (!noteData && !noteLoading) {
      setNoteText('');
    }
  }, [noteData, noteLoading, selectedDate]);

  // Combine history + today
  const datesList = useMemo(() => {
    const list = historyData ? [...historyData] : [];
    // If today is not in the list, pad it
    if (!list.find(x => x.date === today)) {
      list.unshift({ id: 0, date: today, content: '' });
    }
    // Sort descending by date
    return list.sort((a, b) => b.date.localeCompare(a.date));
  }, [historyData, today]);

  const { data: trades } = useTrades();
  const { data: portfolio, loading } = usePortfolio();
  const { data: perf, loading: perfLoading } = usePerformance();

  const fmt = (n: number) => n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const handleExportCSV = async () => {
    try {
      setCsvLoading(true);
      await api.exportCSV();
    } catch (err) {
      console.error('CSV export failed:', err);
    } finally {
      setCsvLoading(false);
    }
  };

  const handleSaveNote = async () => {
    if (saveStatus === 'saving') return;
    try {
      setSaveStatus('saving');
      await api.saveNote(selectedDate, noteText);
      await mutate();
      if (mutateHistory) await mutateHistory();
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
    } catch (err) {
      console.error('Note save failed:', err);
      setSaveStatus('idle');
    }
  };

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
        <EquityCurveChart className="col-span-12 lg:col-span-8 min-h-[320px]" />
        <PnLHeatmap className="col-span-12 lg:col-span-4 min-h-[320px]" />
      </div>

      {/* Monthly Profit Calendar */}
      <div className="grid grid-cols-12 gap-6">
        <ProfitCalendar className="col-span-12" />
      </div>

      {/* Export Row */}
      <div className="flex justify-end">
        <button
          onClick={handleExportCSV}
          disabled={csvLoading}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold border transition-all disabled:opacity-50 bg-slate-800/50 border-slate-700 text-slate-300 hover:bg-slate-700/50 hover:text-white"
        >
          {csvLoading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
          {csvLoading ? 'Exporting...' : 'Export CSV'}
        </button>
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

      {/* Professional Daily Notes: Split View */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 flex-1 min-h-[400px]">
        
        {/* Sidebar: History */}
        <Card className="bg-slate-900/50 flex flex-col border border-slate-800/50">
          <CardHeader className="py-4 border-b border-slate-800/50 flex justify-between items-center">
            <CardTitle className="text-sm flex items-center gap-2">
              📅 History
            </CardTitle>
            <button
              onClick={() => { setSelectedDate(today); setNoteText(''); }}
              className="px-2 py-1 bg-slate-800 text-xs text-white rounded hover:bg-slate-700 transition"
              title="New entry for today"
            >
              + Today
            </button>
          </CardHeader>
          <CardContent className="p-0 flex-1 overflow-y-auto max-h-[400px]">
            {historyLoading && <div className="p-4 text-xs text-slate-500 flex items-center gap-2"><Loader2 size={12} className="animate-spin" /> Loading history...</div>}
            
            {!historyLoading && datesList.length === 0 && (
              <div className="p-4 text-xs text-slate-500">No notes yet. Start writing!</div>
            )}
            
            <div className="flex flex-col">
              {datesList.map(item => (
                <button
                  key={item.date}
                  onClick={() => setSelectedDate(item.date)}
                  className={`p-4 border-b border-slate-800/30 text-left transition-colors flex flex-col gap-1 
                    ${selectedDate === item.date ? 'bg-blue-600/10 border-l-2 border-l-blue-500' : 'hover:bg-slate-800/30 border-l-2 border-l-transparent'}`}
                >
                  <div className="text-sm font-bold text-slate-300 flex items-center gap-2">
                    {item.date === today ? 'Today' : item.date}
                  </div>
                  {item.content && (
                    <div className="text-xs text-slate-500 truncate max-w-full font-mono">
                      {item.content.substring(0, 50)}...
                    </div>
                  )}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Editor: Active Note */}
        <Card className="col-span-1 lg:col-span-3 bg-slate-900/50 flex flex-col border border-slate-800/50">
          <CardHeader className="py-4 border-b border-slate-800/50 flex justify-between flex-row items-center">
             <CardTitle className="text-base flex items-center gap-2">
               📓 Daily Trading Journal <span className="text-xs font-normal text-slate-400 ml-2">({selectedDate})</span>
             </CardTitle>
             <button 
               onClick={handleSaveNote}
               disabled={saveStatus === 'saving' || noteLoading}
               className={`px-3 py-1 flex items-center gap-2 text-white rounded text-xs font-bold transition-colors ${saveStatus === 'saved' ? 'bg-emerald-600' : 'bg-blue-600 hover:bg-blue-700'}`}
             >
               {saveStatus === 'saving' ? <><Loader2 size={14} className="animate-spin" /> Saving...</> : saveStatus === 'saved' ? <><Check size={14} /> Saved</> : 'Save Entry'}
             </button>
          </CardHeader>
          <CardContent className="p-0 flex-1 flex flex-col relative">
            {noteLoading ? (
              <div className="absolute inset-0 flex items-center justify-center bg-slate-900/50 z-10">
                <Loader2 className="animate-spin text-blue-500" size={32} />
              </div>
            ) : null}
            <textarea 
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="Reflect on today's trading session. Were you disciplined? Did you follow your strategy? What could be improved?"
              className="w-full h-full min-h-[350px] p-6 bg-transparent resize-none outline-none focus:ring-0 text-sm text-slate-300 placeholder:text-slate-600 font-mono leading-relaxed"
            />
          </CardContent>
        </Card>

      </div>

    </div>
  );
};
