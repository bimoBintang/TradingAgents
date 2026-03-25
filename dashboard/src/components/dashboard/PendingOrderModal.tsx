/**
 * PendingOrderModal — Trade Confirmation Dialog
 *
 * Displays pending orders from the AI analysis that require manual
 * approval before being sent to the exchange. Shows order details,
 * confidence level, risk assessment, and countdown timer.
 */

import { useState, useEffect, useCallback } from 'react';
import {
  getPendingOrders,
  approveOrder,
  rejectOrder,
  type PendingOrder,
  type ApproveRejectResult,
} from '../../services/api';

// ── Styles ───────────────────────────────────────────────────────────

const overlayStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  backgroundColor: 'rgba(0, 0, 0, 0.7)',
  backdropFilter: 'blur(8px)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 9999,
  animation: 'fadeIn 0.3s ease',
};

const modalStyle: React.CSSProperties = {
  background: 'linear-gradient(145deg, #0f172a 0%, #1e293b 100%)',
  border: '1px solid rgba(251, 146, 60, 0.3)',
  borderRadius: '20px',
  padding: '32px',
  width: '520px',
  maxWidth: '95vw',
  maxHeight: '90vh',
  overflowY: 'auto',
  boxShadow: '0 25px 60px rgba(251, 146, 60, 0.15), 0 0 0 1px rgba(251, 146, 60, 0.1)',
  animation: 'slideUp 0.4s ease',
};

const badgeStyle: React.CSSProperties = {
  position: 'fixed',
  top: '16px',
  right: '16px',
  background: 'linear-gradient(135deg, #f97316, #ef4444)',
  color: '#fff',
  padding: '10px 20px',
  borderRadius: '50px',
  fontWeight: 700,
  fontSize: '14px',
  cursor: 'pointer',
  zIndex: 9998,
  boxShadow: '0 4px 20px rgba(249, 115, 22, 0.4)',
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
  animation: 'pulse 2s infinite',
};

// ── Component ────────────────────────────────────────────────────────

export default function PendingOrderModal() {
  const [pendingOrders, setPendingOrders] = useState<PendingOrder[]>([]);
  const [selectedOrder, setSelectedOrder] = useState<PendingOrder | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [result, setResult] = useState<ApproveRejectResult | null>(null);

  // Poll for pending orders every 5 seconds
  const fetchPending = useCallback(async () => {
    try {
      const orders = await getPendingOrders();
      setPendingOrders(orders.filter(o => o.status === 'PENDING'));
    } catch {
      // Silently fail — API may not be ready
    }
  }, []);

  useEffect(() => {
    fetchPending();
    const interval = setInterval(fetchPending, 5000);
    return () => clearInterval(interval);
  }, [fetchPending]);

  // Auto-open modal when first pending order arrives
  useEffect(() => {
    if (pendingOrders.length > 0 && !selectedOrder && !result) {
      setSelectedOrder(pendingOrders[0]);
    }
  }, [pendingOrders, selectedOrder, result]);

  const handleApprove = async (key: string) => {
    setIsProcessing(true);
    try {
      const res = await approveOrder(key);
      setResult(res);
      setSelectedOrder(null);
      fetchPending();
    } catch (e: any) {
      setResult({ success: false, idempotency_key: key, status: 'ERROR', message: e.message });
    } finally {
      setIsProcessing(false);
    }
  };

  const handleReject = async (key: string) => {
    setIsProcessing(true);
    try {
      const res = await rejectOrder(key);
      setResult(res);
      setSelectedOrder(null);
      fetchPending();
    } catch (e: any) {
      setResult({ success: false, idempotency_key: key, status: 'ERROR', message: e.message });
    } finally {
      setIsProcessing(false);
    }
  };

  // Dismiss result toast after 5s
  useEffect(() => {
    if (result) {
      const timer = setTimeout(() => setResult(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [result]);

  const actionColor = (action: string) => {
    if (action.includes('BUY')) return '#22c55e';
    if (action.includes('SELL')) return '#ef4444';
    return '#94a3b8';
  };

  const confidenceColor = (c: number) => {
    if (c >= 0.8) return '#22c55e';
    if (c >= 0.6) return '#f59e0b';
    return '#ef4444';
  };

  return (
    <>
      {/* Inject CSS animations */}
      <style>{`
        @keyframes fadeIn { from { opacity: 0 } to { opacity: 1 } }
        @keyframes slideUp { from { opacity: 0; transform: translateY(30px) } to { opacity: 1; transform: translateY(0) } }
        @keyframes pulse { 0%, 100% { transform: scale(1) } 50% { transform: scale(1.05) } }
        @keyframes shimmer { 0% { background-position: -200% 0 } 100% { background-position: 200% 0 } }
      `}</style>

      {/* Notification Badge */}
      {pendingOrders.length > 0 && !selectedOrder && (
        <div style={badgeStyle} onClick={() => setSelectedOrder(pendingOrders[0])}>
          <span style={{ fontSize: '18px' }}>🔔</span>
          <span>{pendingOrders.length} Pending Order{pendingOrders.length > 1 ? 's' : ''}</span>
        </div>
      )}

      {/* Result Toast */}
      {result && (
        <div style={{
          position: 'fixed', bottom: '24px', right: '24px', zIndex: 10000,
          padding: '14px 24px', borderRadius: '12px',
          background: result.success ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)',
          border: `1px solid ${result.success ? '#22c55e' : '#ef4444'}`,
          color: result.success ? '#86efac' : '#fca5a5',
          fontSize: '14px', fontWeight: 600,
          backdropFilter: 'blur(8px)',
        }}>
          {result.success ? '✅' : '❌'} {result.message}
        </div>
      )}

      {/* Modal Overlay */}
      {selectedOrder && (
        <div style={overlayStyle} onClick={() => !isProcessing && setSelectedOrder(null)}>
          <div style={modalStyle} onClick={e => e.stopPropagation()}>

            {/* Header */}
            <div style={{ textAlign: 'center', marginBottom: '24px' }}>
              <div style={{
                display: 'inline-flex', alignItems: 'center', gap: '8px',
                background: 'rgba(251, 146, 60, 0.1)', padding: '6px 16px',
                borderRadius: '50px', marginBottom: '12px',
              }}>
                <span style={{ fontSize: '20px' }}>⚠️</span>
                <span style={{ color: '#fb923c', fontWeight: 700, fontSize: '13px', letterSpacing: '1px' }}>
                  TRADE CONFIRMATION REQUIRED
                </span>
              </div>
              <h2 style={{ color: '#f1f5f9', fontSize: '22px', fontWeight: 700, margin: '8px 0 4px' }}>
                {selectedOrder.action} {selectedOrder.ticker}
              </h2>
              <p style={{ color: '#64748b', fontSize: '13px' }}>
                Review and approve this trade before it is sent to Binance
              </p>
            </div>

            {/* Order Details Grid */}
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px',
              marginBottom: '20px',
            }}>
              {[
                { label: 'Action', value: selectedOrder.action, color: actionColor(selectedOrder.action) },
                { label: 'Order Type', value: selectedOrder.order_type },
                { label: 'Quantity', value: selectedOrder.quantity.toFixed(6) },
                { label: 'Price', value: `$${selectedOrder.price.toLocaleString(undefined, { maximumFractionDigits: 4 })}` },
                { label: 'Total Value', value: `$${selectedOrder.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}` },
                { label: 'Confidence', value: `${(selectedOrder.confidence * 100).toFixed(1)}%`, color: confidenceColor(selectedOrder.confidence) },
                { label: 'Stop Loss', value: selectedOrder.stop_loss_pct ? `${(selectedOrder.stop_loss_pct * 100).toFixed(1)}%` : 'None' },
                { label: 'Take Profit', value: selectedOrder.take_profit_pct ? `${(selectedOrder.take_profit_pct * 100).toFixed(1)}%` : 'None' },
              ].map((item, i) => (
                <div key={i} style={{
                  background: 'rgba(15, 23, 42, 0.6)', borderRadius: '12px',
                  padding: '12px', border: '1px solid rgba(148, 163, 184, 0.1)',
                }}>
                  <div style={{ color: '#64748b', fontSize: '11px', fontWeight: 600, letterSpacing: '0.5px', marginBottom: '4px' }}>
                    {item.label}
                  </div>
                  <div style={{ color: item.color || '#e2e8f0', fontSize: '15px', fontWeight: 700 }}>
                    {item.value}
                  </div>
                </div>
              ))}
            </div>

            {/* Confidence Bar */}
            <div style={{ marginBottom: '20px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span style={{ color: '#94a3b8', fontSize: '12px', fontWeight: 600 }}>AI CONFIDENCE</span>
                <span style={{ color: confidenceColor(selectedOrder.confidence), fontSize: '12px', fontWeight: 700 }}>
                  {(selectedOrder.confidence * 100).toFixed(1)}%
                </span>
              </div>
              <div style={{ height: '8px', background: 'rgba(30, 41, 59, 0.8)', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{
                  height: '100%', width: `${selectedOrder.confidence * 100}%`,
                  background: `linear-gradient(90deg, ${confidenceColor(selectedOrder.confidence)}, ${confidenceColor(selectedOrder.confidence)}88)`,
                  borderRadius: '4px', transition: 'width 0.5s ease',
                }} />
              </div>
            </div>

            {/* Reasoning */}
            {selectedOrder.reasoning && (
              <div style={{
                background: 'rgba(15, 23, 42, 0.6)', borderRadius: '12px',
                padding: '14px', marginBottom: '20px',
                border: '1px solid rgba(148, 163, 184, 0.1)',
              }}>
                <div style={{ color: '#94a3b8', fontSize: '11px', fontWeight: 600, letterSpacing: '0.5px', marginBottom: '6px' }}>
                  AI REASONING
                </div>
                <p style={{ color: '#cbd5e1', fontSize: '13px', lineHeight: 1.5, margin: 0 }}>
                  {selectedOrder.reasoning.length > 300
                    ? selectedOrder.reasoning.substring(0, 300) + '...'
                    : selectedOrder.reasoning}
                </p>
              </div>
            )}

            {/* Action Buttons */}
            <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
              <button
                onClick={() => handleReject(selectedOrder.idempotency_key)}
                disabled={isProcessing}
                style={{
                  flex: 1, padding: '14px', borderRadius: '12px', border: '1px solid rgba(239, 68, 68, 0.3)',
                  background: 'rgba(239, 68, 68, 0.1)', color: '#fca5a5',
                  fontSize: '15px', fontWeight: 700, cursor: isProcessing ? 'wait' : 'pointer',
                  opacity: isProcessing ? 0.5 : 1, transition: 'all 0.2s',
                }}
              >
                ❌ REJECT
              </button>
              <button
                onClick={() => handleApprove(selectedOrder.idempotency_key)}
                disabled={isProcessing}
                style={{
                  flex: 1, padding: '14px', borderRadius: '12px', border: 'none',
                  background: isProcessing
                    ? 'linear-gradient(90deg, #166534, #15803d, #166534)'
                    : 'linear-gradient(135deg, #22c55e, #16a34a)',
                  backgroundSize: isProcessing ? '200% 100%' : 'auto',
                  animation: isProcessing ? 'shimmer 1.5s infinite' : 'none',
                  color: '#fff', fontSize: '15px', fontWeight: 700,
                  cursor: isProcessing ? 'wait' : 'pointer',
                  opacity: isProcessing ? 0.8 : 1, transition: 'all 0.2s',
                  boxShadow: '0 4px 15px rgba(34, 197, 94, 0.3)',
                }}
              >
                {isProcessing ? '⏳ EXECUTING...' : '✅ APPROVE & EXECUTE'}
              </button>
            </div>

            {/* Disclaimer */}
            <p style={{
              textAlign: 'center', color: '#475569', fontSize: '11px',
              marginTop: '16px', lineHeight: 1.5,
            }}>
              This order will be sent to <strong style={{ color: '#94a3b8' }}>Binance (LIVE)</strong>.
              Real funds will be used. This action cannot be undone.
            </p>
          </div>
        </div>
      )}
    </>
  );
}
