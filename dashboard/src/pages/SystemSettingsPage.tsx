import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
import { cx } from '../utils/cx';
import { Key, Bell, Shield, Brain, Monitor, CheckCircle2, AlertCircle, Loader2, Save, Zap, Cpu, Server, Settings2, Send, Activity, TrendingDown, Calendar, Clock, MessageSquare, Target, ShieldAlert, Crosshair } from 'lucide-react';
import { useConfig } from '../hooks/useApi';
import { api } from '../services/api';

const Toggle: React.FC<{ enabled: boolean; onChange: (v: boolean) => void }> = ({ enabled, onChange }) => (
  <button 
    onClick={() => onChange(!enabled)}
    className={cx(
      "relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full focus:outline-none transition-colors",
      enabled ? "bg-blue-600" : "bg-slate-700"
    )}
  >
    <span 
      className={cx(
        "pointer-events-none absolute left-[2px] h-4 w-4 rounded-full bg-white shadow ring-0 transition-transform duration-200 ease-in-out",
        enabled ? "translate-x-4" : "translate-x-0"
      )} 
    />
  </button>
);

export const SystemSettingsPage: React.FC = () => {
  const [activeMenu, setActiveMenu] = useState('api');
  const { data: configData, loading, refetch } = useConfig();
  const config = configData?.config ?? {};

  const [localConfig, setLocalConfig] = useState<Record<string, any>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Friendly names for models
  const MODEL_LABELS: Record<string, string> = {
    'gpt-4o': 'GPT-4o (Flagship Multimodal)',
    'gpt-4o-mini': 'GPT-4o Mini (Fast & Efficient)',
    'gpt-3.5-turbo': 'GPT-3.5 Turbo (Legacy Fast)',
    'o1-preview': 'o1-Preview (Advanced Reasoning)',
    'o1-mini': 'o1-Mini (Fast Reasoning)',
    'o1': 'o1 (Maximum Reasoning)',
    'claude-3-5-sonnet-latest': 'Claude 3.5 Sonnet (Latest)',
    'claude-3-opus-latest': 'Claude 3 Opus (Heavy Reasoning)',
    'claude-3-5-haiku-latest': 'Claude 3.5 Haiku (Fast Routing)',
    'claude-3-haiku-20240307': 'Claude 3 Haiku (Legacy Fast)',
    'gemini-1.5-pro': 'Gemini 1.5 Pro (Flagship)',
    'gemini-1.5-pro-latest': 'Gemini 1.5 Pro Latest',
    'gemini-1.5-flash': 'Gemini 1.5 Flash (Fast Routing)',
    'gemini-1.5-flash-8b': 'Gemini 1.5 Flash-8B (Ultra Fast)',
  };


  const [hasChanges, setHasChanges] = useState(false);

  useEffect(() => {
    if (config && Object.keys(config).length > 0) {
      setLocalConfig(config);
    }
  }, [JSON.stringify(config)]);

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
      console.error('Failed to save settings:', e);
    } finally {
      setSaving(false);
    }
  }, [localConfig, refetch]);

  if (loading && Object.keys(localConfig).length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400 gap-2">
        <Loader2 className="animate-spin" size={20} /> Loading settings…
      </div>
    );
  }

  const execution = localConfig.execution ?? {};
  const order_flow = localConfig.order_flow ?? {};
  const risk_controls = localConfig.risk_controls ?? {};
  const notifications = localConfig.notifications ?? {};


  return (
    <div className="flex flex-col md:flex-row gap-6 h-full pb-8">
      
      {/* Settings Navigation */}
      <Card className="w-full md:w-64 shrink-0 bg-slate-900/50 border-slate-800 h-fit">
        <CardContent className="p-3 flex flex-col gap-1">
          {[
            { id: 'api', icon: Key, label: 'API Management' },
            { id: 'execution', icon: Activity, label: 'Execution & Order Flow' },
            { id: 'risk', icon: ShieldAlert, label: 'Risk Controls (New)' },
            { id: 'ai_models', icon: Brain, label: 'AI Language Models' },
            { id: 'alerts', icon: Bell, label: 'Alerts & Notifications' },
          ].map(item => (
            <button
              key={item.id}
              onClick={() => setActiveMenu(item.id)}
              className={cx("flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-semibold transition-all", activeMenu === item.id ? "bg-blue-600/20 text-blue-400" : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200")}
            >
              <item.icon size={18} /> {item.label}
            </button>
          ))}

          {/* Save button in sidebar */}
          {hasChanges && (
            <button
              onClick={handleSave}
              disabled={saving}
              className="mt-4 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-bold rounded-lg transition-all shadow-[0_0_15px_rgba(37,99,235,0.4)]"
            >
              {saving ? <Loader2 size={16} className="animate-spin" /> : saved ? <CheckCircle2 size={16} /> : <Save size={16} />}
              {saving ? 'Saving…' : saved ? 'Saved!' : 'Save Changes'}
            </button>
          )}
        </CardContent>
      </Card>

      {/* Settings Content */}
      <div className="flex-1 flex flex-col gap-6">
        
        {/* VIEW: API MANAGEMENT */}
        {activeMenu === 'api' && (
          <div className="flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
             
             {/* Execution Mode Selector (CRITICAL SAAS FEATURE) */}
             <Card className="bg-slate-900/50 border-slate-800 overflow-hidden relative">
               {execution.mode === 'live' && (
                 <div className="absolute top-0 left-0 right-0 h-1 bg-linear-to-r from-rose-500 via-rose-400 to-rose-500 animate-pulse"></div>
               )}
               <CardContent className="p-6">
                 <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                   <div>
                     <h3 className="text-lg font-bold text-slate-200 mb-1">Execution Mode</h3>
                     <p className="text-sm text-slate-400">
                       Choose how your AI agents execute trades. Paper trading uses live market data but simulated funds.
                     </p>
                   </div>
                   
                   <div className="flex bg-slate-950 p-1.5 rounded-xl border border-slate-800/80 shrink-0">
                     <button
                       onClick={() => setNestedValue('execution.mode', 'paper')}
                       className={cx(
                         "flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-bold transition-all duration-300",
                         execution.mode === 'paper' || !execution.mode
                           ? "bg-amber-500/10 text-amber-400 shadow-[0_0_15px_rgba(245,158,11,0.15)] ring-1 ring-amber-500/30"
                           : "text-slate-500 hover:text-slate-300"
                       )}
                     >
                       <Shield size={16} /> Paper Trading
                     </button>
                     <button
                       onClick={() => setNestedValue('execution.mode', 'live')}
                       className={cx(
                         "flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-bold transition-all duration-300",
                         execution.mode === 'live'
                           ? "bg-rose-500/10 text-rose-400 shadow-[0_0_15px_rgba(244,63,94,0.15)] ring-1 ring-rose-500/30"
                           : "text-slate-500 hover:text-slate-300"
                       )}
                     >
                       <AlertCircle size={16} /> Live Trading
                     </button>
                   </div>
                 </div>
               </CardContent>
             </Card>

             <Card className="bg-slate-900/50 border-slate-800">
               <CardHeader className="py-5 border-b border-slate-800/50">
                 <CardTitle className="text-base flex items-center gap-2">
                   <Monitor className="text-blue-400" /> Connect Broker or Exchange
                 </CardTitle>
               </CardHeader>
               <CardContent className="p-6 flex flex-col gap-8">
                  
                  {/* Crypto Exchanges */}
                  <div>
                    <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-4">Crypto Exchanges</h4>
                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                      {[
                        { id: 'binance',  label: 'Binance',  abbr: 'BN', color: 'text-yellow-500', bg: 'bg-yellow-500/10' },
                        { id: 'bybit',    label: 'Bybit',    abbr: 'BY', color: 'text-amber-500',  bg: 'bg-amber-500/10' },
                        { id: 'okx',      label: 'OKX',      abbr: 'OK', color: 'text-white',      bg: 'bg-slate-600/20' },
                        { id: 'kucoin',   label: 'KuCoin',   abbr: 'KC', color: 'text-teal-400',   bg: 'bg-teal-500/10' },
                        { id: 'coinbase', label: 'Coinbase', abbr: 'CB', color: 'text-blue-400',   bg: 'bg-blue-500/10' },
                        { id: 'kraken',   label: 'Kraken',   abbr: 'KR', color: 'text-purple-400', bg: 'bg-purple-500/10' },
                        { id: 'gateio',   label: 'Gate.io',  abbr: 'GT', color: 'text-cyan-400',   bg: 'bg-cyan-500/10' },
                      ].map(ex => {
                        const isSelected = (execution.exchange ?? 'binance') === ex.id && execution.broker !== 'alpaca';
                        return (
                          <button
                            key={ex.id}
                            onClick={() => {
                              setNestedValue('execution.exchange', ex.id);
                              setNestedValue('execution.broker', 'ccxt');
                            }}
                            className={cx(
                              "p-4 rounded-xl border transition-all duration-300 flex flex-col items-center gap-3 relative text-center group",
                              isSelected
                                ? "bg-slate-800 border-blue-500/60 shadow-[0_0_20px_rgba(37,99,235,0.15)]"
                                : "bg-slate-950/40 border-slate-800/60 hover:border-slate-700 opacity-60 hover:opacity-100"
                            )}
                          >
                            <div className={cx("w-10 h-10 rounded-lg flex items-center justify-center font-bold text-lg", ex.bg, ex.color)}>
                              {ex.abbr}
                            </div>
                            <span className="font-semibold text-slate-200 text-sm block">{ex.label}</span>
                            
                            {isSelected && (
                              <span className="absolute top-3 right-3 text-blue-400">
                                <CheckCircle2 size={16} />
                              </span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Stock Brokers */}
                  <div>
                    <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-4">Stock & Forex Brokers</h4>
                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                      {[
                        { id: 'alpaca', label: 'Alpaca Markets', abbr: 'AL', color: 'text-lime-400', bg: 'bg-lime-500/10' },
                        { id: 'interactive_brokers', label: 'Interactive Brokers', abbr: 'IB', color: 'text-red-400', bg: 'bg-red-500/10', disabled: true },
                      ].map(ex => {
                        const isSelected = execution.broker === ex.id;
                        return (
                          <button
                            key={ex.id}
                            disabled={ex.disabled}
                            onClick={() => {
                              setNestedValue('execution.broker', ex.id);
                              setNestedValue('execution.exchange', ex.id);
                            }}
                            className={cx(
                              "p-4 rounded-xl border transition-all duration-300 flex flex-col items-center gap-3 relative text-center group",
                              ex.disabled ? "opacity-30 cursor-not-allowed bg-slate-950/20" :
                              isSelected
                                ? "bg-slate-800 border-lime-500/60 shadow-[0_0_20px_rgba(132,204,22,0.15)]"
                                : "bg-slate-950/40 border-slate-800/60 hover:border-slate-700 opacity-60 hover:opacity-100"
                            )}
                          >
                            <div className={cx("w-10 h-10 rounded-lg flex items-center justify-center font-bold text-lg", ex.disabled ? 'bg-slate-800 text-slate-500' : ex.bg, ex.disabled ? '' : ex.color)}>
                              {ex.abbr}
                            </div>
                            <span className="font-semibold text-slate-200 text-sm block">
                              {ex.label}
                              {ex.disabled && <span className="block text-[10px] text-rose-400 mt-1 uppercase">Coming Soon</span>}
                            </span>
                            
                            {isSelected && (
                              <span className="absolute top-3 right-3 text-lime-400">
                                <CheckCircle2 size={16} />
                              </span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* API Credentials Input Form */}
                  <div className="mt-2 p-6 rounded-xl border border-slate-800 bg-slate-950/50">
                    <div className="mb-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
                      <div>
                        <h4 className="font-bold text-slate-100 flex items-center gap-2">
                          <Key size={16} className="text-slate-400" /> 
                          Connection Setup — <span className="text-blue-400">{(execution.exchange ?? 'binance').toUpperCase()}</span>
                        </h4>
                        <p className="text-xs text-slate-500 mt-1">Credentials are securely sanitized before being saved to local persistence.</p>
                      </div>
                      <div className="flex items-center gap-3 bg-slate-900/80 px-4 py-2 rounded-lg border border-slate-700/50">
                        <span className="text-xs font-bold text-slate-400 uppercase">Testnet (Sandbox)</span>
                        <Toggle 
                          enabled={execution.sandbox ?? false}
                          onChange={(v) => setNestedValue('execution.sandbox', v)} 
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                      <div>
                        <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">API Key</label>
                        <input 
                          type="password"
                          value={execution.api_key ?? ''}
                          onChange={(e) => setNestedValue('execution.api_key', e.target.value)}
                          placeholder="Your Read/Trade API Key"
                          className="w-full bg-slate-900 border border-slate-700/50 text-slate-200 text-sm rounded-lg p-3 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/50 font-mono transition-all"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">API Secret</label>
                        <input 
                          type="password"
                          value={execution.api_secret ?? ''}
                          onChange={(e) => setNestedValue('execution.api_secret', e.target.value)}
                          placeholder="Your Secret Hash"
                          className="w-full bg-slate-900 border border-slate-700/50 text-slate-200 text-sm rounded-lg p-3 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/50 font-mono transition-all"
                        />
                      </div>
                    </div>
                    
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6 pt-6 border-t border-slate-800/50">
                      <div>
                        <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Quote Currency</label>
                        <select 
                          value={execution.quote_currency ?? 'USDT'}
                          onChange={(e) => setNestedValue('execution.quote_currency', e.target.value)}
                          className="w-full bg-slate-900 border border-slate-700/50 text-slate-200 text-sm rounded-lg p-3 outline-none focus:border-blue-500 transition-all cursor-pointer"
                        >
                          <option value="USDT">USDT (Tether)</option>
                          <option value="USD">USD (US Dollar)</option>
                          <option value="USDC">USDC (USD Coin)</option>
                          <option value="BTC">BTC (Bitcoin)</option>
                          <option value="EUR">EUR (Euro)</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 items-center justify-between">
                          <span>Passphrase</span>
                          {(execution.exchange === 'okx' || execution.exchange === 'kucoin') 
                            ? <span className="text-rose-400 text-[10px] bg-rose-500/10 px-2 py-0.5 rounded ml-2">Required Here</span> 
                            : <span className="text-slate-500 text-[10px] ml-2">Optional</span>
                          }
                        </label>
                        <input 
                          type="password"
                          value={execution.password ?? ''}
                          onChange={(e) => setNestedValue('execution.password', e.target.value)}
                          placeholder="Required for OKX/Kucoin"
                          className="w-full bg-slate-900 border border-slate-700/50 text-slate-200 text-sm rounded-lg p-3 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/50 font-mono transition-all"
                        />
                      </div>
                    </div>

                    {/* Futures & Leverage Setup */}
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6 pt-6 border-t border-slate-800/50">
                      <div>
                        <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Market Type</label>
                        <select 
                          value={execution.market_type ?? 'spot'}
                          onChange={(e) => setNestedValue('execution.market_type', e.target.value)}
                          className="w-full bg-slate-900 border border-slate-700/50 text-slate-200 text-sm rounded-lg p-3 outline-none focus:border-blue-500 transition-all cursor-pointer"
                        >
                          <option value="spot">Spot Market (No Leverage)</option>
                          <option value="future">Futures (Perpetual / Margin)</option>
                        </select>
                      </div>

                      <div className={cx("transition-opacity duration-300", execution.market_type === 'future' ? "opacity-100" : "opacity-30 pointer-events-none")}>
                        <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Margin Mode</label>
                        <select 
                          value={execution.margin_type ?? 'isolated'}
                          onChange={(e) => setNestedValue('execution.margin_type', e.target.value)}
                          className="w-full bg-slate-900 border border-slate-700/50 text-slate-200 text-sm rounded-lg p-3 outline-none focus:border-blue-500 transition-all cursor-pointer"
                        >
                          <option value="isolated">Isolated (Safer)</option>
                          <option value="cross">Cross (Shared Balance)</option>
                        </select>
                      </div>
                      
                      <div className={cx("transition-opacity duration-300", execution.market_type === 'future' ? "opacity-100" : "opacity-30 pointer-events-none")}>
                        <label className="flex items-center justify-between text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">
                          <span>Max Account Leverage</span>
                          <span className="text-blue-400 font-mono text-[10px] bg-blue-500/10 px-2 py-0.5 rounded">Risk Limit</span>
                        </label>
                        <div className="flex items-center gap-3">
                          <input 
                            type="range" min="1" max="100" step="1"
                            value={execution.max_leverage ?? 10}
                            onChange={(e) => setNestedValue('execution.max_leverage', parseInt(e.target.value))}
                            className="flex-1 accent-blue-500 h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer"
                          />
                          <span className="text-blue-400 font-mono font-bold w-12 text-right">
                            {execution.max_leverage ?? 10}x
                          </span>
                        </div>
                        <p className="text-[10px] text-slate-500 mt-2 leading-relaxed">
                          Agen AI (Risk Manager) tidak diizinkan melebihi batas batas leverage maksimum ini saat menggunakan Futures.
                        </p>
                      </div>
                    </div>
                  </div>

               </CardContent>
             </Card>
          </div>
        )}

        {/* VIEW: EXECUTION & ORDER FLOW */}
        {activeMenu === 'execution' && (
          <div className="flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
             
             {/* Execution Criteria */}
             <Card className="bg-slate-900/50 border-slate-800">
               <CardHeader className="py-5 border-b border-slate-800/50">
                 <CardTitle className="text-base flex items-center gap-2 text-slate-200">
                   <Target className="text-blue-400" size={18} /> Execution Criteria & Cooldowns
                 </CardTitle>
               </CardHeader>
               <CardContent className="p-6">
                 <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                   
                   <div className="flex flex-col gap-2">
                     <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Min Confidence Score</label>
                     <p className="text-xs text-slate-500 mb-2 h-10">
                       Minimum confidence level (0.0 to 1.0) required from the AI to execute a trade.
                     </p>
                     <div className="flex items-center gap-3">
                       <input 
                         type="range" min="0" max="1" step="0.05"
                         value={execution.min_confidence ?? 0.5}
                         onChange={(e) => setNestedValue('execution.min_confidence', parseFloat(e.target.value))}
                         className="flex-1 accent-blue-500 h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer"
                       />
                       <span className="text-blue-400 font-mono font-bold w-12 text-right">
                         {Math.round((execution.min_confidence ?? 0.5) * 100)}%
                       </span>
                     </div>
                   </div>

                   <div className="flex flex-col gap-2">
                     <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Trading Cooldown (Sec)</label>
                     <p className="text-xs text-slate-500 mb-2 h-10">
                       Wait time between regular trades to prevent overtrading on the same asset.
                     </p>
                     <input 
                       type="number" step="1" min="0" max="86400"
                       value={execution.cooldown_seconds ?? 300}
                       onChange={(e) => setNestedValue('execution.cooldown_seconds', parseInt(e.target.value))}
                       className="w-full bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-xl p-3 outline-none focus:border-blue-500 font-mono"
                     />
                   </div>

                   <div className="flex flex-col gap-2 mt-2">
                     <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Require Manual Confirmation</label>
                     <p className="text-xs text-slate-500 mb-2 h-10">
                       When enabled, trades will be staged but not executed until you manually approve them.
                     </p>
                     <div className="flex items-center gap-3 mt-1">
                       <Toggle 
                         enabled={execution.require_confirmation ?? true}
                         onChange={(v) => setNestedValue('execution.require_confirmation', v)} 
                       />
                       <span className={cx("text-sm font-bold", (execution.require_confirmation ?? true) ? "text-amber-400" : "text-emerald-400")}>
                         {(execution.require_confirmation ?? true) ? 'REQUIRED' : 'Auto-Execute'}
                       </span>
                     </div>
                   </div>

                 </div>
               </CardContent>
             </Card>


             {/* Smart Execution Guard Master Switch */}
             <Card className={cx("border transition-colors duration-300", order_flow.enabled ? "bg-emerald-950/20 border-emerald-900/50" : "bg-slate-900/50 border-slate-800")}>
               <CardContent className="p-6">
                 <div className="flex flex-col md:flex-row justify-between gap-6">
                   <div className="flex gap-4">
                     <div className={cx("mt-1 w-12 h-12 rounded-xl flex items-center justify-center shrink-0 shadow-inner", order_flow.enabled ? "bg-emerald-500/20 shadow-emerald-500/10" : "bg-slate-800/50")}>
                       <Shield className={order_flow.enabled ? "text-emerald-400" : "text-slate-500"} size={26} />
                     </div>
                     <div>
                       <h3 className={cx("text-xl font-bold mb-1", order_flow.enabled ? "text-emerald-400" : "text-slate-200")}>
                         Smart Execution Guard (Sniper)
                       </h3>
                       <p className="text-sm text-slate-400 max-w-2xl leading-relaxed">
                         When enabled, the execution engine acts as a sniper. Before placing any order to Binance/Bybit, it fetches the real-time Order Book (L2 data) to calculate the <strong>Order Book Imbalance (OBI)</strong> and detect institutional walls. It will <strong>BLOCK</strong> trades permanently if the order flow is highly dangerous, or <strong>WAIT (Poll)</strong> if it is neutral.
                       </p>
                     </div>
                   </div>
                   <div className="flex items-center shrink-0">
                     <Toggle enabled={!!order_flow.enabled} onChange={(v) => setNestedValue('order_flow.enabled', v)} />
                   </div>
                 </div>
               </CardContent>
             </Card>

             {/* Order Book Imbalance Settings */}
             <div className={cx("flex flex-col gap-6 transition-all duration-500", order_flow.enabled ? "opacity-100" : "opacity-30 pointer-events-none")}>
               
               <Card className="bg-slate-900/50 border-slate-800">
                 <CardHeader className="py-5 border-b border-slate-800/50">
                   <CardTitle className="text-base flex items-center gap-2 text-slate-200">
                     <Activity className="text-blue-400" size={18} /> Order Book Imbalance (OBI) Thresholds
                   </CardTitle>
                 </CardHeader>
                 <CardContent className="p-6">
                   <div className="grid grid-cols-1 lg:grid-cols-2 gap-10">
                     
                     <div className="flex flex-col gap-4">
                       <label className="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center justify-between">
                         <span>Execute Threshold</span>
                         <span className="text-emerald-400 font-mono font-bold">
                           +{order_flow.obi_execute_threshold ?? 0.3}
                         </span>
                       </label>
                       <p className="text-xs text-slate-500 leading-relaxed -mt-2">
                         Minimum positive OBI required to execute a trade instantly. <span className="text-emerald-400 bg-emerald-500/10 px-1 rounded">Default: +0.3</span> (Strong buy pressure).
                       </p>
                       <input 
                         type="range" min="0" max="0.9" step="0.05"
                         value={order_flow.obi_execute_threshold ?? 0.3}
                         onChange={(e) => setNestedValue('order_flow.obi_execute_threshold', parseFloat(e.target.value))}
                         className="w-full accent-emerald-500 h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer"
                       />
                     </div>

                     <div className="flex flex-col gap-4">
                       <label className="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center justify-between">
                         <span>Block (Cancel) Threshold</span>
                         <span className="text-rose-400 font-mono font-bold">
                           -{order_flow.obi_block_threshold ?? 0.3}
                         </span>
                       </label>
                       <p className="text-xs text-slate-500 leading-relaxed -mt-2">
                         Maximum negative OBI before the trade is canceled. <span className="text-rose-400 bg-rose-500/10 px-1 rounded">Default: -0.3</span> (Strong sell pressure).
                       </p>
                       <input 
                         type="range" min="0" max="0.9" step="0.05"
                         value={order_flow.obi_block_threshold ?? 0.3}
                         onChange={(e) => setNestedValue('order_flow.obi_block_threshold', parseFloat(e.target.value))}
                         className="w-full accent-rose-500 h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer"
                       />
                     </div>

                   </div>
                 </CardContent>
               </Card>

               {/* Advanced Guard Settings */}
               <Card className="bg-slate-900/50 border-slate-800">
                 <CardHeader className="py-5 border-b border-slate-800/50">
                   <CardTitle className="text-base flex items-center gap-2 text-slate-200">
                     <Target className="text-amber-400" size={18} /> Wall Detection & Polling Overrides
                   </CardTitle>
                 </CardHeader>
                 <CardContent className="p-6">
                   <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                     
                     <div className="flex flex-col gap-2">
                       <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Wall Size Threshold (USD)</label>
                       <p className="text-xs text-slate-500 mb-2 h-10">
                         Dollar value required at a single price level to be considered an institutional wall.
                       </p>
                       <input 
                         type="number" step="100000"
                         value={order_flow.wall_detection_usd ?? 500000}
                         onChange={(e) => setNestedValue('order_flow.wall_detection_usd', parseInt(e.target.value))}
                         className="w-full bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-xl p-3 outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500 font-mono"
                       />
                     </div>

                     <div className="flex flex-col gap-2">
                       <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Poll Max Wait (Secs)</label>
                       <p className="text-xs text-slate-500 mb-2 h-10">
                         How long to wait & keep polling if the order book flow is currently neutral.
                       </p>
                       <input 
                         type="number" step="10"
                         value={order_flow.max_wait_seconds ?? 180}
                         onChange={(e) => setNestedValue('order_flow.max_wait_seconds', parseInt(e.target.value))}
                         className="w-full bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-xl p-3 outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500 font-mono"
                       />
                     </div>

                     <div className="flex flex-col gap-2">
                       <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Order Book Depth</label>
                       <p className="text-xs text-slate-500 mb-2 h-10">
                         Levels to fetch from exchange (higher = wider lookahead but slower API limits).
                       </p>
                       <select 
                         value={order_flow.order_book_depth ?? 20}
                         onChange={(e) => setNestedValue('order_flow.order_book_depth', parseInt(e.target.value))}
                         className="w-full bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-xl p-3 outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500 font-mono"
                       >
                         <option value="10">10 Levels (Shallow)</option>
                         <option value="20">20 Levels (Optimal)</option>
                         <option value="50">50 Levels (Deep)</option>
                         <option value="100">100 Levels (Extremely Deep)</option>
                       </select>
                     </div>

                   </div>
                 </CardContent>
               </Card>
             </div>
          </div>
        )}

        {/* VIEW: RISK CONTROLS */}
        {activeMenu === 'risk' && (
          <div className="flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
            
            {/* Position Sizing */}
            <Card className="bg-slate-900/50 border-slate-800">
              <CardHeader className="py-5 border-b border-slate-800/50">
                <CardTitle className="text-base flex items-center gap-2 text-slate-200">
                  <Crosshair className="text-blue-400" size={18} /> Asset Allocation & Limits
                </CardTitle>
              </CardHeader>
              <CardContent className="p-6">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  
                  <div className="flex flex-col gap-2">
                    <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Max Position Size (%)</label>
                    <p className="text-xs text-slate-500 mb-2 h-10">
                      Maximum percentage of your total equity allocated per single trade. Default: 10% (0.1).
                    </p>
                    <div className="flex items-center gap-3">
                      <input 
                        type="number" step="0.01" min="0.01" max="1"
                        value={risk_controls.max_position_pct ?? 0.10}
                        onChange={(e) => setNestedValue('risk_controls.max_position_pct', parseFloat(e.target.value))}
                        className="flex-1 bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-xl p-3 outline-none focus:border-blue-500 font-mono"
                      />
                      <span className="bg-slate-800 px-3 py-3 rounded-xl border border-slate-700 font-mono text-sm text-blue-400 w-16 text-center">
                        {Math.round((risk_controls.max_position_pct ?? 0.10) * 100)}%
                      </span>
                    </div>
                  </div>

                  <div className="flex flex-col gap-2">
                    <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Max Concurrent Positions</label>
                    <p className="text-xs text-slate-500 mb-2 h-10">
                      The max number of simultaneous open trades the bot is allowed to maintain.
                    </p>
                    <input 
                      type="number" step="1" min="1" max="50"
                      value={risk_controls.max_concurrent_positions ?? 5}
                      onChange={(e) => setNestedValue('risk_controls.max_concurrent_positions', parseInt(e.target.value))}
                      className="w-full bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-xl p-3 outline-none focus:border-blue-500 font-mono"
                    />
                  </div>

                </div>
              </CardContent>
            </Card>

            {/* Smart Exits */}
            <Card className="bg-slate-900/50 border-slate-800">
              <CardHeader className="py-5 border-b border-slate-800/50">
                <CardTitle className="text-base flex items-center gap-2 text-slate-200">
                  <Activity className="text-emerald-400" size={18} /> Smart Stops & Exits
                </CardTitle>
              </CardHeader>
              <CardContent className="p-6">
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  
                  <div className="flex flex-col gap-2">
                    <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Trailing Stop (%)</label>
                    <p className="text-xs text-slate-500 mb-2 h-10">
                      Drops stop-loss dynamically behind the peak price (e.g. 0.05 = 5%). 0 to disable.
                    </p>
                    <input 
                      type="number" step="0.01" min="0" max="1"
                      value={risk_controls.trailing_stop_pct ?? 0.05}
                      onChange={(e) => setNestedValue('risk_controls.trailing_stop_pct', parseFloat(e.target.value))}
                      className="w-full bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-xl p-3 outline-none focus:border-emerald-500 font-mono"
                    />
                  </div>

                  <div className="flex flex-col gap-2">
                    <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">ATR Multiplier</label>
                    <p className="text-xs text-slate-500 mb-2 h-10">
                      Initial stop-loss distance calculation based on volatility (Average True Range).
                    </p>
                    <input 
                      type="number" step="0.1"
                      value={risk_controls.atr_multiplier ?? 2.0}
                      onChange={(e) => setNestedValue('risk_controls.atr_multiplier', parseFloat(e.target.value))}
                      className="w-full bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-xl p-3 outline-none focus:border-emerald-500 font-mono"
                    />
                  </div>

                  <div className="flex flex-col gap-2">
                    <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Max Hold Time (Hrs)</label>
                    <p className="text-xs text-slate-500 mb-2 h-10">
                      Force exits a stagnant trade after this many hours.
                    </p>
                    <input 
                      type="number" step="1"
                      value={risk_controls.max_hold_hours ?? 72}
                      onChange={(e) => setNestedValue('risk_controls.max_hold_hours', parseInt(e.target.value))}
                      className="w-full bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-xl p-3 outline-none focus:border-emerald-500 font-mono"
                    />
                  </div>

                </div>
              </CardContent>
            </Card>
            {/* Kill Switch (Per-User — Multi-Tenant Safe) */}
            <Card className="bg-slate-900/50 border-slate-800 relative overflow-hidden">
              {risk_controls.kill_switch_enabled && (
                <div className="absolute top-0 left-0 right-0 h-1 bg-linear-to-r from-rose-500 via-rose-400 to-rose-500 animate-pulse"></div>
              )}
              <CardHeader className="py-5 border-b border-slate-800/50">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base flex items-center gap-2 text-slate-200">
                    <ShieldAlert className="text-rose-400" size={18} /> Automated Kill Switch
                  </CardTitle>
                  <span className="text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                    Per-User Isolated
                  </span>
                </div>
              </CardHeader>
              <CardContent className="p-6">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  
                  <div className="flex flex-col gap-2">
                    <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Kill Switch</label>
                    <p className="text-xs text-slate-500 mb-2 h-10">
                      Automatically halt all trading when daily or weekly loss limits are breached. Only affects YOUR account.
                    </p>
                    <div className="flex items-center gap-3">
                      <Toggle 
                        enabled={risk_controls.kill_switch_enabled ?? true}
                        onChange={(v) => setNestedValue('risk_controls.kill_switch_enabled', v)} 
                      />
                      <span className={cx("text-sm font-bold", risk_controls.kill_switch_enabled ? "text-rose-400" : "text-slate-500")}>
                        {risk_controls.kill_switch_enabled ? 'ARMED' : 'Disabled'}
                      </span>
                    </div>
                  </div>

                  <div className="flex flex-col gap-2">
                    <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Consecutive Loss Limit</label>
                    <p className="text-xs text-slate-500 mb-2 h-10">
                      Enter cooldown mode after this many consecutive losing trades.
                    </p>
                    <input 
                      type="number" step="1" min="1" max="20"
                      value={risk_controls.consecutive_loss_limit ?? 3}
                      onChange={(e) => setNestedValue('risk_controls.consecutive_loss_limit', parseInt(e.target.value))}
                      className="w-full bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-xl p-3 outline-none focus:border-rose-500 font-mono"
                    />
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Drawdown Limits */}
            <Card className="bg-slate-900/50 border-slate-800">
              <CardHeader className="py-5 border-b border-slate-800/50">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base flex items-center gap-2 text-slate-200">
                    <TrendingDown className="text-amber-400" size={18} /> Drawdown Limits
                  </CardTitle>
                  <span className="text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                    Per-User Isolated
                  </span>
                </div>
              </CardHeader>
              <CardContent className="p-6">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  
                  <div className="flex flex-col gap-2">
                    <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Max Daily Loss (%)</label>
                    <p className="text-xs text-slate-500 mb-2 h-10">
                      If your daily loss exceeds this threshold, the kill switch activates and all trading halts for the day.
                    </p>
                    <div className="flex items-center gap-3">
                      <input 
                        type="number" step="0.01" min="0.01" max="0.5"
                        value={risk_controls.max_daily_loss_pct ?? 0.05}
                        onChange={(e) => setNestedValue('risk_controls.max_daily_loss_pct', parseFloat(e.target.value))}
                        className="flex-1 bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-xl p-3 outline-none focus:border-amber-500 font-mono"
                      />
                      <span className="bg-slate-800 px-3 py-3 rounded-xl border border-slate-700 font-mono text-sm text-amber-400 w-16 text-center">
                        {Math.round((risk_controls.max_daily_loss_pct ?? 0.05) * 100)}%
                      </span>
                    </div>
                  </div>

                  <div className="flex flex-col gap-2">
                    <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Max Weekly Loss (%)</label>
                    <p className="text-xs text-slate-500 mb-2 h-10">
                      Cumulative weekly loss limit. The kill switch activates if this threshold is breached.
                    </p>
                    <div className="flex items-center gap-3">
                      <input 
                        type="number" step="0.01" min="0.02" max="1"
                        value={risk_controls.max_weekly_loss_pct ?? 0.10}
                        onChange={(e) => setNestedValue('risk_controls.max_weekly_loss_pct', parseFloat(e.target.value))}
                        className="flex-1 bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-xl p-3 outline-none focus:border-amber-500 font-mono"
                      />
                      <span className="bg-slate-800 px-3 py-3 rounded-xl border border-slate-700 font-mono text-sm text-amber-400 w-16 text-center">
                        {Math.round((risk_controls.max_weekly_loss_pct ?? 0.10) * 100)}%
                      </span>
                    </div>
                  </div>

                </div>
              </CardContent>
            </Card>

          </div>
        )}

        {/* VIEW: AI LANGUAGE MODELS */}
        {activeMenu === 'ai_models' && (
          <div className="flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
             
             {/* Provider Selection */}
             <Card className="bg-slate-900/50 border-slate-800">
               <CardHeader className="py-5 border-b border-slate-800/50">
                 <CardTitle className="text-lg flex items-center gap-2">
                   <Brain className="text-purple-400" /> AI Provider Selection
                 </CardTitle>
               </CardHeader>
               <CardContent className="p-6">
                 <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                   {[
                     { id: 'openai', label: 'OpenAI', desc: 'GPT-4o, o1-preview', color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
                     { id: 'anthropic', label: 'Anthropic', desc: 'Claude 3.5 Sonnet', color: 'text-amber-400', bg: 'bg-amber-500/10' },
                     { id: 'google', label: 'Google', desc: 'Gemini 1.5 Pro', color: 'text-blue-400', bg: 'bg-blue-500/10' },
                   ].map(provider => {
                     const isSelected = localConfig.llm_provider === provider.id;
                     return (
                       <button
                         key={provider.id}
                         onClick={() => setNestedValue('llm_provider', provider.id)}
                         className={cx(
                           "p-5 rounded-xl border-2 transition-all duration-200 flex flex-col items-center gap-3 relative text-center",
                           isSelected
                             ? "bg-slate-900/80 border-purple-500/60 shadow-[0_0_20px_rgba(168,85,247,0.15)]"
                             : "bg-slate-950/50 border-slate-800/50 hover:border-slate-700 opacity-70 hover:opacity-100"
                         )}
                       >
                         <div className={cx("w-12 h-12 rounded-full flex items-center justify-center font-bold text-xl", provider.bg, provider.color)}>
                           {provider.label.charAt(0)}
                         </div>
                         <div>
                           <span className="block font-bold text-slate-200">{provider.label}</span>
                           <span className="block text-xs text-slate-500 mt-1">{provider.desc}</span>
                         </div>
                         {isSelected && (
                           <span className="absolute top-3 right-3 text-purple-400">
                             <CheckCircle2 size={16} />
                           </span>
                         )}
                       </button>
                     );
                   })}
                 </div>
               </CardContent>
             </Card>

             {/* Model Configuration */}
             <Card className="bg-slate-900/50 border-slate-800">
               <CardHeader className="py-5 border-b border-slate-800/50">
                 <CardTitle className="text-base flex items-center gap-2">
                   <Cpu className="text-blue-400" size={18} /> Engine Allocation & Persona
                 </CardTitle>
               </CardHeader>
               <CardContent className="p-6">
                 
                 <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                   {/* Deep Think LLM */}
                   <div className="flex flex-col gap-3 relative">
                     <div className="flex items-center justify-between pointer-events-none">
                       <label className="text-sm font-bold text-slate-200 flex items-center gap-1.5">
                         <Brain size={16} className="text-purple-400" /> Deep Think LLM
                       </label>
                       <span className="text-[10px] font-bold tracking-wider text-purple-400 bg-purple-500/10 px-2 py-0.5 rounded uppercase">Heavy Reasoning</span>
                     </div>
                     <p className="text-xs text-slate-500 min-h-[32px]">
                       Powers the Market, Quant, and Macro specialist agents. Requires maximum zero-shot logical capability.
                     </p>
                     
                     <div className="relative group">
                       <select 
                         value={localConfig.deep_think_llm ?? ''}
                         onChange={(e) => setNestedValue('deep_think_llm', e.target.value)}
                         className="w-full bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-lg p-3 outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500/50 font-mono transition-all shadow-inner cursor-pointer appearance-none"
                       >
                         {/* Dynamic Options Based on Provider */}
                         {Array.from(new Set([
                           ...(localConfig.llm_provider === 'anthropic' ? ['claude-3-5-sonnet-latest', 'claude-3-opus-latest'] : []),
                           ...(localConfig.llm_provider === 'google' ? ['gemini-1.5-pro', 'gemini-1.5-pro-latest'] : []),
                           ...(localConfig.llm_provider === 'openai' ? ['gpt-4o', 'o1-preview', 'o1-mini', 'o1'] : []),
                           localConfig.deep_think_llm // Ensure current value is always visible even if custom
                         ].filter(Boolean))).map(val => (
                           <option key={val as string} value={val as string}>{MODEL_LABELS[val as string] || val}</option>
                         ))}
                       </select>
                       <div className="absolute inset-y-0 right-4 flex items-center pointer-events-none">
                         <span className="text-slate-500">▼</span>
                       </div>
                     </div>
                   </div>

                   {/* Quick Think LLM */}
                   <div className="flex flex-col gap-3 relative">
                     <div className="flex items-center justify-between pointer-events-none">
                       <label className="text-sm font-bold text-slate-200 flex items-center gap-1.5">
                         <Zap size={16} className="text-amber-400" /> Quick Think LLM
                       </label>
                       <span className="text-[10px] font-bold tracking-wider text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded uppercase">Fast Routing</span>
                     </div>
                     <p className="text-xs text-slate-500 min-h-[32px]">
                       Powers the Orchestrator for rapid data synthesis, intent parsing, and delegating tasks to specialists.
                     </p>
                     
                     <div className="relative group">
                       <select 
                         value={localConfig.quick_think_llm ?? ''}
                         onChange={(e) => setNestedValue('quick_think_llm', e.target.value)}
                         className="w-full bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-lg p-3 outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500/50 font-mono transition-all shadow-inner cursor-pointer appearance-none"
                       >
                         {Array.from(new Set([
                           ...(localConfig.llm_provider === 'anthropic' ? ['claude-3-5-haiku-latest', 'claude-3-haiku-20240307'] : []),
                           ...(localConfig.llm_provider === 'google' ? ['gemini-1.5-flash', 'gemini-1.5-flash-8b'] : []),
                           ...(localConfig.llm_provider === 'openai' ? ['gpt-4o-mini', 'gpt-3.5-turbo'] : []),
                           localConfig.quick_think_llm
                         ].filter(Boolean))).map(val => (
                           <option key={val as string} value={val as string}>{MODEL_LABELS[val as string] || val}</option>
                         ))}
                       </select>
                       <div className="absolute inset-y-0 right-4 flex items-center pointer-events-none">
                         <span className="text-slate-500">▼</span>
                       </div>
                     </div>
                   </div>
                 </div>

               </CardContent>
             </Card>

             {/* Advanced Settings */}
             <Card className="bg-slate-950/40 border-slate-800 overflow-hidden">
               <CardHeader className="py-4 border-b border-slate-800/50 bg-slate-900/30">
                 <CardTitle className="text-sm font-semibold text-slate-300 flex items-center gap-2">
                   <Settings2 size={16} /> Advanced Parameters & Connectivity
                 </CardTitle>
               </CardHeader>
               <CardContent className="p-6">
                 
                 <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                   <div>
                     <label className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                       <Server size={14} />  API AI URL Override
                     </label>
                     <p className="text-xs text-slate-500 mb-3 leading-relaxed">
                       Leave blank to use provider defaults. Useful if you are routing traffic through an enterprise proxy (e.g., LiteLLM, Azure OpenAI, or Cloudflare AI Gateway).
                     </p>
                     <input 
                       type="text"
                       value={localConfig.backend_url ?? ''}
                       onChange={(e) => setNestedValue('backend_url', e.target.value)}
                       placeholder={localConfig.llm_provider === 'openai' ? 'https://api.openai.com/v1' : 'Leave empty for default'}
                       className="w-full bg-black/40 border border-slate-800 text-slate-200 text-sm rounded-lg p-3 outline-none focus:border-slate-500 font-mono transition-colors"
                     />
                   </div>

                   {localConfig.llm_provider === 'openai' && (
                     <div className="border-l border-slate-800/50 pl-0 lg:pl-8">
                       <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">o1 Reasoning Effort</label>
                       <p className="text-xs text-slate-500 mb-3 leading-relaxed">
                         Controls the compute spent on thinking. Only effective if <span className="text-purple-400 font-mono bg-purple-500/10 px-1 rounded">o1-*</span> series models are allocated above.
                       </p>
                       <div className="inline-flex bg-slate-900 p-1 rounded-xl border border-slate-800">
                         {['low', 'medium', 'high'].map(eff => (
                           <button
                             key={eff}
                             onClick={() => setNestedValue('openai_reasoning_effort', eff)}
                             className={cx(
                               "px-6 py-2 rounded-lg text-sm font-semibold capitalize transition-all",
                               (localConfig.openai_reasoning_effort === eff) || (!localConfig.openai_reasoning_effort && eff === 'medium')
                                 ? "bg-slate-700 text-white shadow"
                                 : "text-slate-500 hover:text-slate-300"
                             )}
                           >
                             {eff}
                           </button>
                         ))}
                       </div>
                     </div>
                   )}
                 </div>

               </CardContent>
             </Card>

          </div>
        )}

        {/* VIEW: ALERTS */}
        {activeMenu === 'alerts' && (
          <div className="flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
             
             {/* Master Enable Warning */}
             {!notifications.enabled && (
               <div className="bg-amber-500/10 border border-amber-500/20 p-4 rounded-xl flex items-start gap-4">
                 <AlertCircle className="text-amber-500 shrink-0 mt-0.5" size={20} />
                 <div>
                   <h4 className="text-amber-400 font-bold text-sm">Notifications are currently disabled</h4>
                   <p className="text-amber-500/80 text-xs mt-1 leading-relaxed">
                     Your AI agents will not send any alerts to Telegram. Enable the master switch below to start receiving real-time portfolio updates.
                   </p>
                 </div>
                 <div className="ml-auto">
                   <Toggle enabled={false} onChange={(v) => setNestedValue('notifications.enabled', v)} />
                 </div>
               </div>
             )}

             {notifications.enabled && (
               <div className="bg-emerald-500/10 border border-emerald-500/20 p-4 rounded-xl flex items-center justify-between gap-4">
                 <div className="flex items-center gap-3">
                   <div className="w-8 h-8 rounded-full bg-emerald-500/20 flex items-center justify-center">
                     <Bell className="text-emerald-400" size={16} />
                   </div>
                   <div>
                     <h4 className="text-emerald-400 font-bold text-sm">Notifications Active</h4>
                     <p className="text-emerald-500/80 text-xs mt-0.5">System is broadcasting alerts.</p>
                   </div>
                 </div>
                 <Toggle enabled={true} onChange={(v) => setNestedValue('notifications.enabled', v)} />
               </div>
             )}

             {/* Connection Setup */}
             <Card className="bg-slate-900/50 border-slate-800">
               <CardHeader className="py-5 border-b border-slate-800/50">
                 <CardTitle className="text-base flex items-center gap-2">
                   <Send className="text-blue-400" size={18} /> Telegram Connection Setup
                 </CardTitle>
               </CardHeader>
               <CardContent className="p-6">
                 <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-12">
                   <div className="flex flex-col">
                     <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Bot Token</label>
                     <p className="text-xs text-slate-500 mb-4 leading-relaxed flex-1">
                       The HTTP API Token generated by <a href="https://t.me/BotFather" target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">@BotFather</a>. Keep this secret.
                     </p>
                     <input 
                       type="password"
                       value={notifications.telegram_bot_token ?? ''}
                       onChange={(e) => setNestedValue('notifications.telegram_bot_token', e.target.value)}
                       placeholder="e.g. 1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
                       className="w-full bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-lg p-3 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/50 font-mono transition-all shadow-inner"
                     />
                   </div>
                   <div className="flex flex-col">
                     <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Target Chat ID</label>
                     <p className="text-xs text-slate-500 mb-4 leading-relaxed flex-1">
                       Your personal Chat ID or Group ID. Forward a message to <a href="https://t.me/userinfobot" target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">@userinfobot</a> to find yours.
                     </p>
                     <input 
                       type="text"
                       value={notifications.telegram_chat_id ?? ''}
                       onChange={(e) => setNestedValue('notifications.telegram_chat_id', e.target.value)}
                       placeholder="e.g. 838749219"
                       className="w-full bg-slate-950 border border-slate-700/60 text-slate-200 text-sm rounded-lg p-3 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/50 font-mono transition-all shadow-inner"
                     />
                   </div>
                 </div>
               </CardContent>
             </Card>

             {/* Event Triggers */}
             <Card className="bg-slate-900/50 border-slate-800 opacity-100 transition-opacity">
               <CardHeader className="py-5 border-b border-slate-800/50 bg-slate-950/20">
                 <CardTitle className="text-base flex items-center gap-2">
                   <MessageSquare className="text-slate-300" size={18} /> Alert Preferences & Triggers
                 </CardTitle>
               </CardHeader>
               <CardContent className="p-0">
                 <div className="divide-y divide-slate-800/50">
                   
                   {/* Trade Executions */}
                   <div className="p-6 flex flex-col sm:flex-row sm:items-start justify-between gap-6 hover:bg-slate-800/20 transition-colors">
                     <div className="flex gap-4">
                       <div className="mt-1 w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center shrink-0">
                         <Activity className="text-blue-400" size={16} />
                       </div>
                       <div>
                         <h4 className="font-bold text-slate-200 text-sm">Trade Executions</h4>
                         <p className="text-xs text-slate-500 mt-1 leading-relaxed max-w-xl">
                           Receive an instant message whenever a specialist agent successfully opens, modifies, or closes a position on the exchange.
                         </p>
                       </div>
                     </div>
                     <div className="sm:mt-2">
                       <Toggle enabled={!!notifications.alert_on_trade} onChange={(v) => setNestedValue('notifications.alert_on_trade', v)} />
                     </div>
                   </div>

                   {/* Stop-Loss */}
                   <div className="p-6 flex flex-col sm:flex-row sm:items-start justify-between gap-6 hover:bg-slate-800/20 transition-colors">
                     <div className="flex gap-4">
                       <div className="mt-1 w-8 h-8 rounded-lg bg-rose-500/10 flex items-center justify-center shrink-0">
                         <TrendingDown className="text-rose-400" size={16} />
                       </div>
                       <div>
                         <h4 className="font-bold text-slate-200 text-sm">Stop-Loss Triggers</h4>
                         <p className="text-xs text-slate-500 mt-1 leading-relaxed max-w-xl">
                           Get immediately notified if a position goes against you and hits the absolute stop-loss safety net.
                         </p>
                       </div>
                     </div>
                     <div className="sm:mt-2">
                       <Toggle enabled={!!notifications.alert_on_stop_loss} onChange={(v) => setNestedValue('notifications.alert_on_stop_loss', v)} />
                     </div>
                   </div>

                   {/* Daily Summary */}
                   <div className="p-6 flex flex-col gap-4 hover:bg-slate-800/20 transition-colors">
                     <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-6">
                       <div className="flex gap-4">
                         <div className="mt-1 w-8 h-8 rounded-lg bg-amber-500/10 flex items-center justify-center shrink-0">
                           <Calendar className="text-amber-400" size={16} />
                         </div>
                         <div>
                           <h4 className="font-bold text-slate-200 text-sm">Daily P&L Summary</h4>
                           <p className="text-xs text-slate-500 mt-1 leading-relaxed max-w-xl">
                             Receive a comprehensive end-of-day report detailing total profit/loss, win rate, and outstanding positions.
                           </p>
                         </div>
                       </div>
                       <div className="sm:mt-2">
                         <Toggle enabled={!!notifications.daily_summary_enabled} onChange={(v) => setNestedValue('notifications.daily_summary_enabled', v)} />
                       </div>
                     </div>
                     
                     {/* Schedule input shown conditionally below Daily Summary */}
                     <div className={cx(
                       "mt-2 ml-12 p-4 bg-slate-950/50 rounded-lg border border-slate-800/60 transition-all duration-300",
                       notifications.daily_summary_enabled ? "opacity-100 block" : "opacity-50 hidden"
                     )}>
                       <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                         <Clock size={12} /> Delivery Schedule (Hour in EST)
                       </label>
                       <div className="flex items-center gap-3">
                         <input 
                           type="number" min="0" max="23" step="1"
                           value={notifications.daily_summary_hour ?? 16}
                           onChange={(e) => setNestedValue('notifications.daily_summary_hour', Number(e.target.value))}
                           className="w-20 bg-slate-900 border border-slate-700/60 text-slate-200 text-sm rounded p-2 outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500/50 font-mono text-center"
                         />
                         <span className="text-xs text-slate-500">
                           Report will be sent at {notifications.daily_summary_hour ?? 16}:00 EST. (Traditional market close).
                         </span>
                       </div>
                     </div>
                   </div>

                 </div>
               </CardContent>
             </Card>
          </div>
        )}
      </div>
    </div>
  );
};
