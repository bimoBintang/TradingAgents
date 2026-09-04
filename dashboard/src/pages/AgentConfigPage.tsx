import React, { useCallback, useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
import { cx } from '../utils/cx';
import { Bot, Zap, Cpu, Activity, Save, Loader2, CheckCircle2 } from 'lucide-react';
import { useConfig } from '../hooks/useApi';
import { api } from '../services/api';
import { diffConfig } from '../utils/configDiff';

const Toggle: React.FC<{ enabled: boolean; onChange: (v: boolean) => void }> = ({ enabled, onChange }) => (
  <button 
    onClick={() => onChange(!enabled)}
    className={cx(
      "relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900",
      enabled ? "bg-blue-600" : "bg-slate-700"
    )}
    role="switch"
    aria-checked={enabled}
  >
    <span className="sr-only">Use setting</span>
    <span 
      aria-hidden="true" 
      className={cx(
        "pointer-events-none absolute left-[2px] h-4 w-4 rounded-full bg-white shadow ring-0 transition-transform duration-200 ease-in-out",
        enabled ? "translate-x-4" : "translate-x-0"
      )} 
    />
  </button>
);

// Agent strategies derived from config flags.
// Kill Switch used to be listed here too (risk_controls.kill_switch_enabled)
// — removed as a duplicate editor of Settings > Risk Controls > Automated
// Kill Switch, which is the more complete version (also sets the
// consecutive-loss cooldown). Editing the SAME field from two independent
// pages was exactly the kind of redundancy diffConfig's cross-page fix
// exists to survive, but survivable isn't the same as needed — one editor
// per field is simpler and removes any doubt about which page is "current".
const STRATEGIES = [
  { id: 'enable_execution_optimizer', name: 'Execution Optimizer', desc: 'AI-powered VWAP timing, DCA, and ATR-based stop placement.', icon: Zap, color: 'text-amber-500', bg: 'bg-amber-500/10' },
  { id: 'scheduler.auto_execute', name: 'Auto-Execute Decisions', desc: 'Automatically execute approved trade decisions without manual confirmation.', icon: Activity, color: 'text-blue-500', bg: 'bg-blue-500/10' },
  { id: 'realtime.enabled', name: 'Realtime Price Monitor', desc: 'Continuous price polling for auto stop-loss exits.', icon: Cpu, color: 'text-purple-500', bg: 'bg-purple-500/10' },
];

export const AgentConfigPage: React.FC = () => {
  const { data: configData, loading, refetch } = useConfig();
  const config = configData?.config ?? {};

  // Local state mirrors the config for optimistic UI
  const [localConfig, setLocalConfig] = useState<Record<string, any>>({});
  // The last-synced server snapshot — diffed against localConfig at save
  // time so only fields actually touched on THIS page get sent (see
  // src/utils/configDiff.ts). Always updated in lockstep with
  // localConfig below, never independently.
  const [baselineConfig, setBaselineConfig] = useState<Record<string, any>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);

  // Sync local state when config loads — but NEVER while the user has
  // unsaved edits (hasChanges). useConfig() polls every 60s; without this
  // guard, a background refresh (someone else's save, the balance-sync
  // job, another browser tab) would silently blow away whatever the user
  // was mid-way through editing here.
  useEffect(() => {
    if (hasChanges) return;
    if (config && Object.keys(config).length > 0) {
      setLocalConfig(config);
      setBaselineConfig(config);
    }
  }, [JSON.stringify(config), hasChanges]);

  const getNestedValue = (obj: Record<string, any>, path: string): any => {
    const parts = path.split('.');
    let val = obj;
    for (const part of parts) {
      val = val?.[part];
    }
    return val;
  };

  const setNestedValue = (path: string, value: any) => {
    setHasChanges(true);
    setLocalConfig(prev => {
      const parts = path.split('.');
      const updated = JSON.parse(JSON.stringify(prev));
      let target = updated;
      for (let i = 0; i < parts.length - 1; i++) {
        if (!target[parts[i]]) target[parts[i]] = {};
        target = target[parts[i]];
      }
      target[parts[parts.length - 1]] = value;
      return updated;
    });
  };

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      // Send only what actually changed on this page — not the whole
      // snapshot (see diffConfig's doc comment for why that matters).
      const updates = diffConfig(baselineConfig, localConfig);
      if (Object.keys(updates).length > 0) {
        await api.updateConfig(updates);
      }
      await refetch();
      setSaved(true);
      setHasChanges(false);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      console.error('Failed to save config:', e);
    } finally {
      setSaving(false);
    }
  }, [localConfig, baselineConfig, refetch]);

  if (loading && Object.keys(localConfig).length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400 gap-2">
        <Loader2 className="animate-spin" size={20} /> Loading configuration…
      </div>
    );
  }

  const execution = localConfig.execution ?? {};
  const portfolio = localConfig.portfolio ?? {};
  const scheduler = localConfig.scheduler ?? {};

  return (
    <div className="flex flex-col gap-6 h-full pb-8">
      
      {/* Header / Action Bar */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-slate-900/40 p-5 rounded-2xl border border-slate-800/50">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2 text-slate-100">
            <Bot className="text-blue-500" /> Agent Orchestrator
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Configure AI trading agents and global risk parameters.
            <span className="text-xs text-slate-600 ml-2">
              Mode: <span className="text-blue-400 font-mono">{execution.mode ?? 'disabled'}</span> | Broker: <span className="text-blue-400 font-mono">{execution.broker ?? 'paper'}</span>
            </span>
          </p>
        </div>
        <button 
          onClick={handleSave}
          disabled={saving || !hasChanges}
          className={cx(
            "flex items-center gap-2 px-4 py-2 text-sm font-bold rounded-lg transition-all",
            hasChanges
              ? "bg-blue-600 hover:bg-blue-700 text-white shadow-[0_0_15px_rgba(37,99,235,0.4)]" 
              : saved 
                ? "bg-emerald-600 text-white"
                : "bg-slate-800 text-slate-500 cursor-not-allowed"
          )}
        >
          {saving ? <Loader2 size={16} className="animate-spin" /> : saved ? <CheckCircle2 size={16} /> : <Save size={16} />}
          {saving ? 'Saving…' : saved ? 'Saved!' : hasChanges ? 'Save & Deploy' : 'No Changes'}
        </button>
      </div>

      <div className="grid grid-cols-12 gap-6 flex-1">
        
        {/* LEFT COLUMN: Strategies */}
        <div className="col-span-12 lg:col-span-7 flex flex-col gap-6">
          <h3 className="text-lg font-bold text-slate-200 flex items-center gap-2">
            Active Strategies & Modules
          </h3>
          
          <div className="flex flex-col gap-4">
            {STRATEGIES.map((strat) => {
              const isActive = !!getNestedValue(localConfig, strat.id);
              const Icon = strat.icon;
              return (
                <Card 
                  key={strat.id} 
                  className={cx(
                    "transition-all duration-300 border-2 overflow-hidden",
                    isActive ? "bg-slate-900/80 border-blue-500/50 shadow-[0_0_20px_rgba(37,99,235,0.1)]" : "bg-slate-950/50 border-slate-800/50 opacity-70 hover:opacity-100 grayscale hover:grayscale-0"
                  )}
                >
                  <CardContent className="p-5 flex flex-col sm:flex-row gap-5 items-start sm:items-center justify-between">
                    <div className="flex items-center gap-4">
                       <div className={cx("w-12 h-12 rounded-xl flex items-center justify-center", strat.bg, strat.color)}>
                         <Icon size={24} />
                       </div>
                       <div>
                         <h4 className="font-bold text-slate-100 text-base">{strat.name}</h4>
                         <p className="text-sm text-slate-400 max-w-sm mt-0.5">{strat.desc}</p>
                       </div>
                    </div>
                    
                    <div className="flex items-center gap-6 w-full sm:w-auto mt-4 sm:mt-0 px-2 sm:px-0">
                      <div className="flex flex-col justify-center items-center">
                        <Toggle enabled={isActive} onChange={(v) => setNestedValue(strat.id, v)} />
                        <span className="text-[10px] font-bold text-slate-500 mt-1">{isActive ? 'ACTIVE' : 'OFF'}</span>
                      </div>
                    </div>
                  </CardContent>
                  {/* Auto-Execute has ZERO effect while Require Trade
                      Confirmation is on — execution_engine.py checks
                      require_confirmation FIRST and blocks execution
                      before auto_execute is ever consulted. Surface that
                      dependency here instead of letting the toggle look
                      like it's working when it silently isn't. */}
                  {strat.id === 'scheduler.auto_execute' && isActive && !!execution.require_confirmation && (
                    <div className="px-5 pb-4 -mt-1">
                      <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-xs text-amber-400">
                        <span className="font-bold shrink-0">⚠️ No effect yet:</span>
                        <span>
                          "Require Manual Confirmation" (Settings → Execution & Order Flow) is ON and blocks every
                          execution before Auto-Execute is ever checked. Turn that off too if you want trades to
                          execute automatically.
                        </span>
                      </div>
                    </div>
                  )}
                </Card>
              )
            })}
          </div>

          {/* Scheduler */}
          <Card className="bg-slate-900/50 border-slate-800">
            <CardHeader className="py-4 border-b border-slate-800/50">
              <CardTitle className="text-base">Scheduler / Watchlist</CardTitle>
            </CardHeader>
            <CardContent className="p-6 flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-semibold text-slate-200 text-sm">Enable Autonomous Scheduler</p>
                  <p className="text-xs text-slate-500 mt-0.5">Run analysis on a fixed interval automatically.</p>
                </div>
                <Toggle enabled={!!scheduler.enabled} onChange={(v) => setNestedValue('scheduler.enabled', v)} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-slate-300 mb-2">Interval (minutes)</label>
                  <input 
                    type="number" min="5" max="1440" step="5"
                    value={scheduler.interval_minutes ?? 60}
                    onChange={(e) => setNestedValue('scheduler.interval_minutes', Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-800 text-slate-200 text-sm rounded-md p-2.5 outline-none focus:border-blue-500 font-mono"
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-300 mb-2">Max Trades / Day</label>
                  <input 
                    type="number" min="1" max="100" step="1"
                    value={scheduler.max_trades_per_day ?? 10}
                    onChange={(e) => setNestedValue('scheduler.max_trades_per_day', Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-800 text-slate-200 text-sm rounded-md p-2.5 outline-none focus:border-blue-500 font-mono"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-semibold text-slate-300 mb-2">Watchlist (comma-separated)</label>
                <input 
                  type="text"
                  value={(scheduler.watchlist ?? []).join(', ')}
                  onChange={(e) => setNestedValue('scheduler.watchlist', e.target.value.split(',').map((s: string) => s.trim()).filter(Boolean))}
                  placeholder="NVDA, BTC-USD, ETH-USD"
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 text-sm rounded-md p-2.5 outline-none focus:border-blue-500 font-mono"
                />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* RIGHT COLUMN: Scheduler Behavior & Portfolio */}
        <div className="col-span-12 lg:col-span-5 flex flex-col gap-6">
          {/* Max Daily Loss / Max Position / Max Concurrent Positions /
              Trailing Stop, and the Sandbox + Require Trade Confirmation
              toggles, used to be duplicated here — removed. They're fully
              covered (and more completely: Settings' Risk tab also has
              consecutive-loss cooldown and max weekly loss; Settings' API
              tab pairs broker+exchange atomically and gates going live
              with a confirmation dialog, neither of which this page ever
              had) by Settings > Risk Controls and Settings > API
              Management. One editor per field beats two that can silently
              disagree. */}
          <Card className="bg-slate-900/50 border-slate-800">
            <CardHeader className="py-4 border-b border-slate-800/50">
              <CardTitle className="text-base">Scheduler Behavior</CardTitle>
            </CardHeader>
            <CardContent className="p-6">
               <ul className="flex flex-col gap-5">
                 <li className="flex items-center justify-between">
                   <div>
                     <p className="font-semibold text-slate-200 text-sm">Crypto 24/7 Trading</p>
                     <p className="text-xs text-slate-500 mt-0.5">Allow crypto tickers to run outside market hours.</p>
                   </div>
                   <Toggle enabled={!!scheduler.crypto_24_7} onChange={(v) => setNestedValue('scheduler.crypto_24_7', v)} />
                 </li>
                 <li className="flex items-center justify-between">
                   <div>
                     <p className="font-semibold text-slate-200 text-sm">Market Hours Only</p>
                     <p className="text-xs text-slate-500 mt-0.5">Skip analysis outside NYSE hours.</p>
                   </div>
                   <Toggle enabled={!!scheduler.market_hours_only} onChange={(v) => setNestedValue('scheduler.market_hours_only', v)} />
                 </li>
               </ul>
            </CardContent>
          </Card>

          {/* Portfolio */}
          <Card className="bg-slate-900/50 border-slate-800">
            <CardHeader className="py-4 border-b border-slate-800/50">
              <CardTitle className="text-base">Portfolio Sizing</CardTitle>
            </CardHeader>
            <CardContent className="p-6 flex flex-col gap-4">
              <div>
                <label className="block text-sm font-semibold text-slate-300 mb-2">Initial Cash</label>
                <input 
                  type="number" min="100" step="100"
                  value={portfolio.initial_cash ?? 10000}
                  onChange={(e) => setNestedValue('portfolio.initial_cash', Number(e.target.value))}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 text-sm rounded-md p-2.5 outline-none focus:border-blue-500 font-mono"
                />
              </div>
              <div>
                <label className="block text-sm font-semibold text-slate-300 mb-2">Max Total Positions</label>
                <input 
                  type="number" min="1" max="50" step="1"
                  value={portfolio.max_total_positions ?? 10}
                  onChange={(e) => setNestedValue('portfolio.max_total_positions', Number(e.target.value))}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 text-sm rounded-md p-2.5 outline-none focus:border-blue-500 font-mono"
                />
              </div>
            </CardContent>
          </Card>
        </div>

      </div>
    </div>
  );
};
