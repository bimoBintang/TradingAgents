/**
 * Centralized API client for the TradingAgents FastAPI backend.
 *
 * Base URL defaults to http://localhost:8000 but can be overridden
 * via the VITE_API_URL environment variable.
 */

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

import type {
  FVGResponse, IFVGResponse, LiquiditySweepResponse,
  OrderFlowResponse, AnchoredVWAPResponse, VolumeProfileResponse,
  PredictionMarketsResponse,
} from '../types/smc';

// ── Core request function (Bearer Token Injecting) ────────────────────

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(opts?.headers as Record<string, string>),
  };
  
  // Dynamically inject Clerk JWT if active session exists
  const clerk = (window as any).Clerk;
  if (clerk && clerk.session) {
    const token = await clerk.session.getToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  }
  
  const res = await fetch(`${BASE}${path}`, { 
    ...opts, 
    headers,
    // credentials: 'omit' is default, no longer needing 'include' cookies
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `API ${res.status}`);
  }
  return res.json();
}

// ── Types ────────────────────────────────────────────────────────────

export interface AuthUser {
  email: string;
  name: string;
  is_admin?: boolean;
  created_at: string;
}

export interface AuthResponse {
  user: AuthUser;
}

export interface Position {
  ticker: string;
  side: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
}

export interface Portfolio {
  cash_balance: number;
  total_equity: number;
  total_pnl: number;
  daily_pnl: number | null;
  win_rate: number;
  max_drawdown_pct: number;
  total_trades: number;
  open_positions: Position[];
}

export interface Trade {
  id?: string;
  ticker?: string;
  action?: string;
  filled_qty?: number;
  fill_price?: number;
  realized_pnl?: number;
  status?: string;
  fill_time?: string;
  created_at?: string;
}

export interface Performance {
  total_trades: number;
  win_rate: number;
  profit_factor: number;
  sharpe_ratio: number;
  max_drawdown: number;
  avg_pnl: number;
  best_trade: number;
  worst_trade: number;
}

export interface BrokerTestRequest {
  broker: string;
  exchange?: string | null;
  api_key: string;
  api_secret: string;
  password?: string;
  sandbox: boolean;
  market_type?: string;
  quote_currency?: string;
}

export interface BrokerTestResponse {
  success: boolean;
  broker_name: string;
  message: string;
  balance?: Record<string, number> | null;
}

export interface EquityPoint {
  timestamp: string;
  total_equity: number;
  cash?: number;
  drawdown_pct?: number;
}

export interface SystemStatus {
  session_id: string;
  execution_mode: string;
  engine_status: Record<string, unknown>;
  uptime_seconds: number;
}

/**
 * Normalized Trader decision — see api/schemas.py::DecisionSummary and
 * api/routers/analysis.py::_parse_decision() for why this is the ONE
 * shape every consumer gets, regardless of whether the backend's
 * structured extraction succeeded (is_structured: true, most fields
 * populated) or fell back to a bare action word (is_structured: false,
 * only action/raw_text present). Never guess at `decision`'s shape in a
 * component — this interface IS the contract.
 */
export interface DecisionSummary {
  action: string; // BUY | SELL | HOLD | STRONG_BUY | STRONG_SELL
  is_structured: boolean;
  raw_text: string;
  ticker?: string | null;
  confidence_score?: number | null;
  quantity_pct?: number | null;
  order_type?: string | null;
  limit_price?: number | null;
  stop_loss_pct?: number | null;
  take_profit_pct?: number | null;
  reasoning?: string | null;
  key_factors?: string[] | null;
  risk_reward_ratio?: number | null;
  time_horizon?: string | null;
  leverage?: number | null;
  position_side?: string | null;
  margin_type?: string | null;
}

export interface AnalyzeResult {
  task_id: string;
  status: string;
  decision?: DecisionSummary | null;
  order_result?: any;
  reports?: Record<string, string | null>;
  error?: string;
}

// ── API Methods ──────────────────────────────────────────────────────

export const api = {
  // System
  health: () => request<{ status: string; timestamp: string }>('/api/health'),
  status: () => request<SystemStatus>('/api/status'),

  // Portfolio
  portfolio: () => request<Portfolio>('/api/portfolio'),
  positions: () => request<Position[]>('/api/portfolio/positions'),
  exits: () => request<{ ticker: string; trigger: string }[]>('/api/portfolio/exits'),

  // Journal
  trades: (params?: { ticker?: string; start_date?: string; end_date?: string }) => {
    const qs = new URLSearchParams();
    if (params?.ticker) qs.set('ticker', params.ticker);
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    const q = qs.toString();
    return request<Trade[]>(`/api/journal/trades${q ? `?${q}` : ''}`);
  },
  performance: () => request<Performance>('/api/journal/performance'),
  equityCurve: () => request<EquityPoint[]>('/api/journal/equity-curve'),
  rejections: () => request<Record<string, number>>('/api/journal/rejections'),

  // Analysis
  analyze: (ticker: string, auto_execute = false) =>
    request<{ task_id: string }>('/api/analyze', {
      method: 'POST',
      body: JSON.stringify({ ticker, auto_execute }),
    }),
  analyzeResult: (taskId: string) => request<AnalyzeResult>(`/api/analyze/${taskId}`),

  // Config
  config: () => request<{ config: Record<string, unknown> }>('/api/config'),
  testBrokerConnection: (body: BrokerTestRequest) =>
    request<BrokerTestResponse>('/api/config/test-broker', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateConfig: (updates: Record<string, unknown>) =>
    request<{ config: Record<string, unknown> }>('/api/config', {
      method: 'PUT',
      body: JSON.stringify({ updates }),
    }),

  // CSV Export — triggers download with auth
  exportCSV: async () => {
    const headers: Record<string, string> = {};
    const clerk = (window as any).Clerk;
    if (clerk?.session) {
      const token = await clerk.session.getToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }
    const res = await fetch(`${BASE}/api/journal/export`, { headers });
    if (!res.ok) throw new Error(`Export failed: ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trades_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  },

  // Journal Notes
  saveNote: (date: string, content: string) =>
    request<{ date: string; content: string }>('/api/journal/notes', {
      method: 'POST',
      body: JSON.stringify({ date, content }),
    }),

  // Market Data
  ohlcv: (ticker: string, interval = '1d', period = 200) =>
    request<OHLCVResponse>(`/api/market-data/ohlcv?ticker=${encodeURIComponent(ticker)}&interval=${interval}&period=${period}`),
  fibonacci: (ticker: string, period = 90, extensions = true) =>
    request<FibonacciResponse>(`/api/market-data/fibonacci?ticker=${encodeURIComponent(ticker)}&period=${period}&extensions=${extensions}`),

  // SMC
  fvg: (ticker: string, period = 90) =>
    request<FVGResponse>(`/api/market-data/fvg?ticker=${encodeURIComponent(ticker)}&period=${period}`),
  ifvg: (ticker: string, period = 90) =>
    request<IFVGResponse>(`/api/market-data/ifvg?ticker=${encodeURIComponent(ticker)}&period=${period}`),
  liquiditySweeps: (ticker: string, period = 90) =>
    request<LiquiditySweepResponse>(`/api/market-data/liquidity-sweeps?ticker=${encodeURIComponent(ticker)}&period=${period}`),
  orderFlow: (ticker: string, period = 30) =>
    request<OrderFlowResponse>(`/api/market-data/order-flow?ticker=${encodeURIComponent(ticker)}&period=${period}`),
  anchoredVwap: (ticker: string, period = 90) =>
    request<AnchoredVWAPResponse>(`/api/market-data/vwap?ticker=${encodeURIComponent(ticker)}&period=${period}`),
  volumeProfile: (ticker: string, period = 90) =>
    request<VolumeProfileResponse>(`/api/market-data/volume-profile?ticker=${encodeURIComponent(ticker)}&period=${period}`),
  predictionMarkets: (query: string, limit = 10) =>
    request<PredictionMarketsResponse>(`/api/market-data/prediction-markets?query=${encodeURIComponent(query)}&limit=${limit}`),

  // Admin
  admin: {
    stats: () => request<AdminSystemStats>('/api/admin/stats'),
    users: () => request<AdminUserItem[]>('/api/admin/users'),
    updateUserRole: (userId: number, isAdmin: boolean) =>
      request<{ status: string; user_id: number; is_admin: boolean }>(`/api/admin/users/${userId}/role`, {
        method: 'PUT',
        body: JSON.stringify({ is_admin: isAdmin }),
      }),
    getConfig: () => request<AdminConfig>('/api/admin/config'),
    updateConfig: (data: Partial<AdminConfig>) =>
      request<AdminConfig>('/api/admin/config', {
        method: 'PUT',
        body: JSON.stringify(data),
      }),
    getUserDetails: (userId: number) => request<AdminUserDetailsResponse>(`/api/admin/users/${userId}/details`),
  },
};

// ── Admin Types ──────────────────────────────────────────────────────

export interface AdminUserDetailsResponse {
  id: number;
  email: string;
  name: string;
  is_admin: boolean;
  created_at: string;
  portfolio_balance: number;
  total_equity: number;
  total_pnl: number;
  win_rate: number;
  total_trades: number;
  max_drawdown_pct: number;
  active_positions_count: number;
}

export interface AdminConfig {
  maintenance_mode: boolean;
  allow_registration: boolean;
  global_max_leverage: number;
}

export interface AdminSystemStats {
  total_users: number;
  admin_users: number;
  total_trades: number;
  total_platform_volume: number;
  total_equity: number;
  active_positions: number;
  engine_uptime_seconds: number;
}

export interface AdminUserItem {
  id: number;
  email: string;
  name: string;
  is_admin: boolean;
  created_at: string;
  status: string;
}


// ── Market Data Types ────────────────────────────────────────────────

export interface OHLCVCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OHLCVResponse {
  ticker: string;
  interval: string;
  candles: OHLCVCandle[];
  count: number;
}

export interface FibLevel {
  label: string;
  ratio: number;
  price: number;
  type: 'retracement' | 'extension';
}

export interface FibonacciResponse {
  status: string;
  symbol: string;
  period: string;
  data_points: number;
  current_price: number;
  swing_high: number;
  swing_low: number;
  swing_high_date: string | null;
  swing_low_date: string | null;
  trend_direction: string;
  trend_confidence: number;
  is_uptrend: boolean;
  in_golden_zone: boolean;
  levels: FibLevel[];
}

// ── Pending Order Types & API ────────────────────────────────────────

export interface PendingOrder {
  id: string;
  idempotency_key: string;
  ticker: string;
  action: string;
  quantity: number;
  price: number;
  value: number;
  confidence: number;
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  order_type: string;
  time_horizon: string | null;
  reasoning: string;
  key_factors: string[];
  risk_score: number | null;
  status: string;
  created_at: string;
  expires_at?: string | null;
}

export interface ApproveRejectResult {
  success: boolean;
  idempotency_key: string;
  status: string;
  message: string;
  order_id?: string | null;
}

export const getPendingOrders = () =>
  request<PendingOrder[]>('/api/pending-orders');

export const approveOrder = (idempotencyKey: string) =>
  request<ApproveRejectResult>(`/api/pending-orders/${idempotencyKey}/approve`, {
    method: 'POST',
  });

export const rejectOrder = (idempotencyKey: string) =>
  request<ApproveRejectResult>(`/api/pending-orders/${idempotencyKey}/reject`, {
    method: 'POST',
  });
