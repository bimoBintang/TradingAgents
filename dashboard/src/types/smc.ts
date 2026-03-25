// Smart Money Concepts — TypeScript interfaces
// Single source of truth. Imported by api.ts, useApi.ts, ChartPanel.tsx.

export interface FVGZone {
  type: 'bullish' | 'bearish';
  top: number;
  bottom: number;
  gap_size: number;
  candle_date: string;
  is_filled: boolean;
  fill_pct: number;
}

export interface FVGResponse {
  status: string;
  symbol: string;
  fvgs: FVGZone[];
}

export interface IFVGZone {
  original_type: string;
  inverted_type: string;
  top: number;
  bottom: number;
  original_date: string;
  breach_date: string;
}

export interface IFVGResponse {
  status: string;
  symbol: string;
  ifvgs: IFVGZone[];
}

export interface SweepEvent {
  type: 'buy_side' | 'sell_side';
  swing_price: number;
  sweep_price: number;
  sweep_date: string;
  reversal_confirmed: boolean;
}

export interface LiquiditySweepResponse {
  status: string;
  symbol: string;
  sweeps: SweepEvent[];
}

export interface FlowCandle {
  date: string;
  delta: number;
  cumulative_delta: number;
  buy_vol: number;
  sell_vol: number;
}

export interface OrderFlowSummary {
  net_delta: number;
  avg_delta: number;
  pressure: 'buying' | 'selling' | 'neutral';
}

export interface OrderFlowResponse {
  status: string;
  symbol: string;
  flow: FlowCandle[];
  summary: OrderFlowSummary;
}

export interface VWAPPoint {
  date: string;
  vwap: number;
  price: number;
  deviation_pct: number;
}

export interface AnchoredVWAPResponse {
  status: string;
  symbol: string;
  anchor_date: string;
  anchor_price: number;
  vwap_values: VWAPPoint[];
  current_deviation_pct: number;
}

export interface VolumeBucket {
  price_low: number;
  price_high: number;
  price_mid: number;
  volume: number;
  pct_of_total: number;
  is_value_area: boolean;
  is_poc: boolean;
}

export interface VolumeProfileResponse {
  status: string;
  symbol: string;
  poc_price: number;
  vah_price: number;
  val_price: number;
  buckets: VolumeBucket[];
}

// ── Polymarket Prediction Markets ────────────────────────────────────

export interface PredictionMarketItem {
  question: string;
  yes_price: number;
  no_price: number;
  yes_pct: number;
  volume: number;
  condition_id: string;
}

export interface PredictionEventItem {
  title: string;
  slug: string;
  description: string;
  image: string;
  icon: string;
  tags: string[];
  volume: number;
  liquidity: number;
  start_date: string;
  end_date: string;
  markets: PredictionMarketItem[];
}

export interface PredictionMarketsResponse {
  status: string;
  query: string;
  count: number;
  events: PredictionEventItem[];
  message: string;
}
