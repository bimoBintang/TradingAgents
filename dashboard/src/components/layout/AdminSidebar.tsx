import React, { useState, useEffect } from 'react';
import { 
  Activity,
  ShieldCheck,
  Users,
  Settings
} from 'lucide-react';
import { api } from '../../services/api';

interface AdminSidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  isOpen?: boolean;
}

export const AdminSidebar: React.FC<AdminSidebarProps> = ({ activeTab, setActiveTab, isOpen }) => {
  const [online, setOnline] = useState(false);
  const [latency, setLatency] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    const check = async () => {
      const t0 = performance.now();
      try {
        await api.health();
        if (active) {
          setOnline(true);
          setLatency(Math.round(performance.now() - t0));
        }
      } catch {
        if (active) { setOnline(false); setLatency(null); }
      }
    };
    check();
    const id = setInterval(check, 15000);
    return () => { active = false; clearInterval(id); };
  }, []);

  const navItems = [
    { name: 'Admin Overview', icon: ShieldCheck },
    { name: 'User Management', icon: Users },
    { name: 'Global Settings', icon: Settings },
  ];

  return (
    <aside className={`
      fixed lg:static top-0 left-0 bottom-0 z-50
      w-64 border-r border-amber-900/40 bg-slate-950/95 backdrop-blur-xl flex flex-col
      transition-transform duration-300 ease-in-out h-full
      ${isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
    `}>
      {/* Branding */}
      <div className="flex items-center gap-3 px-6 h-20 border-b border-amber-900/40">
        <div className="w-8 h-8 rounded-lg bg-linear-to-br from-amber-600 to-orange-600 flex items-center justify-center text-white shadow-[0_0_15px_rgba(217,119,6,0.5)]">
          <Activity size={18} strokeWidth={2.5} />
        </div>
        <div>
          <h2 className="text-lg font-bold tracking-tight m-0 text-amber-50">Admin Center</h2>
          <div className="text-[0.65rem] font-bold text-amber-500 tracking-wider">TRADING AGENTS PRO</div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-4 py-6 flex flex-col gap-2">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.name;
          
          return (
            <button
              key={item.name}
              onClick={() => setActiveTab(item.name)}
              className={`
                flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all duration-200 border w-full text-left
                ${isActive 
                  ? 'bg-amber-600/10 text-amber-400 border-amber-600/30 shadow-[0_4px_12px_rgba(217,119,6,0.1)]' 
                  : 'bg-transparent text-slate-400 border-transparent hover:bg-slate-900 hover:text-slate-200'
                }
              `}
            >
              <Icon size={18} strokeWidth={isActive ? 2.5 : 2} className={isActive ? 'text-amber-400' : 'text-slate-500'} />
              {item.name}
            </button>
          );
        })}
      </nav>

      {/* Connection Status — LIVE */}
      <div className="p-6">
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-400">
          <div className="flex items-center gap-2 mb-2 font-semibold text-slate-300">
            <span className="relative flex h-2 w-2">
              {online ? (
                <>
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </>
              ) : (
                <span className="relative inline-flex rounded-full h-2 w-2 bg-rose-500"></span>
              )}
            </span>
            {online ? 'SYSTEM ONLINE' : 'SYSTEM OFFLINE'}
          </div>
          <div className="flex justify-between mt-1">
            <span>Core Latency:</span>
            <span className={`font-mono ${online ? 'text-emerald-400' : 'text-rose-400'}`}>
              {latency !== null ? `${latency}ms` : '—'}
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
};
