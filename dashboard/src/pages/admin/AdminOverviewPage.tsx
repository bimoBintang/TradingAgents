import React from 'react';
import { useAdminStats } from '../../hooks/useApi';
import {
  Users, BarChart3, Wallet, Activity, ShieldCheck, TrendingUp, Server, Loader2
} from 'lucide-react';

const fmt = (n: number) => n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtInt = (n: number) => n.toLocaleString('en-US');

interface MetricCardProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  color: string;
  bgColor: string;
}

function MetricCard({ icon, label, value, sub, color, bgColor }: MetricCardProps) {
  return (
    <div className="relative overflow-hidden bg-slate-900/40 backdrop-blur-md border border-slate-700/50 rounded-2xl p-5 shadow-lg group">
      <div className={`absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity ${color}`}>
        {React.cloneElement(icon as React.ReactElement<any>, { size: 48 })}
      </div>
      <div className="relative z-10">
        <div className="flex items-center gap-2 mb-3">
          <span className={`p-1.5 rounded-lg ${bgColor} ${color}`}>
            {React.cloneElement(icon as React.ReactElement<any>, { size: 16 })}
          </span>
          <span className="text-sm font-semibold text-slate-300">{label}</span>
        </div>
        <div className="text-2xl font-mono font-bold text-white">{value}</div>
        {sub && <div className="text-xs text-slate-400 font-medium mt-2">{sub}</div>}
      </div>
    </div>
  );
}

export const AdminOverviewPage: React.FC = () => {
  const { data: stats, loading, error } = useAdminStats();

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96 gap-3 text-slate-400">
        <Loader2 size={20} className="animate-spin" />
        <span className="text-sm font-medium">Loading admin metrics...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-rose-500/10 border border-rose-500/20 rounded-xl p-4 text-rose-300 text-sm">
        {error}
      </div>
    );
  }

  const s = stats!;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-linear-to-br from-indigo-600 to-purple-600 flex items-center justify-center shadow-lg">
          <ShieldCheck size={20} color="white" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-white">Admin Overview</h2>
          <p className="text-xs text-slate-400">Global platform statistics in real-time</p>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          icon={<Users />}
          label="Total Users"
          value={fmtInt(s.total_users)}
          sub={`${s.admin_users} admin${s.admin_users !== 1 ? 's' : ''}`}
          color="text-blue-400"
          bgColor="bg-blue-500/10"
        />
        <MetricCard
          icon={<BarChart3 />}
          label="Total Trades"
          value={fmtInt(s.total_trades)}
          sub="Platform-wide executions"
          color="text-purple-400"
          bgColor="bg-purple-500/10"
        />
        <MetricCard
          icon={<Wallet />}
          label="Platform Volume"
          value={`$${fmt(s.total_platform_volume)}`}
          sub="Total traded volume"
          color="text-emerald-400"
          bgColor="bg-emerald-500/10"
        />
        <MetricCard
          icon={<TrendingUp />}
          label="Total Equity"
          value={`$${fmt(s.total_equity)}`}
          sub={`${s.active_positions} active position${s.active_positions !== 1 ? 's' : ''}`}
          color="text-amber-400"
          bgColor="bg-amber-500/10"
        />
      </div>

      {/* System Info Card */}
      <div className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50 rounded-2xl p-6 shadow-lg">
        <div className="flex items-center gap-2 mb-4">
          <Server size={16} className="text-cyan-400" />
          <h3 className="text-sm font-semibold text-slate-200">System Status</h3>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div>
            <p className="text-xs text-slate-400 mb-1">Engine</p>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-sm font-mono font-semibold text-emerald-400">Online</span>
            </div>
          </div>
          <div>
            <p className="text-xs text-slate-400 mb-1">API</p>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-sm font-mono font-semibold text-emerald-400">Healthy</span>
            </div>
          </div>
          <div>
            <p className="text-xs text-slate-400 mb-1">LangGraph</p>
            <div className="flex items-center gap-2">
              <Activity size={12} className="text-blue-400" />
              <span className="text-sm font-mono font-semibold text-blue-400">Ready</span>
            </div>
          </div>
          <div>
            <p className="text-xs text-slate-400 mb-1">Database</p>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-sm font-mono font-semibold text-emerald-400">Connected</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
