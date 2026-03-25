import React, { useState } from 'react';
import { useAdminConfig } from '../../hooks/useApi';
import { api } from '../../services/api';
import {
  Settings, ServerOff, UserPlus, Gauge, AlertTriangle, PowerOff, Loader2
} from 'lucide-react';

export const GlobalSettingsPage: React.FC = () => {
  const { data: config, loading, error, refetch } = useAdminConfig();
  const [updating, setUpdating] = useState<string | null>(null);
  const [leverageInput, setLeverageInput] = useState<string>('');

  React.useEffect(() => {
    if (config && !leverageInput) {
      setLeverageInput(config.global_max_leverage.toString());
    }
  }, [config, leverageInput]);

  const handleToggle = async (key: 'maintenance_mode' | 'allow_registration') => {
    if (!config) return;
    try {
      setUpdating(key);
      const newValue = !config[key];
      // Optimistic update via refetch callback simulation or direct UI flip (SWR takes care of it, we just await)
      await api.admin.updateConfig({ [key]: newValue });
      await refetch();
    } catch (e: any) {
      alert(e.message || `Failed to update ${key}`);
    } finally {
      setUpdating(null);
    }
  };

  const handleUpdateLeverage = async () => {
    const lev = parseInt(leverageInput, 10);
    if (isNaN(lev) || lev < 1 || lev > 100) return alert('Leverage must be between 1 and 100');
    if (!config || lev === config.global_max_leverage) return;

    try {
      setUpdating('leverage');
      await api.admin.updateConfig({ global_max_leverage: lev });
      await refetch();
    } catch (e: any) {
      alert(e.message || 'Failed to update leverage');
    } finally {
      setUpdating(null);
    }
  };

  const handleKillSwitch = () => {
    if (window.confirm('🚨 WARNING 🚨\n\nThis will instantly halt all trading activity, kill active agents, and force the API into emergency maintenance mode. Are you sure?')) {
      handleToggle('maintenance_mode'); // Acting as emergency stop
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96 gap-3 text-slate-400">
        <Loader2 size={20} className="animate-spin" />
        <span className="text-sm font-medium">Loading platform configuration...</span>
      </div>
    );
  }

  if (error || !config) {
    return (
      <div className="bg-rose-500/10 border border-rose-500/20 rounded-xl p-4 text-rose-300 text-sm">
        {error || 'Failed to load configuration'}
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3 mb-8">
        <div className="w-10 h-10 rounded-xl bg-linear-to-br from-slate-600 to-slate-800 flex items-center justify-center shadow-lg border border-slate-700">
          <Settings size={20} className="text-slate-300" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-white">Global Settings</h2>
          <p className="text-xs text-slate-400">Manage platform-wide configurations and emergency overrides</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* System Toggles */}
        <div className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50 rounded-2xl p-6 shadow-lg space-y-6">
          <h3 className="text-sm font-bold text-slate-300 tracking-wider uppercase mb-4 flex items-center gap-2">
            <ServerOff size={16} className="text-blue-400" /> System State
          </h3>
          
          <div className="flex items-center justify-between p-4 rounded-xl bg-slate-950/50 border border-slate-800/80">
            <div>
              <p className="font-semibold text-slate-200">Maintenance Mode</p>
              <p className="text-xs text-slate-500 mt-1">Stops API trades and shows 503 to active agents.</p>
            </div>
            <button
              onClick={() => handleToggle('maintenance_mode')}
              disabled={updating === 'maintenance_mode'}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${config.maintenance_mode ? 'bg-rose-500' : 'bg-slate-700'} disabled:opacity-50`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${config.maintenance_mode ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
          </div>

          <div className="flex items-center justify-between p-4 rounded-xl bg-slate-950/50 border border-slate-800/80">
            <div>
              <p className="font-semibold text-slate-200 flex items-center gap-2">
                <UserPlus size={16} className="text-cyan-400" /> Allow Registrations
              </p>
              <p className="text-xs text-slate-500 mt-1">Open public account creation endpoint.</p>
            </div>
            <button
              onClick={() => handleToggle('allow_registration')}
              disabled={updating === 'allow_registration'}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${config.allow_registration ? 'bg-emerald-500' : 'bg-slate-700'} disabled:opacity-50`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${config.allow_registration ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
          </div>
        </div>

        {/* Risk Controls */}
        <div className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50 rounded-2xl p-6 shadow-lg space-y-6">
          <h3 className="text-sm font-bold text-slate-300 tracking-wider uppercase mb-4 flex items-center gap-2">
            <Gauge size={16} className="text-amber-400" /> Risk Controls
          </h3>

          <div className="p-4 rounded-xl bg-slate-950/50 border border-slate-800/80 space-y-3">
            <div>
              <p className="font-semibold text-slate-200">Global Max Leverage</p>
              <p className="text-xs text-slate-500 mt-1">Absolute leverage cap imposed on all user agents.</p>
            </div>
            <div className="flex items-center gap-3">
              <input 
                type="number"
                min="1"
                max="100"
                value={leverageInput}
                onChange={(e) => setLeverageInput(e.target.value)}
                className="w-24 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-amber-500/50 transition-colors"
              />
              <span className="text-slate-500 font-mono">x</span>
              <div className="flex-1" />
              <button
                onClick={handleUpdateLeverage}
                disabled={updating === 'leverage' || leverageInput === config.global_max_leverage.toString()}
                className="px-4 py-2 bg-amber-500/10 text-amber-500 text-sm font-bold rounded-lg border border-amber-500/20 hover:bg-amber-500/20 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {updating === 'leverage' ? <Loader2 size={14} className="animate-spin" /> : 'Save'}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Danger Zone */}
      <div className="mt-8 border border-rose-900/50 bg-rose-950/20 rounded-2xl p-6 relative overflow-hidden">
        <div className="absolute top-0 right-0 p-8 opacity-5">
          <AlertTriangle size={150} className="text-rose-500" />
        </div>
        <div className="relative z-10 space-y-4">
          <h3 className="text-sm font-bold text-rose-500 tracking-wider uppercase flex items-center gap-2">
            <AlertTriangle size={16} /> Danger Zone
          </h3>
          <p className="text-sm text-rose-200/70 max-w-2xl">
            Actions here have immediate, irreversible platform-wide consequences. Ensure you have proper authorization before triggering emergency protocols.
          </p>
          <div className="pt-2">
            <button 
              onClick={handleKillSwitch}
              className="flex items-center gap-2 px-6 py-3 bg-rose-600 hover:bg-rose-700 text-white font-bold rounded-xl shadow-[0_0_20px_rgba(225,29,72,0.4)] hover:shadow-[0_0_30px_rgba(225,29,72,0.6)] transition-all"
            >
              <PowerOff size={18} />
              ENGAGE KILL SWITCH
            </button>
          </div>
        </div>
      </div>

    </div>
  );
};
