import React, { useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { cx } from '../../utils/cx';
import { useDecisions } from '../../hooks/useApi';
import { Brain, ChevronDown, ChevronRight } from 'lucide-react';

const actionClass = (a: string) =>
  a.includes('BUY') ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
  : a.includes('SELL') ? 'bg-rose-500/15 text-rose-400 border-rose-500/30'
  : 'bg-slate-700/40 text-slate-300 border-slate-600/40';

export const AIDecisionsPanel: React.FC<{ className?: string }> = ({ className }) => {
  const { data, loading, error } = useDecisions(20);
  const [open, setOpen] = useState<string | null>(null);

  return (
    <Card className={cx('bg-slate-900/50 flex flex-col border-slate-800', className)}>
      <CardHeader className="py-4 border-b border-slate-800/80 flex flex-row items-center justify-between shrink-0">
        <CardTitle className="text-base flex items-center gap-2.5 font-bold tracking-tight text-slate-100">
          <div className="p-1.5 rounded-md bg-blue-500/20 text-blue-400 border border-blue-500/30"><Brain size={16} /></div>
          Keputusan AI
        </CardTitle>
        <span className="text-[10px] text-slate-500 uppercase tracking-wider">{data.length} terbaru</span>
      </CardHeader>
      <CardContent className="p-0 overflow-y-auto flex-1">
        {error && <div className="p-4 text-xs text-rose-400">{error}</div>}
        {!error && data.length === 0 && (
          <div className="p-8 text-center text-xs text-slate-500">
            {loading ? 'Memuat…' : 'Belum ada keputusan. Mulai autopilot atau jalankan "Analisis sekarang".'}
          </div>
        )}
        <div className="divide-y divide-slate-800/50">
          {data.map(d => {
            const isOpen = open === d.task_id;
            const action = d.decision?.action ?? (d.status === 'failed' ? 'GAGAL' : d.status.toUpperCase());
            const conf = d.decision?.confidence_score;
            return (
              <div key={d.task_id}>
                <button onClick={() => setOpen(isOpen ? null : d.task_id)} className="w-full p-3 flex items-center gap-3 text-left hover:bg-slate-800/30">
                  {isOpen ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
                  <span className="font-bold text-slate-100 text-sm w-24 truncate">{d.ticker}</span>
                  <span className={cx('px-2 py-0.5 rounded-md text-[10px] font-bold border', actionClass(action))}>{action}</span>
                  {conf != null && <span className="text-xs text-slate-400">{Math.round(conf * 100)}%</span>}
                  {d.order_result && <span className="text-[10px] text-emerald-400">tereksekusi</span>}
                  <span className="ml-auto text-[11px] text-slate-500">{d.created_at ? new Date(d.created_at).toLocaleString() : ''}</span>
                </button>
                {isOpen && (
                  <div className="px-10 pb-4 text-xs text-slate-300 flex flex-col gap-2">
                    {d.error && <div className="text-rose-400">{d.error}</div>}
                    {d.decision?.reasoning && <p className="leading-relaxed whitespace-pre-wrap">{d.decision.reasoning}</p>}
                    {d.decision?.key_factors && d.decision.key_factors.length > 0 && (
                      <ul className="list-disc pl-4 text-slate-400">{d.decision.key_factors.map((f, i) => <li key={i}>{f}</li>)}</ul>
                    )}
                    {(d.decision?.stop_loss_pct != null || d.decision?.take_profit_pct != null) && (
                      <div className="text-slate-400">SL {d.decision?.stop_loss_pct ?? '—'}% · TP {d.decision?.take_profit_pct ?? '—'}%</div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
};
