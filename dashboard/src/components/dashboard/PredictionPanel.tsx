/**
 * PredictionPanel — Dashboard panel showing Polymarket prediction market data.
 *
 * Displays active prediction events with probability bars, volume info,
 * and color-coded signals (green = bullish, red = bearish, amber = neutral).
 */

import { useState, useMemo } from 'react';
import { TrendingUp, BarChart3, Globe, Loader2, AlertTriangle, RefreshCw, ChevronDown, ChevronUp, Clock, ShieldCheck, BrainCircuit } from 'lucide-react';
import { usePredictionMarkets } from '../../hooks/useApi';
import type { PredictionEventItem, PredictionMarketItem } from '../../types/smc';
import { cx } from '../../utils/cx';

interface PredictionPanelProps {
  ticker?: string;
}

/** Map common tickers to Polymarket search queries */
function tickerToQuery(ticker: string): string {
  const t = ticker.toUpperCase().replace(/-USD$/, '');
  const map: Record<string, string> = {
    'BTC': 'bitcoin',
    'ETH': 'ethereum',
    'SOL': 'solana',
    'NVDA': 'nvidia',
    'TSLA': 'tesla',
    'AAPL': 'apple',
    'GOOGL': 'google',
    'MSFT': 'microsoft',
    'AMZN': 'amazon',
    'META': 'meta',
    'XRP': 'ripple',
  };
  return map[t] || t.toLowerCase();
}

/** Get Tailwind text colors for signals */
function signalTextColor(yesPct: number): string {
  if (yesPct >= 70) return 'text-emerald-400';
  if (yesPct <= 30) return 'text-rose-400';
  return 'text-amber-400';
}

/** Get Tailwind background colors for badges */
function signalBadgeBg(yesPct: number): string {
  if (yesPct >= 70) return 'bg-emerald-500/10 text-emerald-400';
  if (yesPct <= 30) return 'bg-rose-500/10 text-rose-400';
  return 'bg-amber-500/10 text-amber-400';
}

function signalLabel(yesPct: number): string {
  if (yesPct >= 70) return 'Strong YES';
  if (yesPct >= 55) return 'Leaning YES';
  if (yesPct <= 30) return 'Strong NO';
  if (yesPct <= 45) return 'Leaning NO';
  return 'Uncertain';
}

function formatVolume(vol: number): string {
  if (vol >= 1_000_000) return `$${(vol / 1_000_000).toFixed(1)}M`;
  if (vol >= 1_000) return `$${(vol / 1_000).toFixed(0)}K`;
  return `$${vol.toFixed(0)}`;
}

function getDaysRemaining(end_date?: string): { days: number, isExpiring: boolean, expired: boolean } | null {
  if (!end_date) return null;
  const diffTime = new Date(end_date).getTime() - Date.now();
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

  return {
    days: diffDays,
    isExpiring: diffDays > 0 && diffDays <= 7,
    expired: diffDays <= 0
  };
}

function MarketCard({ market }: { market: PredictionMarketItem }) {
  const textColor = signalTextColor(market.yes_pct);
  const badgeClass = signalBadgeBg(market.yes_pct);
  const label = signalLabel(market.yes_pct);
  const isIlliquid = market.volume < 10000;

  // Create gradient depending on sentiment
  const gradientColor = market.yes_pct >= 70 ? '#34d399' : market.yes_pct <= 30 ? '#fb7185' : '#fbbf24';

  return (
    <div className={cx("bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 mb-3 transition-colors hover:bg-slate-800/60 relative group/market shadow-sm", isIlliquid ? 'opacity-60 grayscale-30' : '')}>
      <div className="text-sm text-slate-100 leading-relaxed mb-4 font-semibold pr-16">
        {market.question}
      </div>

      {/* Probability bar */}
      <div className="flex items-center gap-4 mb-4">
        <div className="flex-1 h-3 rounded-full bg-slate-900 overflow-hidden border border-slate-700/60 shadow-inner">
          <div
            className="h-full rounded-full transition-all duration-700 ease-out"
            style={{
              width: `${Math.max(market.yes_pct, 2)}%`,
              background: `linear-gradient(90deg, ${gradientColor}55, ${gradientColor})`
            }}
          />
        </div>
        <span className={cx("text-base font-black min-w-[56px] text-right font-mono tracking-tight", textColor)}>
          {market.yes_pct.toFixed(0)}%
        </span>
      </div>

      {/* Labels */}
      <div className="flex flex-col xl:flex-row justify-between xl:items-center gap-3 mt-3 pt-3 border-t border-slate-700/40">
        <div className="flex items-center gap-2">
          <span className={cx("text-xs font-bold uppercase tracking-wider px-2.5 py-1 rounded-md shadow-sm", badgeClass)}>
            {label}
          </span>
          {isIlliquid && (
            <span className="text-[10px] uppercase tracking-wider text-slate-400 font-bold bg-slate-900 border border-slate-800 px-2 py-1 rounded-md">
              Illiquid
            </span>
          )}
        </div>

        <div className="text-xs text-slate-400 font-medium flex items-center gap-2.5 font-mono bg-slate-900/50 px-3 py-1.5 rounded-lg border border-slate-800/50">
          <span className="text-emerald-400/80">Y: {(market.yes_price || market.yes_pct / 100).toFixed(2)}¢</span>
          <span className="text-slate-600">|</span>
          <span className="text-rose-400/80">N: {(market.no_price || (100 - market.yes_pct) / 100).toFixed(2)}¢</span>
          {market.volume > 0 && (
            <>
              <span className="text-slate-600">|</span>
              <span className="text-slate-300 font-semibold tooltip">
                V: {formatVolume(market.volume)}
              </span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function EventCard({ event }: { event: PredictionEventItem }) {
  const [expanded, setExpanded] = useState(event.markets.length <= 2);
  const timeInfo = getDaysRemaining(event.end_date);

  // Hide expired events
  if (timeInfo?.expired) return null;

  const isHighConfidence = event.liquidity >= 500000;

  return (
    <div className="bg-slate-900/60 border border-slate-700/40 rounded-2xl p-5 mb-4 transition-all shadow-md relative group/event hover:border-slate-600/50">
      {isHighConfidence && (
        <div className="absolute -top-3 -right-3 bg-linear-to-r from-blue-600 to-indigo-600 text-white text-[10px] font-bold uppercase tracking-wider px-3 py-1 rounded-lg shadow-xl flex items-center gap-1.5 z-10 border border-blue-400/40 ring-2 ring-slate-900">
          <ShieldCheck size={12} /> Deep Liquidity
        </div>
      )}

      {/* Event header */}
      <div
        className="cursor-pointer flex items-start gap-4 group"
        onClick={() => setExpanded(!expanded)}
      >
        {/* Event thumbnail or fallback icon */}
        {(event.image || event.icon) ? (
          <div className="w-12 h-12 rounded-xl overflow-hidden shrink-0 mt-0.5 border border-slate-700/50 bg-slate-800">
            <img 
              src={event.image || event.icon} 
              alt="" 
              className="w-full h-full object-cover" 
              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
            />
          </div>
        ) : (
          <div className="bg-slate-800/80 p-2 rounded-xl shrink-0 mt-0.5 border border-slate-700/50 w-12 h-12 flex items-center justify-center">
            <Globe size={18} className="text-blue-400 group-hover:text-blue-300 transition-colors" />
          </div>
        )}
        <div className="flex-1">
          <div className="text-base font-bold text-slate-100 leading-snug transition-colors pr-8">
            <a 
              href={`https://polymarket.com/event/${event.slug}`} 
              target="_blank" 
              rel="noopener noreferrer" 
              className="hover:text-blue-400 hover:underline decoration-blue-500/50 underline-offset-4 transition-all"
              onClick={(e) => e.stopPropagation()}
            >
              {event.title}
            </a>
          </div>
          <div className="text-xs text-slate-400 mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
            {timeInfo && (
              <span className={cx("flex items-center gap-1.5 font-mono font-medium", timeInfo.isExpiring ? "text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-md border border-amber-500/20" : "")}>
                <Clock size={12} /> {timeInfo.days === 1 ? '1 day left' : `${timeInfo.days} days left`}
              </span>
            )}
            {event.volume > 0 && <span className="flex items-center gap-1.5 font-mono font-medium"><span className="text-slate-600">•</span> 💵 {formatVolume(event.volume)} Vol</span>}
            {event.liquidity > 0 && <span className="flex items-center gap-1.5 font-mono font-medium"><span className="text-slate-600">•</span> 💧 {formatVolume(event.liquidity)} Liq</span>}
            {event.markets.length > 0 && <span className="flex items-center gap-1.5 font-medium"><span className="text-slate-600">•</span> {event.markets.length} market{event.markets.length > 1 ? 's' : ''}</span>}
            {/* Tags */}
            {event.tags && event.tags.length > 0 && event.tags.filter(t => t !== 'All').slice(0, 3).map((tag, idx) => (
              <span key={idx} className="text-[10px] font-bold uppercase tracking-wider text-indigo-300 bg-indigo-500/15 border border-indigo-500/25 px-2 py-0.5 rounded-md">
                {tag}
              </span>
            ))}
          </div>
        </div>
        <div className="text-slate-500 ml-2 mt-2 bg-slate-800/50 p-1.5 rounded-md group-hover:bg-slate-700 group-hover:text-slate-300 transition-all">
          {expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
        </div>
      </div>

      {/* Expanded markets & Description */}
      {expanded && (
        <div className="mt-4 pt-4 border-t border-slate-700/40 animate-in slide-in-from-top-2 fade-in duration-300">
          {event.description && (
            <div className="text-sm text-slate-300 mb-5 p-4 rounded-xl bg-slate-800/40 border border-slate-700/50 leading-relaxed font-medium">
              {event.description}
            </div>
          )}
          
          {event.markets.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {event.markets.map((m, i) => (
                <MarketCard key={i} market={m} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function PredictionPanel({ ticker = 'BTC-USD' }: PredictionPanelProps) {
  const query = useMemo(() => tickerToQuery(ticker), [ticker]);
  const { data, loading, error } = usePredictionMarkets(query);

  const events = data?.events || [];
  const hasData = events.length > 0;

  // Calculate Global AI Sentiment Consensus
  const consensusData = useMemo(() => {
    let totalVol = 0;
    let weightedYes = 0;
    events.forEach(ev => {
      ev.markets.forEach(m => {
        if (m.volume > 0) {
          totalVol += m.volume;
          weightedYes += (m.yes_pct * m.volume);
        }
      });
    });

    if (totalVol === 0) return null;
    const avgYesPct = weightedYes / totalVol;

    let stance = 'Neutral';
    let color = 'text-amber-400';
    let bg = 'bg-amber-500/10';
    let borderColor = 'border-amber-500/20';

    if (avgYesPct >= 60) {
      stance = 'Bullish Edge';
      color = 'text-emerald-400';
      bg = 'bg-emerald-500/10';
      borderColor = 'border-emerald-500/20';
    } else if (avgYesPct <= 40) {
      stance = 'Bearish Edge';
      color = 'text-rose-400';
      bg = 'bg-rose-500/10';
      borderColor = 'border-rose-500/20';
    }

    return { pct: avgYesPct, stance, color, bg, borderColor };
  }, [events]);

  return (
    <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-700/50 rounded-2xl p-5 h-full flex flex-col shadow-xl">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6 pb-5 border-b border-slate-800/80">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-linear-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20 shrink-0">
            <TrendingUp size={20} className="text-white" />
          </div>
          <div>
            <h3 className="m-0 text-lg font-bold text-slate-100 tracking-tight">
              Prediction Markets
            </h3>
            <p className="m-0 text-sm font-medium text-slate-400 mt-1">
              Polymarket • Wisdom of the Crowd
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2.5 bg-slate-950 border border-slate-700/60 px-4 py-2 rounded-xl shrink-0 shadow-inner">
          <BarChart3 size={16} className="text-slate-400" />
          <span className="text-sm font-bold text-slate-300 uppercase tracking-widest">
            {query}
          </span>
        </div>
      </div>

      {/* AI Consensus Ring Banner */}
      {consensusData && hasData && !loading && (
        <div className={cx("mb-6 rounded-2xl border-2 p-5 flex items-center justify-between gap-4 shadow-lg backdrop-blur-md transition-all hover:scale-[1.01]", consensusData.bg, consensusData.borderColor)}>
          <div className="flex items-center gap-4">
            <div className={cx("w-12 h-12 rounded-full flex items-center justify-center bg-slate-950/80 shrink-0 border border-white/5 shadow-inner", consensusData.color)}>
              <BrainCircuit size={22} className="opacity-90" />
            </div>
            <div>
              <div className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">Macro AI Consensus</div>
              <div className={cx("text-lg font-black uppercase tracking-wider", consensusData.color)}>
                {consensusData.stance}
              </div>
            </div>
          </div>
          <div className="flex flex-col items-end">
            <div className={cx("text-3xl font-mono font-black leading-none drop-shadow-md tracking-tighter", consensusData.color)}>
              {consensusData.pct.toFixed(1)}%
            </div>
            <div className="text-xs text-slate-400 font-semibold mt-1.5 bg-slate-950/50 px-2 py-0.5 rounded-md border border-slate-800/60">Vol-Weighted</div>
          </div>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto pr-1 scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-transparent">
        {loading && (
          <div className="flex flex-col items-center justify-center gap-3 py-16 text-slate-400">
            <Loader2 size={24} className="animate-spin text-blue-500" />
            <span className="text-xs font-medium uppercase tracking-widest animate-pulse">Scanning probabilities...</span>
          </div>
        )}

        {error && !loading && (
          <div className="flex items-start gap-3 p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm leading-relaxed">
            <AlertTriangle size={18} className="shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {!loading && !error && !hasData && (
          <div className="flex flex-col items-center justify-center gap-3 py-16 text-slate-500 text-sm text-center">
            <div className="w-12 h-12 rounded-full bg-slate-800/50 flex items-center justify-center mb-2">
              <RefreshCw size={24} className="text-slate-400" />
            </div>
            <span>No prediction markets found for <strong className="text-slate-300">"{query}"</strong>.</span>
            <span className="text-xs text-slate-600">Try a different asset ticker.</span>
          </div>
        )}

        {hasData && (
          <div className="flex flex-col gap-1">
            {events.map((ev, i) => (
              <EventCard key={i} event={ev} />
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      {hasData && (
        <div className="border-t border-slate-800/60 pt-3 mt-3 flex justify-between items-center">
          <span className="text-[10px] font-medium text-slate-500 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
            {data?.count || 0} events • Auto-refreshes 5m
          </span>
          <span className="text-[10px] font-bold text-slate-600 uppercase tracking-wider">
            Polymarket.com
          </span>
        </div>
      )}
    </div>
  );
}
