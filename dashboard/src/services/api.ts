/**
 * Centralized API client for the TradingAgents FastAPI backend.
 *
 * Base URL defaults to http://localhost:8000 but can be overridden
 * via the VITE_API_URL environment variable.
 */

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';


// ── Core request function ─────────────────────────────────────────────

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(opts?.headers as Record<string, string>),
  };

  const res = await fetch(`${BASE}${path}`, { 
    ...opts, 
    headers,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `API ${res.status}`);
  }
  return res.json();
}

// ── Types ────────────────────────────────────────────────────────────

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

  // Market Data
  ohlcv: (ticker: string, interval = '1d', period = 200) =>
    request<OHLCVResponse>(`/api/market-data/ohlcv?ticker=${encodeURIComponent(ticker)}&interval=${interval}&period=${period}`),

};

// ── Market Data Types};

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


// ── Autopilot & AI decisions ─────────────────────────────────────────

export interface AutopilotTicker {
  ticker: string;
  last_run_at: string | null;
  last_status: string | null;
  next_due_at: string;
  market_open: boolean;
}

export interface AutopilotStatus {
  enabled: boolean;
  state: 'running' | 'paused' | 'stopped';
  stopped_reason: string | null;
  stopped_at: string | null;
  running_ticker: string | null;
  last_tick_at: string | null;
  last_error: string | null;
  interval_minutes: number;
  watchlist: string[];
  tickers: AutopilotTicker[];
  market: string;
  broker: string;
  mode: string;
  require_confirmation: boolean;
  auto_execute: boolean;
  goals: { target_profit_pct: number | null; max_loss_pct: number | null; end_at: string | null };
  progress: {
    started_at: string | null;
    start_equity: number | null;
    equity: number;
    change_pct: number | null;
    seconds_left: number | null;
  };
}

export interface AutopilotGoals {
  target_profit_pct?: number | null;
  max_loss_pct?: number | null;
  end_at?: string | null;
}

export interface AIDecision {
  task_id: string;
  ticker: string;
  status: string;
  error: string | null;
  created_at: string | null;
  decision: {
    action: string;
    confidence_score?: number | null;
    reasoning?: string | null;
    key_factors?: string[] | null;
    stop_loss_pct?: number | null;
    take_profit_pct?: number | null;
  } | null;
  order_result: { side?: string; filled_quantity?: number; filled_price?: number; status?: string } | null;
}

export const getAutopilot = () => request<AutopilotStatus>('/api/autopilot');

export const startAutopilot = (goals: AutopilotGoals) =>
  request<AutopilotStatus>('/api/autopilot/start', { method: 'POST', body: JSON.stringify(goals) });

export const pauseAutopilot = () => request<AutopilotStatus>('/api/autopilot/pause', { method: 'POST' });

export const resumeAutopilot = () => request<AutopilotStatus>('/api/autopilot/resume', { method: 'POST' });

export const getDecisions = (limit = 20) => request<AIDecision[]>(`/api/decisions?limit=${limit}`);

export const analyzeNow = (ticker: string) =>
  request<{ task_id: string }>('/api/analyze', {
    method: 'POST',
    body: JSON.stringify({ ticker, auto_execute: true }),
  });
