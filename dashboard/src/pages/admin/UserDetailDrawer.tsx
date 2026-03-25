import React from 'react';
import { useAdminUserDetails } from '../../hooks/useApi';
import { X, Crown, UserCircle2, Wallet, TrendingUp, Activity, ShieldCheck, ShieldOff, Loader2 } from 'lucide-react';
import { api } from '../../services/api';

interface Props {
  userId: number | null;
  onClose: () => void;
  onRoleChanged: () => void;
}

export const UserDetailDrawer: React.FC<Props> = ({ userId, onClose, onRoleChanged }) => {
  const { data: user, loading, error, refetch } = useAdminUserDetails(userId);
  const [updating, setUpdating] = React.useState(false);

  if (!userId) return null;

  const handleRoleToggle = async () => {
    if (!user) return;
    try {
      setUpdating(true);
      await api.admin.updateUserRole(user.id, !user.is_admin);
      await refetch();
      onRoleChanged(); // trigger parent refresh of the table
    } catch (e: any) {
      alert(e.message || 'Failed to update role');
    } finally {
      setUpdating(false);
    }
  };

  return (
    <>
      <div 
        className="fixed inset-0 bg-slate-950/60 backdrop-blur-sm z-40 transition-opacity"
        onClick={onClose}
      />
      
      <div className={`fixed top-0 right-0 h-full w-full max-w-md bg-slate-900 border-l border-slate-700/50 shadow-2xl z-50 transform transition-transform duration-300 ease-in-out flex flex-col ${userId ? 'translate-x-0' : 'translate-x-full'}`}>
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-slate-800">
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            User Profile
          </h2>
          <button 
            onClick={onClose}
            className="p-2 -mr-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex flex-col items-center justify-center h-40 gap-3 text-slate-400">
              <Loader2 size={24} className="animate-spin" />
              <span className="text-sm">Loading deep metrics...</span>
            </div>
          ) : error || !user ? (
            <div className="bg-rose-500/10 border border-rose-500/20 rounded-xl p-4 text-rose-300 text-sm">
              {error || 'Failed to load user profile'}
            </div>
          ) : (
            <div className="space-y-8">
              {/* Identity Block */}
              <div className="flex items-start gap-4">
                <div className={`w-16 h-16 rounded-2xl flex items-center justify-center shadow-inner border border-white/5 ${user.is_admin ? 'bg-amber-500/20 text-amber-400' : 'bg-slate-800 text-slate-400'}`}>
                  {user.is_admin ? <Crown size={32} /> : <UserCircle2 size={32} />}
                </div>
                <div>
                  <h3 className="text-xl font-bold text-white tracking-tight">{user.name}</h3>
                  <p className="text-sm text-slate-400 font-mono mt-1">{user.email}</p>
                  <p className="text-xs text-slate-500 mt-2">ID: {user.id} • Joined: {new Date(user.created_at).toLocaleDateString()}</p>
                </div>
              </div>

              {/* Status Badge */}
              <div>
                {user.is_admin ? (
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">
                    <ShieldCheck size={14} /> SYSTEM ADMINISTRATOR
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-slate-800 text-slate-300 border border-slate-700">
                    <UserCircle2 size={14} /> STANDARD USER
                  </span>
                )}
              </div>

              {/* Portfolio KPIs */}
              <div className="space-y-3">
                <h4 className="text-xs font-bold tracking-widest text-slate-500 uppercase">Portfolio Metrics</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-4">
                    <div className="flex items-center gap-2 text-slate-400 mb-2">
                      <Wallet size={14} /> <span className="text-xs font-semibold">Balance</span>
                    </div>
                    <span className="text-lg font-mono font-bold text-white">${user.portfolio_balance.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
                  </div>
                  <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-4">
                    <div className="flex items-center gap-2 text-slate-400 mb-2">
                      <TrendingUp size={14} className={user.total_pnl >= 0 ? "text-emerald-400" : "text-rose-400"} /> 
                      <span className="text-xs font-semibold">Total PNL</span>
                    </div>
                    <span className={`text-lg font-mono font-bold ${user.total_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {user.total_pnl >= 0 ? '+' : ''}{user.total_pnl.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                  <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-4">
                    <div className="flex items-center gap-2 text-slate-400 mb-2">
                      <Activity size={14} className="text-blue-400" /> <span className="text-xs font-semibold">Win Rate</span>
                    </div>
                    <span className="text-lg font-mono font-bold text-white">{(user.win_rate * 100).toFixed(1)}%</span>
                  </div>
                  <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-4">
                    <div className="flex items-center justify-between text-slate-400 mb-2">
                      <span className="text-xs font-semibold">Total Trades</span>
                    </div>
                    <span className="text-lg font-mono font-bold text-white">{user.total_trades}</span>
                  </div>
                </div>
              </div>

              {/* Admin Action Zone */}
              <div className="space-y-3 pt-4 border-t border-slate-800">
                <h4 className="text-xs font-bold tracking-widest text-slate-500 uppercase">Access Control</h4>
                <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-4">
                  <p className="text-xs text-slate-400 mb-4 leading-relaxed">
                    Toggle administrative privileges for this account. System administrators bypass risk constraints and can mutate platform settings.
                  </p>
                  <button
                    onClick={handleRoleToggle}
                    disabled={updating}
                    className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-bold transition-all ${
                      user.is_admin
                        ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20 hover:bg-rose-500/20'
                        : 'bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20'
                    } disabled:opacity-50`}
                  >
                    {updating ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : user.is_admin ? (
                      <><ShieldOff size={16} /> Revoke Admin Access</>
                    ) : (
                      <><ShieldCheck size={16} /> Grant Admin Access</>
                    )}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
};
