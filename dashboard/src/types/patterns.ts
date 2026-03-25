/**
 * TypeScript types for the chart pattern detection API.
 * Mirrors the backend Pydantic schemas in api/schemas/patterns.py.
 */

export interface PatternPoint {
  time: number;    // Unix timestamp in seconds
  price: number;
  label: string;
}

export interface ChartPattern {
  type: 'head_and_shoulders' | 'rising_wedge' | 'falling_wedge';
  points: PatternPoint[];
  confidence: number;   // 0.0–1.0
  direction: 'bullish' | 'bearish';
}

export interface PatternResponse {
  ticker: string;
  timeframe: string;
  candle_count: number;
  patterns: ChartPattern[];
  detected_at: number;  // Unix timestamp
}
