import React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { Activity } from 'lucide-react';
import { cx } from '../../utils/cx';

interface MarketSelectorProps {
  activeTicker: string;
  onSelectTicker: (ticker: string) => void;
  className?: string;
}

const generateSparkline = (isPositive: boolean) => {
  const data = [];
  let current = 100;
  for (let i = 0; i < 24; i++) {
    const change = (Math.random() - (isPositive ? 0.4 : 0.6)) * 4;
    current += change;
    data.push(current);
  }
  return data;
};

const MARKETS = [
  { ticker: 'BTC-USD', name: 'Bitcoin', price: '$65,240.50', change: '+2.4%', isPositive: true, trend: generateSparkline(true) },
  { ticker: 'ETH-USD', name: 'Ethereum', price: '$3,520.10', change: '+1.8%', isPositive: true, trend: generateSparkline(true) },
  { ticker: 'SOL-USD', name: 'Solana', price: '$145.20', change: '-3.2%', isPositive: false, trend: generateSparkline(false) },
  { ticker: 'NVDA', name: 'NVIDIA Corp', price: '$850.40', change: '+5.1%', isPositive: true, trend: generateSparkline(true) },
  { ticker: 'TSLA', name: 'Tesla Inc', price: '$180.50', change: '-1.2%', isPositive: false, trend: generateSparkline(false) },
];

const Sparkline: React.FC<{ data: number[], color: string }> = ({ data, color }) => {
  const width = 80;
  const height = 20;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const step = width / (data.length - 1);
  
  const points = data.map((val, i) => {
    const x = i * step;
    const y = height - ((val - min) / range) * height;
    return `${x},${y}`;
  }).join(' ');

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
};

export const MarketSelector: React.FC<MarketSelectorProps> = ({ activeTicker, onSelectTicker, className }) => {
  return (
    <Card className={cx("border-slate-800 bg-slate-900/50 flex flex-col", className)}>
      <CardHeader className="px-4 py-3 pb-2 border-b border-slate-800/50 shrink-0">
        <CardTitle className="text-sm flex items-center gap-2 text-slate-200">
          <Activity size={16} className="text-blue-500" />
          Market Pulse
        </CardTitle>
      </CardHeader>
      
      <CardContent className="p-3 pt-2 flex-1 overflow-y-auto">
        <div className="flex flex-col gap-1">
          {MARKETS.map(market => {
            const isActive = activeTicker === market.ticker;
            const trendColor = market.isPositive ? '#10b981' : '#ef4444'; // Use hex for SVG stroke
            const textTrendClass = market.isPositive ? 'text-emerald-500' : 'text-rose-500';
            
            return (
              <button
                key={market.ticker}
                onClick={() => onSelectTicker(market.ticker)}
                className={`
                  w-full px-3 py-2 rounded-lg text-left flex items-center justify-between transition-all duration-150
                  border-b last:border-b-0
                  ${isActive 
                    ? 'bg-blue-600/10 border-transparent shadow-[inset_2px_0_0_#3b82f6]' 
                    : 'bg-transparent border-slate-800/50 hover:bg-slate-800/30'
                  }
                `}
              >
                {/* Left Side: Name and Ticker */}
                <div className="flex flex-col w-24">
                  <span className={`font-semibold text-sm ${isActive ? 'text-blue-400' : 'text-slate-200'}`}>
                    {market.ticker}
                  </span>
                  <span className="text-[10px] text-slate-500 truncate">{market.name}</span>
                </div>

                {/* Middle Side: Sparkline Chart */}
                <div className="flex-1 flex justify-center opacity-80">
                  <Sparkline data={market.trend} color={trendColor} />
                </div>
                
                {/* Right Side: Price and Change */}
                <div className="flex flex-col items-end w-24">
                  <span className="text-sm font-bold text-slate-100 font-mono tracking-tight">
                    {market.price}
                  </span>
                  <span className={`text-[10px] font-semibold ${textTrendClass}`}>
                    {market.change}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
};
