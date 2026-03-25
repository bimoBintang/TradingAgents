/**
 * Custom React hooks for fetching data from the TradingAgents API
 * using SWR (stale-while-revalidate) for caching and automatic updates.
 */

import useSWR from 'swr';
import { api } from '../services/api';
import type { Portfolio, Trade, Performance, EquityPoint, SystemStatus, OHLCVResponse, FibonacciResponse, AdminSystemStats, AdminUserItem } from '../services/api';
import type {
  FVGResponse, IFVGResponse, LiquiditySweepResponse,
  OrderFlowResponse, AnchoredVWAPResponse, VolumeProfileResponse,
  PredictionMarketsResponse,
} from '../types/smc';

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

export function useAnalyzeResult(taskId: string | null) {
  const { data, error, isLoading, mutate } = useSWR(
    taskId ? `/api/analyze/${taskId}` : null,
    () => api.analyzeResult(taskId!),
    {
      refreshInterval: (data) => (data?.status === 'queued' || data?.status === 'running') ? 2000 : 0,
    }
  );
  return { data, loading: isLoading, error: error?.message, refetch: mutate };
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

export function useFibonacci(ticker: string) {
  const { data, error, isLoading, mutate } = useSWR<FibonacciResponse>(
    ticker ? `/api/market-data/fibonacci/${ticker}` : null,
    () => api.fibonacci(ticker),
    { ...MARKET_SWR_OPTS },
  );
  return { data, loading: isLoading, error: error?.message, refetch: mutate };
}

// ── SMC Hooks ────────────────────────────────────────────────────────

export function useFVG(ticker: string) {
  const { data, error, isLoading } = useSWR<FVGResponse>(
    ticker ? `/api/market-data/fvg/${ticker}` : null,
    () => api.fvg(ticker), { ...MARKET_SWR_OPTS },
  );
  return { data, loading: isLoading, error: error?.message };
}

export function useIFVG(ticker: string) {
  const { data, error, isLoading } = useSWR<IFVGResponse>(
    ticker ? `/api/market-data/ifvg/${ticker}` : null,
    () => api.ifvg(ticker), { ...MARKET_SWR_OPTS },
  );
  return { data, loading: isLoading, error: error?.message };
}

export function useLiquiditySweeps(ticker: string) {
  const { data, error, isLoading } = useSWR<LiquiditySweepResponse>(
    ticker ? `/api/market-data/liquidity-sweeps/${ticker}` : null,
    () => api.liquiditySweeps(ticker), { ...MARKET_SWR_OPTS },
  );
  return { data, loading: isLoading, error: error?.message };
}

export function useOrderFlow(ticker: string) {
  const { data, error, isLoading } = useSWR<OrderFlowResponse>(
    ticker ? `/api/market-data/order-flow/${ticker}` : null,
    () => api.orderFlow(ticker), { ...MARKET_SWR_OPTS },
  );
  return { data, loading: isLoading, error: error?.message };
}

export function useAnchoredVWAP(ticker: string) {
  const { data, error, isLoading } = useSWR<AnchoredVWAPResponse>(
    ticker ? `/api/market-data/vwap/${ticker}` : null,
    () => api.anchoredVwap(ticker), { ...MARKET_SWR_OPTS },
  );
  return { data, loading: isLoading, error: error?.message };
}

export function useVolumeProfile(ticker: string) {
  const { data, error, isLoading } = useSWR<VolumeProfileResponse>(
    ticker ? `/api/market-data/volume-profile/${ticker}` : null,
    () => api.volumeProfile(ticker), { ...MARKET_SWR_OPTS },
  );
  return { data, loading: isLoading, error: error?.message };
}

export function usePredictionMarkets(query: string) {
  const { data, error, isLoading } = useSWR<PredictionMarketsResponse>(
    query ? `/api/market-data/prediction-markets/${query}` : null,
    () => api.predictionMarkets(query), { ...MARKET_SWR_OPTS },
  );
  return { data, loading: isLoading, error: error?.message };
}

// ── Admin Hooks ──────────────────────────────────────────────────────

export const useJournalNote = (date: string) => {
  const fetcher = async (url: string) => {
    const headers: Record<string, string> = {};
    const clerk = (window as any).Clerk;
    if (clerk?.session) {
      const token = await clerk.session.getToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error('API error');
    return res.json();
  };

  const { data, error, mutate, isLoading } = useSWR(
    `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/journal/notes?date=${date}`,
    fetcher
  );

  return {
    data: data as { content: string, date: string } | undefined,
    loading: isLoading,
    error,
    mutate
  };
};

export const useJournalHistory = () => {
  const fetcher = async (url: string) => {
    const headers: Record<string, string> = {};
    const clerk = (window as any).Clerk;
    if (clerk?.session) {
      const token = await clerk.session.getToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error('API error');
    return res.json();
  };

  const { data, error, mutate, isLoading } = useSWR(
    `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/journal/notes/history`,
    fetcher
  );

  return {
    data: data as { id: number, date: string, content: string }[] | undefined,
    loading: isLoading,
    error,
    mutate
  };
};

export function useAdminStats() {
  const { data, error, isLoading, mutate } = useSWR<AdminSystemStats>(
    '/api/admin/stats',
    () => api.admin.stats(),
    { refreshInterval: 30000 },
  );
  return { data, loading: isLoading, error: error?.message, refetch: mutate };
}

export function useAdminUsers() {
  const { data, error, isLoading, mutate } = useSWR<AdminUserItem[]>(
    '/api/admin/users',
    () => api.admin.users(),
    { refreshInterval: 30000 },
  );
  return { data: data ?? [], loading: isLoading, error: error?.message, refetch: mutate };
}

export function useAdminConfig() {
  const { data, error, isLoading, mutate } = useSWR<import('../services/api').AdminConfig>(
    '/api/admin/config',
    () => api.admin.getConfig(),
    { refreshInterval: 60000 },
  );
  return { data, loading: isLoading, error: error?.message, refetch: mutate };
}

export function useAdminUserDetails(userId: number | null) {
  const { data, error, isLoading, mutate } = useSWR<import('../services/api').AdminUserDetailsResponse>(
    userId ? `/api/admin/users/${userId}/details` : null,
    () => userId ? api.admin.getUserDetails(userId) : Promise.reject('No ID'),
    { refreshInterval: 15000, revalidateOnFocus: false },
  );
  return { data, loading: isLoading, error: error?.message, refetch: mutate };
}
