import React, { useState } from 'react';
import { useAdminUsers } from '../../hooks/useApi';
import {
  Users, Search, ShieldCheck, Loader2, Crown, UserCircle2, Eye
} from 'lucide-react';
import { UserDetailDrawer } from './UserDetailDrawer';

export const UserManagementPage: React.FC = () => {
  const { data: users, loading, error, refetch } = useAdminUsers();
  const [search, setSearch] = useState('');
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);

  const filtered = users.filter(u =>
    u.email.toLowerCase().includes(search.toLowerCase()) ||
    u.name.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96 gap-3 text-slate-400">
        <Loader2 size={20} className="animate-spin" />
        <span className="text-sm font-medium">Loading user data...</span>
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

  return (
    <>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-linear-to-br from-blue-600 to-cyan-600 flex items-center justify-center shadow-lg">
              <Users size={20} color="white" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white">User Management</h2>
              <p className="text-xs text-slate-400">{users.length} registered user{users.length !== 1 ? 's' : ''}</p>
            </div>
          </div>

          {/* Search */}
          <div className="relative max-w-xs w-full">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search by name or email..."
              className="w-full bg-slate-900/50 border border-slate-700/50 rounded-xl pl-9 pr-4 py-2.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-all"
            />
          </div>
        </div>

        {/* User Table */}
        <div className="bg-slate-900/40 backdrop-blur-md border border-slate-700/50 rounded-2xl overflow-hidden shadow-lg">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-slate-400 bg-slate-950/50">
              <tr>
                <th className="px-5 py-3.5 font-semibold border-b border-slate-800">User</th>
                <th className="px-5 py-3.5 font-semibold border-b border-slate-800">Email</th>
                <th className="px-5 py-3.5 font-semibold border-b border-slate-800 text-center">Role</th>
                <th className="px-5 py-3.5 font-semibold border-b border-slate-800">Joined</th>
                <th className="px-5 py-3.5 font-semibold border-b border-slate-800 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-5 py-10 text-center text-slate-500">
                    No users found
                  </td>
                </tr>
              )}
              {filtered.map(u => (
                <tr key={u.id} className="border-b border-slate-800/50 hover:bg-slate-800/20 transition-colors">
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center ${u.is_admin ? 'bg-amber-500/20' : 'bg-slate-700/50'}`}>
                        {u.is_admin ? <Crown size={14} className="text-amber-400" /> : <UserCircle2 size={14} className="text-slate-400" />}
                      </div>
                      <span className="font-semibold text-slate-200">{u.name}</span>
                    </div>
                  </td>
                  <td className="px-5 py-4 text-slate-400 font-mono text-xs">{u.email}</td>
                  <td className="px-5 py-4 text-center">
                    {u.is_admin ? (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">
                        <ShieldCheck size={10} /> ADMIN
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold bg-slate-700/40 text-slate-400 border border-slate-600/30">
                        USER
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-4 text-slate-500 text-xs">
                    {u.created_at ? new Date(u.created_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }) : '—'}
                  </td>
                  <td className="px-5 py-4 text-right">
                    <button
                      onClick={() => setSelectedUserId(u.id)}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-slate-800 text-slate-300 border border-slate-700 hover:bg-slate-700 hover:text-white transition-all shadow-sm"
                    >
                      <Eye size={14} /> View Details
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <UserDetailDrawer 
        userId={selectedUserId} 
        onClose={() => setSelectedUserId(null)} 
        onRoleChanged={() => refetch()}
      />
    </>
  );
};
