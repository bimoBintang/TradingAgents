import React from 'react';
import { WifiOff, RefreshCw } from 'lucide-react';

export const OfflinePage: React.FC = () => {
  return (
    <div className="flex h-screen w-screen flex-col items-center justify-center bg-slate-950 text-slate-100 overflow-hidden relative">
      {/* Background radial gradient */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,var(--tw-gradient-stops))] from-slate-900 via-slate-950 to-slate-950 -z-10" />

      {/* Decorative circles */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 h-64 border border-slate-800/30 rounded-full animate-pulse opacity-20" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 border border-slate-800/20 rounded-full animate-pulse opacity-10" style={{ animationDelay: '0.5s' }} />

      <div className="z-10 flex flex-col items-center text-center max-w-md px-6">
        <div className="w-24 h-24 rounded-full bg-slate-900 border border-slate-800 shadow-2xl flex items-center justify-center mb-8 relative">
          <div className="absolute inset-0 bg-rose-500/10 rounded-full blur-xl" />
          <WifiOff size={40} className="text-rose-400 relative z-10" />
        </div>

        <h1 className="text-3xl font-bold tracking-tight text-white mb-3">
          No Internet Connection
        </h1>
        
        <p className="text-slate-400 mb-10 leading-relaxed text-sm">
          It looks like you're offline. TradingAgents requires an active connection to sync market data and AI insights. Please check your network settings.
        </p>

        <button 
          onClick={() => window.location.reload()}
          className="group relative flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold py-3 px-8 rounded-xl shadow-[0_0_20px_rgba(37,99,235,0.3)] transition-all overflow-hidden"
        >
          <div className="absolute inset-0 bg-white/20 translate-y-full group-hover:translate-y-0 transition-transform duration-300 ease-out" />
          <RefreshCw size={16} className="relative z-10 group-hover:rotate-180 transition-transform duration-500" />
          <span className="relative z-10">Try Again</span>
        </button>
      </div>

      <div className="absolute bottom-8 text-xs text-slate-600 font-mono">
        Waiting for network...
      </div>
    </div>
  );
};
