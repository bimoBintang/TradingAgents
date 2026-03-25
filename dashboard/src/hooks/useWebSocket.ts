/**
 * WebSocket hooks for real-time dashboard updates.
 *
 * usePortfolioWS() — connects to ws /ws/portfolio, auto-reconnects,
 * falls back to SWR polling if WebSocket fails.
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
  const mountedRef = useRef(true);

  const connect = useCallback(async () => {
    if (!mountedRef.current) return;

    const token = await getToken();
    if (!token) {
      // No auth token — wait and retry
      setStatus('disconnected');
      setTimeout(() => connect(), 3000);
      return;
    }

    const url = `${getWsBase()}/ws/portfolio?token=${token}`;
    setStatus('connecting');

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setStatus('connected');
        retryRef.current = 0; // Reset backoff on success
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
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
        if (!mountedRef.current) return;
        setStatus('disconnected');
        // Exponential backoff: 1s, 2s, 4s, 8s, ... capped at 30s
        const delay = Math.min(1000 * 2 ** retryRef.current, MAX_RECONNECT_DELAY);
        retryRef.current += 1;
        setTimeout(() => connect(), delay);
      };

      ws.onerror = () => {
        ws.close(); // Triggers onclose → reconnect
      };
    } catch {
      setStatus('disconnected');
      setTimeout(() => connect(), 3000);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      wsRef.current?.close();
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
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;

    if (!taskId) return;

    const connectWs = async () => {
      const token = await getToken();
      if (!token) return;

      const url = `${getWsBase()}/ws/analysis/${taskId}?token=${token}`;
      setStatus('connecting');

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (mountedRef.current) setStatus('connected');
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
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
        if (mountedRef.current) setStatus('disconnected');
      };
    };

    connectWs();

    return () => {
      mountedRef.current = false;
      wsRef.current?.close();
    };
  }, [taskId]);

  return { data, status };
}
