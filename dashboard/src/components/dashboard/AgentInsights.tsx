import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { Bot, Zap, Loader2, FileText, Radio, Cpu } from 'lucide-react';
import { cx } from '../../utils/cx';
import { api } from '../../services/api';
import { useAnalyzeResult } from '../../hooks/useApi';

interface AgentInsightsProps {
  ticker: string;
  className?: string;
}

export const AgentInsights: React.FC<AgentInsightsProps> = ({ ticker, className }) => {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  
  // Custom hook polls when taskId is present and status is running/queued
  const { data: analysis, error } = useAnalyzeResult(taskId);

  // Reset analysis when ticker changes
  useEffect(() => {
    setTaskId(null);
  }, [ticker]);

  const handleRunAnalysis = async () => {
    try {
      setIsStarting(true);
      const res = await api.analyze(ticker, false); // auto_execute = false for insights
      setTaskId(res.task_id);
    } catch (err) {
      console.error("Failed to start analysis", err);
    } finally {
      setIsStarting(false);
    }
  };

  const isRunning = isStarting || analysis?.status === 'queued' || analysis?.status === 'running';
  const isFailed = analysis?.status === 'failed' || error;
  const isCompleted = analysis?.status === 'completed';

  // Extract decision safely
  const decision = analysis?.decision;
  const action = typeof decision === 'object' && decision !== null ? (decision as any).action : 'PENDING';
  const confidence = typeof decision === 'object' && decision !== null ? (decision as any).confidence * 100 : 0;
  const reasoning = typeof decision === 'object' && decision !== null ? (decision as any).reasoning : '';
  const reports: any = analysis?.reports || {};

  // Color mappings
  let actionColor = 'text-slate-400 border-slate-700 bg-slate-800/30';
  let confColor = 'bg-slate-600';
  let glowColor = 'bg-slate-500/5';
  
  if (action === 'BUY' || action === 'STRONG BUY') {
    actionColor = 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
    confColor = 'bg-emerald-500';
    glowColor = 'bg-emerald-500/5';
  } else if (action === 'SELL' || action === 'SHORT') {
    actionColor = 'text-rose-400 bg-rose-500/10 border-rose-500/20';
    confColor = 'bg-rose-500';
    glowColor = 'bg-rose-500/5';
  } else if (action === 'HOLD') {
    actionColor = 'text-amber-400 bg-amber-500/10 border-amber-500/20';
    confColor = 'bg-amber-500';
    glowColor = 'bg-amber-500/5';
  }

  return (
    <Card className={cx("border-slate-800 bg-slate-900/50 flex flex-col relative overflow-hidden group shadow-xl", className)}>
      <div className={cx("absolute top-0 right-0 w-64 h-64 rounded-full blur-3xl -mr-10 -mt-10 pointer-events-none transition-colors duration-1000", glowColor)} />

      <CardHeader className="py-4 border-b border-slate-800/80 flex flex-row items-center justify-between shrink-0 relative z-10 bg-slate-950/20">
        <CardTitle className="text-base flex items-center gap-2.5 font-bold tracking-tight text-slate-100">
          <div className="relative flex items-center justify-center p-1.5 rounded-md bg-blue-500/10 border border-blue-500/30">
            {isRunning ? (
              <Radio size={16} className="text-blue-400 animate-pulse" />
            ) : (
              <Cpu size={16} className="text-slate-400 group-hover:text-blue-400 transition-colors" />
            )}
            {isRunning && (
              <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-blue-500"></span>
              </span>
            )}
          </div>
          Live AI Signals
        </CardTitle>
        <div className="flex items-center gap-3">
          <span className={cx("text-[10px] font-bold uppercase tracking-widest flex items-center gap-1.5", isRunning ? "text-blue-400" : "text-slate-500")}>
            {isRunning ? "● ANALYZING" : "IDLE"}
          </span>
          <button 
            onClick={handleRunAnalysis}
            disabled={isRunning}
            className={cx(
              "flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-md border tracking-wide transition-all uppercase",
              isRunning 
                ? "bg-blue-500/10 text-blue-400 border-blue-500/20 cursor-not-allowed opacity-50" 
                : "bg-blue-600 text-white border-blue-500 hover:bg-blue-500 hover:shadow-lg hover:shadow-blue-500/20"
            )}
          >
            {isRunning ? (
              <><Loader2 size={14} className="animate-spin" /> SCANNING</>
            ) : (
              <><Zap size={14} className="fill-current" /> GENERATE</>
            )}
          </button>
        </div>
      </CardHeader>

      <CardContent className="p-0 flex-1 flex flex-col overflow-hidden relative z-10">
        
        {!taskId && !isRunning && !isCompleted && !isFailed && (
           <div className="flex-1 flex flex-col items-center justify-center p-8 text-center gap-3 text-slate-500">
             <div className="w-16 h-16 rounded-2xl bg-slate-800/40 flex items-center justify-center border border-slate-700/50 shadow-inner mb-2">
               <Bot size={32} strokeWidth={1.5} className="text-slate-600" />
             </div>
             <p className="font-semibold text-slate-400">Signal Radar Standby</p>
             <p className="text-[11px] max-w-xs leading-relaxed uppercase tracking-wider text-slate-500/80">Press Generate to ping the LangGraph Brain for macro & quant synthesis on {ticker}.</p>
           </div>
        )}

        {isRunning && (
           <div className="flex-1 flex flex-col justify-center p-8 text-left gap-6 text-slate-400 bg-slate-950/40">
             <div className="flex items-center gap-4">
               <div className="relative flex border border-blue-500/30 bg-blue-500/10 p-3 rounded-xl">
                 <div className="absolute inset-0 rounded-xl border-t-2 border-blue-400 animate-spin" />
                 <Radio size={24} className="text-blue-400" />
               </div>
               <div className="flex flex-col gap-0.5">
                 <span className="font-mono text-sm tracking-widest text-blue-400 font-bold">SYNERGIZING AGENTS</span>
                 <span className="text-[10px] text-slate-500 uppercase tracking-widest">Querying Technical, Fundamental & Risk nodes...</span>
               </div>
             </div>
             
             {/* Fake terminal log progression */}
             <div className="font-mono text-[10px] text-slate-500 flex flex-col gap-2 mt-4 ml-2 border-l-2 border-slate-800 pl-4">
                <div className="flex items-center gap-2 text-slate-400"><span className="text-emerald-500">✓</span> Initializing Workspace for {ticker}</div>
                <div className="flex items-center gap-2 text-slate-400"><span className="text-emerald-500">✓</span> Fetching SEC Filings & Market Data</div>
                <div className="flex items-center gap-2 text-blue-400 animate-pulse"><span>&gt;</span> Evaluating AI Consensus Models...</div>
             </div>
           </div>
        )}

        {isFailed && (
           <div className="flex-1 flex flex-col items-center justify-center p-8 text-center gap-2 text-rose-400 bg-rose-950/20">
             <div className="p-3 bg-rose-500/10 rounded-full border border-rose-500/20 mb-2">
               <Zap size={24} className="text-rose-500" />
             </div>
             <p className="font-bold text-sm tracking-wider uppercase">Signal Generation Failed</p>
             <div className="w-full max-w-sm bg-rose-500/5 p-3 rounded border border-rose-500/10 text-rose-500/80">
               {(error || analysis?.error || "").includes("authentication method") || (error || analysis?.error || "").includes("api_key") ? (
                 <div className="flex flex-col gap-1 text-xs">
                   <strong className="text-rose-400">Missing AI API Key</strong>
                   <span className="opacity-90 leading-relaxed font-sans text-[11px]">
                     Go to <b>System Settings &rarr; AI Language Models</b> to add your provider API Key.
                   </span>
                 </div>
               ) : (
                 <p className="font-mono text-[10px] wrap-break-word">
                   {error || analysis?.error || "Neural network timeout. Please retry."}
                 </p>
               )}
             </div>
           </div>
        )}

        {isCompleted && (
          <div className="flex-1 flex flex-col overflow-y-auto w-full scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-transparent">
            {/* Top recommendation summary */}
            <div className="p-5 flex flex-col gap-5 border-b border-slate-800/50 bg-slate-950/30">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Target Asset</span>
                  <span className="text-xs font-black text-slate-200 bg-slate-800 px-2 py-0.5 rounded border border-slate-700">{ticker}</span>
                </div>
                <div className="text-right flex items-center gap-3">
                  <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Master Verdict</span>
                  <span className={cx("text-xs font-black tracking-widest px-3 py-1 rounded border", actionColor)}>
                    {action}
                  </span>
                </div>
              </div>
              
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-widest">
                  <span className="text-slate-500">Signal Confidence</span>
                  <span className="text-slate-300 font-mono">{Math.round(confidence)}%</span>
                </div>
                <div className="flex items-center gap-3">
                   <div className="flex-1 bg-slate-800/50 rounded-full h-1.5 overflow-hidden border border-slate-700/50">
                     <div className={cx("h-full rounded-full transition-all duration-1000", confColor)} style={{ width: `${Math.round(confidence)}%` }} />
                   </div>
                </div>
              </div>
              
              {reasoning && (
                <div className="mt-2">
                  <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block mb-2">Pre-trade Justification</span>
                  <div className="text-[11px] text-emerald-400 font-mono bg-black/40 p-3.5 rounded-lg border border-slate-800/80 leading-relaxed shadow-inner">
                    <span className="text-slate-600 select-none mr-2">&gt;</span>
                    {reasoning}
                  </div>
                </div>
              )}
            </div>

            {/* Modular Analyst breakdown */}
            <div className="p-4 grid grid-cols-2 gap-3 bg-slate-900/40">
              <div className="col-span-2 mb-1">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Sub-Agent Network Reports</span>
              </div>
              
              {Object.entries(reports).map(([agent, text]: [string, any], idx) => {
                const reportContent = typeof text === 'string' ? text : JSON.stringify(text);
                if (!reportContent) return null;
                
                return (
                  <div key={idx} className="bg-slate-950/50 rounded-xl p-3.5 border border-slate-800/60 hover:border-slate-700 transition-colors col-span-2 lg:col-span-1">
                    <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2 flex items-center gap-1.5">
                      <FileText size={12} className="text-blue-500" />
                      {agent} Node
                    </div>
                    <div className="text-[10px] text-slate-400/80 leading-relaxed font-mono line-clamp-4">
                      {reportContent.replace(/[{}"\\]/g, ' ')}
                    </div>
                  </div>
                );
              })}
              
              {Object.keys(reports).length === 0 && (
                <div className="col-span-2 text-center text-xs text-slate-500 py-6 border border-dashed border-slate-800 rounded-lg">
                  No internal sub-reports generated by network.
                </div>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
