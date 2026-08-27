/**
 * WebSocket hooks for real-time dashboard updates.
 *
 * usePortfolioWS() — connects to ws /ws/portfolio, auto-reconnects,
 * falls back to SWR polling if WebSocket fails.
 * useChartControlWS() — connects to ws /ws/chart-control (Fase 7):
 * reports this tab's chart state, receives MCP-driven chart commands.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import type { Portfolio } from '../services/api';

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

/** Convert http(s) URL to ws(s) URL */
function getWsBase(): string {
  return BASE.replace(/^http/, 'ws');
}

/** Get Clerk JWT token for WebSocket auth */
async function getToken(): Promise<string> {
  const clerk = (window as any).Clerk;
  if (clerk?.session) {
    return (await clerk.session.getToken()) ?? '';
  }
  return '';
}

// ── Defaults ─────────────────────────────────────────────────────────

const EMPTY_PORTFOLIO: Portfolio = {
  cash_balance: 0, total_equity: 0, total_pnl: 0, daily_pnl: null,
  win_rate: 0, max_drawdown_pct: 0, total_trades: 0, open_positions: [],
};

type WsStatus = 'connecting' | 'connected' | 'disconnected';

const MAX_RECONNECT_DELAY = 30_000; // 30s cap

// ── usePortfolioWS ───────────────────────────────────────────────────

export function usePortfolioWS() {
  const [data, setData] = useState<Portfolio>(EMPTY_PORTFOLIO);
  const [status, setStatus] = useState<WsStatus>('connecting');
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  // Generation counter — invalidates any in-flight async connect() chain
  // from a superseded effect run. A plain boolean "mountedRef" is not
  // enough under StrictMode: its double mount/cleanup/mount cycle resets
  // the flag back to true while the FIRST connect() call is still
  // awaiting getToken(), letting it resume and open a second, duplicate
  // WebSocket whose events race the real one — flooding OverviewPage's
  // connection-status badge with rapid, out-of-order re-renders that
  // triggered the "insertBefore" DOM crash right after sign-in.
  const generationRef = useRef(0);

  const connect = useCallback(async (generation: number) => {
    if (generationRef.current !== generation) return;

    const token = await getToken();
    if (generationRef.current !== generation) return; // superseded while awaiting

    if (!token) {
      // No auth token — wait and retry
      setStatus('disconnected');
      setTimeout(() => connect(generation), 3000);
      return;
    }

    const url = `${getWsBase()}/ws/portfolio?token=${token}`;
    setStatus('connecting');

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (generationRef.current !== generation) return;
        setStatus('connected');
        retryRef.current = 0; // Reset backoff on success
      };

      ws.onmessage = (event) => {
        if (generationRef.current !== generation) return;
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'portfolio_update' && msg.data) {
            setData(msg.data);
          }
        } catch {
          // Ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (generationRef.current !== generation) return;
        setStatus('disconnected');
        // Exponential backoff: 1s, 2s, 4s, 8s, ... capped at 30s
        const delay = Math.min(1000 * 2 ** retryRef.current, MAX_RECONNECT_DELAY);
        retryRef.current += 1;
        setTimeout(() => connect(generation), delay);
      };

      ws.onerror = () => {
        ws.close(); // Triggers onclose → reconnect
      };
    } catch {
      setStatus('disconnected');
      setTimeout(() => connect(generation), 3000);
    }
  }, []);

  useEffect(() => {
    const generation = ++generationRef.current;
    connect(generation);

    return () => {
      generationRef.current += 1; // invalidate this generation
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connect]);

  return { data, status };
}

// ── useAnalysisWS ────────────────────────────────────────────────────

interface AnalysisStatus {
  task_id: string;
  status: string;
  ticker?: string;
  result?: any;
  error?: string;
}

export function useAnalysisWS(taskId: string | null) {
  const [data, setData] = useState<AnalysisStatus | null>(null);
  const [status, setStatus] = useState<WsStatus>('disconnected');
  const wsRef = useRef<WebSocket | null>(null);
  // Same StrictMode-safe generation guard as usePortfolioWS — see the
  // comment there for why a plain "mountedRef" boolean isn't sufficient.
  const generationRef = useRef(0);

  useEffect(() => {
    const generation = ++generationRef.current;

    if (!taskId) return;

    const connectWs = async () => {
      const token = await getToken();
      if (!token || generationRef.current !== generation) return;

      const url = `${getWsBase()}/ws/analysis/${taskId}?token=${token}`;
      setStatus('connecting');

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (generationRef.current === generation) setStatus('connected');
      };

      ws.onmessage = (event) => {
        if (generationRef.current !== generation) return;
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'analysis_status') {
            setData(msg);
            // Auto-close on terminal state
            if (msg.status === 'completed' || msg.status === 'failed') {
              setStatus('disconnected');
            }
          }
        } catch { /* ignore */ }
      };

      ws.onclose = () => {
        if (generationRef.current === generation) setStatus('disconnected');
      };
    };

    connectWs();

    return () => {
      generationRef.current += 1;
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [taskId]);

  return { data, status };
}

// ── useChartControlWS ────────────────────────────────────────────────
//
// Fase 7 — lets an MCP client (Claude, via mcp_server/tools_chart.py)
// read/drive THIS tab's chart. Bidirectional over one connection:
//   outgoing: {"type": "chart_state", "data": {...}} — call sendState()
//     whenever ticker/timeframe/indicator changes, so MCP's
//     get_chart_state() tool has something current to read.
//   incoming: {"type": "chart_command", "action": ..., ...} — dispatched
//     to the matching handler in ChartControlHandlers.
//
// Best-effort by design: if this channel never connects (e.g. an
// ad-blocker, or the backend doesn't have it yet), the chart itself
// still works fully — this only adds remote-control, nothing the UI
// depends on.

export interface ChartControlHandlers {
  onSetView?: (ticker: string, timeframe?: string | null, indicator?: string | null) => void;
  onAnnotatePatterns?: (ticker: string, timeframe: string) => void;
  onHighlightPriceLevel?: (ticker: string, price: number, label: string, color?: string) => void;
  onClearAiHighlights?: (ticker: string) => void;
}

interface ChartStateReport {
  ticker: string;
  timeframe?: string;
  activeIndicator?: string;
}

const CHART_CONTROL_RETRY_DELAY = 5000;

export function useChartControlWS(handlers: ChartControlHandlers) {
  const wsRef = useRef<WebSocket | null>(null);
  const generationRef = useRef(0);
  // Ref mirror of the latest handlers so the WS's onmessage closure
  // (bound once per connection) always calls current callbacks without
  // needing to reconnect every time a handler identity changes.
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  const sendState = useCallback((state: ChartStateReport) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'chart_state', data: state }));
    }
  }, []);

  useEffect(() => {
    const generation = ++generationRef.current;

    const connect = async () => {
      if (generationRef.current !== generation) return;
      const token = await getToken();
      if (!token || generationRef.current !== generation) return;

      const ws = new WebSocket(`${getWsBase()}/ws/chart-control?token=${token}`);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        if (generationRef.current !== generation) return;
        let msg: any;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }
        if (msg.type !== 'chart_command') return;

        const h = handlersRef.current;
        switch (msg.action) {
          case 'set_view':
            h.onSetView?.(msg.ticker, msg.timeframe, msg.indicator);
            break;
          case 'annotate_patterns':
            h.onAnnotatePatterns?.(msg.ticker, msg.timeframe ?? '1d');
            break;
          case 'highlight_price_level':
            h.onHighlightPriceLevel?.(msg.ticker, msg.price, msg.label, msg.color);
            break;
          case 'clear_ai_highlights':
            h.onClearAiHighlights?.(msg.ticker);
            break;
        }
      };

      ws.onclose = () => {
        if (generationRef.current !== generation) return;
        setTimeout(connect, CHART_CONTROL_RETRY_DELAY);
      };
    };

    connect();

    return () => {
      generationRef.current += 1;
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, []);

  return { sendState };
}
