/**
 * Custom React hooks for fetching data from the TradingAgents API
 * using SWR (stale-while-revalidate) for caching and automatic updates.
 */

import useSWR from 'swr';
import { api, getAutopilot, getDecisions } from '../services/api';
import type { Portfolio, Trade, Performance, EquityPoint, SystemStatus, OHLCVResponse } from '../services/api';

// ── Default Fallbacks ────────────────────────────────────────────────

const EMPTY_PORTFOLIO: Portfolio = {
  cash_balance: 0, total_equity: 0, total_pnl: 0, daily_pnl: null,
  win_rate: 0, max_drawdown_pct: 0, total_trades: 0, open_positions: [],
};

const EMPTY_PERFORMANCE: Performance = {
  total_trades: 0, win_rate: 0, profit_factor: 0, sharpe_ratio: 0,
  max_drawdown: 0, avg_pnl: 0, best_trade: 0, worst_trade: 0,
};

const EMPTY_STATUS: SystemStatus = {
  session_id: 'N/A', execution_mode: 'unknown',
  engine_status: {}, uptime_seconds: 0,
};

// ── Exported SWR Hooks ───────────────────────────────────────────────
// We use a refresh interval of 10s for live dashboard feel.

export function usePortfolio() {
  const { data, error, isLoading, mutate } = useSWR('/api/portfolio', () => api.portfolio(), {
    fallbackData: EMPTY_PORTFOLIO,
    refreshInterval: 10000,
  });
  return { data: data!, loading: isLoading, error: error?.message, refetch: mutate };
}

export function useTrades() {
  const { data, error, isLoading, mutate } = useSWR('/api/journal/trades', () => api.trades(), {
    fallbackData: [] as Trade[],
    refreshInterval: 15000,
  });
  return { data: data!, loading: isLoading, error: error?.message, refetch: mutate };
}

export function usePerformance() {
  const { data, error, isLoading, mutate } = useSWR('/api/journal/performance', () => api.performance(), {
    fallbackData: EMPTY_PERFORMANCE,
    refreshInterval: 15000,
  });
  return { data: data!, loading: isLoading, error: error?.message, refetch: mutate };
}

export function useEquityCurve() {
  const { data, error, isLoading, mutate } = useSWR('/api/journal/equity-curve', () => api.equityCurve(), {
    fallbackData: [] as EquityPoint[],
    refreshInterval: 30000,
  });
  return { data: data!, loading: isLoading, error: error?.message, refetch: mutate };
}

export function useStatus() {
  const { data, error, isLoading, mutate } = useSWR('/api/status', () => api.status(), {
    fallbackData: EMPTY_STATUS,
    refreshInterval: 5000,
  });
  return { data: data!, loading: isLoading, error: error?.message, refetch: mutate };
}

// ── Added Remaining Integration Hooks ────────────────────────────────

export function usePositions() {
  const { data, error, isLoading, mutate } = useSWR('/api/portfolio/positions', () => api.positions(), {
    fallbackData: [] as import('../services/api').Position[],
    refreshInterval: 10000,
  });
  return { data: data!, loading: isLoading, error: error?.message, refetch: mutate };
}

export function useExits() {
  const { data, error, isLoading, mutate } = useSWR('/api/portfolio/exits', () => api.exits(), {
    fallbackData: [] as { ticker: string; trigger: string }[],
    refreshInterval: 15000,
  });
  return { data: data!, loading: isLoading, error: error?.message, refetch: mutate };
}

export function useRejections() {
  const { data, error, isLoading, mutate } = useSWR('/api/journal/rejections', () => api.rejections(), {
    fallbackData: {} as Record<string, number>,
    refreshInterval: 30000,
  });
  return { data: data!, loading: isLoading, error: error?.message, refetch: mutate };
}

export function useConfig() {
  const { data, error, isLoading, mutate } = useSWR('/api/config', () => api.config(), {
    fallbackData: { config: {} } as { config: Record<string, unknown> },
    refreshInterval: 60000,
  });
  return { data: data!, loading: isLoading, error: error?.message, refetch: mutate };
}

// ── Market Data Hooks ────────────────────────────────────────────────

const MARKET_SWR_OPTS = {
  refreshInterval: 5 * 60 * 1000,    // 5 minutes
  revalidateOnFocus: false,
  dedupingInterval: 60 * 1000,        // 60 seconds
};

export function useOHLCV(ticker: string, interval = '1d') {
  const { data, error, isLoading, mutate } = useSWR<OHLCVResponse>(
    ticker ? `/api/market-data/ohlcv/${ticker}/${interval}` : null,
    () => api.ohlcv(ticker, interval),
    { fallbackData: { ticker: '', interval: '1d', candles: [], count: 0 }, ...MARKET_SWR_OPTS },
  );
  return { data: data!, loading: isLoading, error: error?.message, refetch: mutate };
}

// ── SMC Hooks ────────────────────────────────────────────────────────


export function useAutopilot() {
  const { data, error, isLoading, mutate } = useSWR('/api/autopilot', () => getAutopilot(), { refreshInterval: 10000 });
  return { data, loading: isLoading, error: error?.message, refetch: mutate };
}

export function useDecisions(limit = 20) {
  const { data, error, isLoading, mutate } = useSWR(['/api/decisions', limit], () => getDecisions(limit), {
    refreshInterval: 15000,
  });
  return { data: data ?? [], loading: isLoading, error: error?.message, refetch: mutate };
}
