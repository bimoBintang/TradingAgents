import React from 'react';
import { OpenPositionsTable } from '../components/dashboard/OpenPositionsTable';
import { AllocationChart } from '../components/dashboard/AllocationChart';
import { Card, CardContent } from '../components/ui/Card';

export const PositionsPage: React.FC = () => {
  return (
    <div className="flex flex-col gap-6 h-full pb-8">
      
      {/* Portfolio Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <Card className="bg-slate-900/50">
          <CardContent className="p-5">
            <span className="text-sm font-medium text-slate-400">Total Margin Used</span>
            <div className="text-2xl font-mono font-bold mt-2 text-slate-100">$21,450.00</div>
            <div className="text-sm text-slate-500 font-medium mt-1">
              39% of Total Equity
            </div>
          </CardContent>
        </Card>
        
        <Card className="bg-slate-900/50">
          <CardContent className="p-5">
            <span className="text-sm font-medium text-slate-400">Buying Power</span>
            <div className="text-2xl font-mono font-bold mt-2 text-blue-400">$32,780.50</div>
            <div className="text-sm text-blue-500/70 font-medium mt-1">
              Leverage Available: up to 10x
            </div>
          </CardContent>
        </Card>
        
        <Card className="bg-slate-900/50">
          <CardContent className="p-5">
            <span className="text-sm font-medium text-slate-400">Unrealized P&L</span>
            <div className="text-2xl font-mono font-bold mt-2 text-emerald-500">+$3,296.07</div>
            <div className="text-sm text-emerald-500 font-medium flex items-center gap-1 mt-1">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline><polyline points="17 6 23 6 23 12"></polyline></svg>
              +6.07%
            </div>
          </CardContent>
        </Card>
        
        <Card className="bg-slate-900/50">
          <CardContent className="p-5">
            <span className="text-sm font-medium text-slate-400">Best Performer</span>
            <div className="text-2xl font-mono font-bold mt-2 text-purple-400">ETH-USD</div>
            <div className="text-sm text-emerald-500 font-medium mt-1">
              +20.5% Unrealized
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-12 gap-6 flex-1">
        <AllocationChart className="col-span-12 lg:col-span-4" />
        <OpenPositionsTable className="col-span-12 lg:col-span-8" />
      </div>

    </div>
  );
};
