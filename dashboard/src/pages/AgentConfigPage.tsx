import React, { useCallback, useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
import { cx } from '../utils/cx';
import { Bot, Zap, ShieldAlert, Cpu, Activity, Save, Loader2, CheckCircle2 } from 'lucide-react';
import { useConfig } from '../hooks/useApi';
import { api } from '../services/api';

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

// Agent strategies derived from config flags
const STRATEGIES = [
  { id: 'enable_execution_optimizer', name: 'Execution Optimizer', desc: 'AI-powered VWAP timing, DCA, and ATR-based stop placement.', icon: Zap, color: 'text-amber-500', bg: 'bg-amber-500/10' },
  { id: 'scheduler.auto_execute', name: 'Auto-Execute Decisions', desc: 'Automatically execute approved trade decisions without manual confirmation.', icon: Activity, color: 'text-blue-500', bg: 'bg-blue-500/10' },
  { id: 'risk_controls.kill_switch_enabled', name: 'Kill Switch (Risk Guard)', desc: 'Automatically halt trading when drawdown exceeds configured limits.', icon: ShieldAlert, color: 'text-rose-500', bg: 'bg-rose-500/10' },
  { id: 'realtime.enabled', name: 'Realtime Price Monitor', desc: 'Continuous price polling for auto stop-loss exits.', icon: Cpu, color: 'text-purple-500', bg: 'bg-purple-500/10' },
];

export const AgentConfigPage: React.FC = () => {
  const { data: configData, loading, refetch } = useConfig();
  const config = configData?.config ?? {};

  // Local state mirrors the config for optimistic UI
  const [localConfig, setLocalConfig] = useState<Record<string, any>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);

  // Sync local state when config loads
  useEffect(() => {
    if (config && Object.keys(config).length > 0) {
      setLocalConfig(config);
    }
  }, [JSON.stringify(config)]);

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
      await api.updateConfig(localConfig);
      await refetch();
      setSaved(true);
      setHasChanges(false);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      console.error('Failed to save config:', e);
    } finally {
      setSaving(false);
    }
  }, [localConfig, refetch]);

  if (loading && Object.keys(localConfig).length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400 gap-2">
        <Loader2 className="animate-spin" size={20} /> Loading configuration…
      </div>
    );
  }

  const execution = localConfig.execution ?? {};
  const riskControls = localConfig.risk_controls ?? {};
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
                </Card>
              )
            })}
          </div>

          {/* Execution Config */}
          <Card className="bg-slate-900/50 border-slate-800">
            <CardHeader className="py-4 border-b border-slate-800/50">
              <CardTitle className="text-base">Execution Settings</CardTitle>
            </CardHeader>
            <CardContent className="p-6 flex flex-col gap-5">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-slate-300 mb-2">Execution Mode</label>
                  <select 
                    value={execution.mode ?? 'disabled'}
                    onChange={(e) => setNestedValue('execution.mode', e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 text-slate-200 text-sm rounded-md p-2.5 outline-none focus:border-blue-500"
                  >
                    <option value="disabled">Disabled</option>
                    <option value="paper">Paper Trading</option>
                    <option value="live">Live Trading</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-300 mb-2">Broker</label>
                  <select 
                    value={execution.broker ?? 'paper'}
                    onChange={(e) => setNestedValue('execution.broker', e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 text-slate-200 text-sm rounded-md p-2.5 outline-none focus:border-blue-500"
                  >
                    <option value="paper">Paper (Simulated)</option>
                    <option value="ccxt">CCXT (Crypto Exchange)</option>
                    <option value="alpaca">Alpaca (Stocks)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-slate-300 mb-2">Exchange</label>
                  <select 
                    value={execution.exchange ?? 'binance'}
                    onChange={(e) => setNestedValue('execution.exchange', e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 text-slate-200 text-sm rounded-md p-2.5 outline-none focus:border-blue-500"
                  >
                    <option value="binance">Binance</option>
                    <option value="bybit">Bybit</option>
                    <option value="okx">OKX</option>
                    <option value="coinbase">Coinbase</option>
                    <option value="kraken">Kraken</option>
                    <option value="kucoin">KuCoin</option>
                    <option value="gateio">Gate.io</option>
                    <option value="alpaca">Alpaca (Stocks)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-300 mb-2">Min Confidence</label>
                  <div className="flex items-center gap-3">
                    <input 
                      type="range" min="0.1" max="1.0" step="0.05"
                      value={execution.min_confidence ?? 0.5}
                      onChange={(e) => setNestedValue('execution.min_confidence', Number(e.target.value))}
                      className="flex-1 h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-blue-500"
                    />
                    <span className="text-sm font-mono font-bold text-blue-400 w-12 text-right">
                      {((execution.min_confidence ?? 0.5) * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

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

        {/* RIGHT COLUMN: Risk Parameters */}
        <div className="col-span-12 lg:col-span-5 flex flex-col gap-6">
          <Card className="bg-slate-900/50 border-slate-800">
            <CardHeader className="py-4 border-b border-slate-800/50">
              <CardTitle className="text-base flex items-center gap-2">
                <ShieldAlert size={18} className="text-rose-500" />
                Global Risk Parameters
              </CardTitle>
            </CardHeader>
            <CardContent className="p-6 flex flex-col gap-6">
               
               {/* Max Daily Loss */}
               <div>
                  <div className="flex justify-between items-center mb-2">
                    <label className="text-sm font-semibold text-slate-300">Max Daily Loss</label>
                    <span className="text-sm font-mono font-bold text-rose-400">-{((riskControls.max_daily_loss_pct ?? 0.05) * 100).toFixed(0)}%</span>
                  </div>
                  <input 
                    type="range" min="0.01" max="0.20" step="0.01" 
                    value={riskControls.max_daily_loss_pct ?? 0.05} 
                    onChange={(e) => setNestedValue('risk_controls.max_daily_loss_pct', Number(e.target.value))}
                    className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-rose-500"
                  />
                  <div className="flex justify-between text-xs text-slate-500 mt-2 font-mono">
                    <span>-1%</span><span>-10%</span><span>-20%</span>
                  </div>
               </div>

               {/* Max Position */}
               <div>
                  <div className="flex justify-between items-center mb-2">
                    <label className="text-sm font-semibold text-slate-300">Max Position Size</label>
                    <span className="text-sm font-mono font-bold text-blue-400">{((riskControls.max_position_pct ?? 0.10) * 100).toFixed(0)}%</span>
                  </div>
                  <input 
                    type="range" min="0.01" max="0.50" step="0.01" 
                    value={riskControls.max_position_pct ?? 0.10} 
                    onChange={(e) => setNestedValue('risk_controls.max_position_pct', Number(e.target.value))}
                    className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-blue-500"
                  />
               </div>

               {/* Max Concurrent Positions */}
               <div>
                  <div className="flex justify-between items-center mb-2">
                    <label className="text-sm font-semibold text-slate-300">Max Concurrent Positions</label>
                    <span className="text-sm font-mono font-bold text-slate-200">{riskControls.max_concurrent_positions ?? 5}</span>
                  </div>
                  <input 
                    type="range" min="1" max="20" step="1" 
                    value={riskControls.max_concurrent_positions ?? 5} 
                    onChange={(e) => setNestedValue('risk_controls.max_concurrent_positions', Number(e.target.value))}
                    className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-blue-500"
                  />
               </div>

               {/* Trailing Stop */}
               <div>
                  <div className="flex justify-between items-center mb-2">
                    <label className="text-sm font-semibold text-slate-300">Trailing Stop</label>
                    <span className="text-sm font-mono font-bold text-amber-400">{((riskControls.trailing_stop_pct ?? 0.05) * 100).toFixed(0)}%</span>
                  </div>
                  <input 
                    type="range" min="0" max="0.20" step="0.01" 
                    value={riskControls.trailing_stop_pct ?? 0.05} 
                    onChange={(e) => setNestedValue('risk_controls.trailing_stop_pct', Number(e.target.value))}
                    className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-amber-500"
                  />
               </div>

            </CardContent>
          </Card>

          <Card className="bg-slate-900/50 border-slate-800">
            <CardHeader className="py-4 border-b border-slate-800/50">
              <CardTitle className="text-base">Advanced Fine-Tuning</CardTitle>
            </CardHeader>
            <CardContent className="p-6">
               <ul className="flex flex-col gap-5">
                 <li className="flex items-center justify-between">
                   <div>
                     <p className="font-semibold text-slate-200 text-sm">Sandbox / Testnet Mode</p>
                     <p className="text-xs text-slate-500 mt-0.5">Use exchange testnet for live broker.</p>
                   </div>
                   <Toggle enabled={!!execution.sandbox} onChange={(v) => setNestedValue('execution.sandbox', v)} />
                 </li>
                 <li className="flex items-center justify-between">
                   <div>
                     <p className="font-semibold text-slate-200 text-sm">Require Trade Confirmation</p>
                     <p className="text-xs text-slate-500 mt-0.5">Manual confirm before executing live orders.</p>
                   </div>
                   <Toggle enabled={!!execution.require_confirmation} onChange={(v) => setNestedValue('execution.require_confirmation', v)} />
                 </li>
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
