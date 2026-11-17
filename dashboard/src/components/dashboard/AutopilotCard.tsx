import React, { useState } from 'react';
import { Card, CardContent } from '../ui/Card';
import { cx } from '../../utils/cx';
import { useAutopilot } from '../../hooks/useApi';
import { startAutopilot, pauseAutopilot, resumeAutopilot, analyzeNow } from '../../services/api';
import type { AutopilotStatus } from '../../services/api';
import { Bot, Pause, Play, Zap, Loader2, ShieldAlert } from 'lucide-react';

const REASONS: Record<string, string> = {
  target_profit: 'Target profit tercapai',
  max_loss: 'Batas rugi tercapai',
  end_at: 'Waktu selesai',
};

const fmtLeft = (s: number | null) => {
  if (s === null) return null;
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d > 0 ? `${d}h ${h}j` : h > 0 ? `${h}j ${m}m` : `${m}m`;
};

const toIsoOrNull = (local: string) => (local ? new Date(local).toISOString() : null);

export const AutopilotCard: React.FC<{ className?: string }> = ({ className }) => {
  const { data: st, error, refetch } = useAutopilot();
  const [showForm, setShowForm] = useState(false);
  const [profit, setProfit] = useState('10');
  const [loss, setLoss] = useState('5');
  const [endAt, setEndAt] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [analyzeTicker, setAnalyzeTicker] = useState('');

  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true); setMsg(null);
    try { await fn(); if (ok) setMsg(ok); await refetch(); }
    catch (e) { setMsg(e instanceof Error ? e.message : 'Gagal'); }
    finally { setBusy(false); }
  };

  const onStart = () => {
    const goals = {
      target_profit_pct: profit ? Number(profit) : null,
      max_loss_pct: loss ? Number(loss) : null,
      end_at: toIsoOrNull(endAt),
    };
    if (goals.target_profit_pct === null && goals.max_loss_pct === null && goals.end_at === null) {
      setMsg('Isi minimal satu target agar AI tidak berjalan tanpa akhir.');
      return;
    }
    run(() => startAutopilot(goals), 'Autopilot dimulai').then(() => setShowForm(false));
  };

  if (error && !st) {
    return <Card className={className}><CardContent className="p-5 text-sm text-slate-400">Autopilot tidak tersedia: {error}</CardContent></Card>;
  }
  if (!st) return <Card className={className}><CardContent className="p-5 text-sm text-slate-500">Memuat autopilot…</CardContent></Card>;

  const badge: Record<AutopilotStatus['state'], string> = {
    running: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    paused: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    stopped: 'bg-slate-700/40 text-slate-300 border-slate-600/40',
  };
  const label = { running: 'BERJALAN', paused: 'DIJEDA', stopped: 'SELESAI' }[st.state];
  const g = st.goals, pr = st.progress;
  const left = fmtLeft(pr.seconds_left);
  const ticker = analyzeTicker || st.watchlist[0] || '';

  return (
    <Card className={cx('bg-slate-900/50 border-slate-800', className)}>
      <CardContent className="p-5 flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-500/15 text-blue-400 border border-blue-500/30"><Bot size={18} /></div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-slate-100">AI Autopilot</span>
                <span className={cx('px-2 py-0.5 rounded-full text-[10px] font-bold border', badge[st.state])}>{label}</span>
              </div>
              <div className="text-xs text-slate-400 mt-0.5">
                {st.market} · {st.mode.toUpperCase()}
                {st.running_ticker && <span className="text-blue-400"> · menganalisis {st.running_ticker}…</span>}
                {st.state === 'stopped' && st.stopped_reason && <span className="text-amber-400"> · {REASONS[st.stopped_reason] ?? st.stopped_reason}</span>}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {st.state === 'running' && (
              <button disabled={busy} onClick={() => run(pauseAutopilot)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-bold border border-slate-700 bg-slate-800/50 text-slate-200 hover:bg-slate-700">
                <Pause size={13} /> Jeda
              </button>
            )}
            {st.state === 'paused' && (
              <button disabled={busy} onClick={() => run(resumeAutopilot)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-bold border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20">
                <Play size={13} /> Lanjut
              </button>
            )}
            {st.state !== 'running' && (
              <button disabled={busy} onClick={() => setShowForm(v => !v)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-bold border border-blue-500/40 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20">
                <Zap size={13} /> {st.state === 'stopped' ? 'Mulai ulang' : 'Mulai baru'}
              </button>
            )}
            {st.watchlist.length > 0 && (
              <div className="flex items-center gap-1">
                <select value={ticker} onChange={e => setAnalyzeTicker(e.target.value)} className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-md px-2 py-1.5">
                  {st.watchlist.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
                <button disabled={busy || !ticker} onClick={() => run(() => analyzeNow(ticker), `Analisis ${ticker} dimulai`)} className="px-3 py-1.5 rounded-md text-xs font-bold border border-slate-700 bg-slate-800/50 text-slate-200 hover:bg-slate-700 disabled:opacity-50">
                  {busy ? <Loader2 size={13} className="animate-spin" /> : 'Analisis sekarang'}
                </button>
              </div>
            )}
          </div>
        </div>

        {showForm && (
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 p-3 rounded-lg bg-slate-950/50 border border-slate-800">
            <label className="text-xs text-slate-400">Target profit (%)
              <input value={profit} onChange={e => setProfit(e.target.value)} type="number" min="0" step="0.5" className="mt-1 w-full bg-slate-900 border border-slate-700 rounded-md px-2 py-1.5 text-slate-100 text-sm" />
            </label>
            <label className="text-xs text-slate-400">Batas rugi (%)
              <input value={loss} onChange={e => setLoss(e.target.value)} type="number" min="0" step="0.5" className="mt-1 w-full bg-slate-900 border border-slate-700 rounded-md px-2 py-1.5 text-slate-100 text-sm" />
            </label>
            <label className="text-xs text-slate-400">Selesai pada (opsional)
              <input value={endAt} onChange={e => setEndAt(e.target.value)} type="datetime-local" className="mt-1 w-full bg-slate-900 border border-slate-700 rounded-md px-2 py-1.5 text-slate-100 text-sm" />
            </label>
            <div className="flex items-end">
              <button disabled={busy} onClick={onStart} className="w-full px-3 py-2 rounded-md text-xs font-bold bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50">Mulai autopilot</button>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div><div className="text-slate-500">Perubahan equity</div>
            <div className={cx('font-mono font-bold text-sm', (pr.change_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
              {pr.change_pct === null ? '—' : `${pr.change_pct >= 0 ? '+' : ''}${pr.change_pct.toFixed(2)}%`}</div></div>
          <div><div className="text-slate-500">Target / batas rugi</div>
            <div className="font-mono text-slate-200 text-sm">{g.target_profit_pct ? `+${g.target_profit_pct}%` : '—'} / {g.max_loss_pct ? `-${g.max_loss_pct}%` : '—'}</div></div>
          <div><div className="text-slate-500">Sisa waktu</div><div className="font-mono text-slate-200 text-sm">{left ?? '—'}</div></div>
          <div><div className="text-slate-500">Interval</div><div className="font-mono text-slate-200 text-sm">{st.interval_minutes} menit</div></div>
        </div>

        {st.tickers.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {st.tickers.map(t => (
              <span key={t.ticker} className="px-2 py-1 rounded-md text-[11px] bg-slate-800/60 border border-slate-700/50 text-slate-300">
                <b>{t.ticker}</b> · {t.market_open ? 'pasar buka' : 'pasar tutup'}
                {t.last_run_at && ` · terakhir ${new Date(t.last_run_at).toLocaleTimeString()}`}
              </span>
            ))}
          </div>
        )}

        {st.require_confirmation && st.state !== 'stopped' && (
          <div className="flex items-center gap-2 text-[11px] text-amber-300">
            <ShieldAlert size={13} /> Order menunggu persetujuan Anda (mode konfirmasi aktif).
          </div>
        )}
        {st.last_error && <div className="text-[11px] text-rose-400">Error loop terakhir: {st.last_error}</div>}
        {msg && <div className="text-[11px] text-slate-300">{msg}</div>}
      </CardContent>
    </Card>
  );
};
