import React, { useState, useEffect } from 'react';
import axios from 'axios';
import {
  ShieldCheck, ShieldAlert, Bot, ArrowRight, Activity, Terminal,
  AlertTriangle, CheckCircle2, XCircle, Search, Cpu, Lock, Check
} from 'lucide-react';

const API_BASE = `${(import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "")}/api`;
const API_HEADERS = { "X-AgentPay-Key": import.meta.env.VITE_API_AUTH_KEY || "demo-agentpay-key" };

export default function App() {
  const [prompt, setPrompt] = useState("Buy Dell Inspiron laptop within ₹45,000");
  const [budget, setBudget] = useState(45000);
  const [loading, setLoading] = useState(false);
  const [activeStep, setActiveStep] = useState(0); // 0: Idle, 1: Search, 2: Reason, 3: Tier-0/1 Guard, 4: Done
  const [executionResult, setExecutionResult] = useState(null);
  const [auditLogs, setAuditLogs] = useState([]);
  const [escalationData, setEscalationData] = useState(null);
  const [resolvingEscalation, setResolvingEscalation] = useState(false);
  const [sessionId] = useState(() => {
    const existing = window.localStorage.getItem("agentpay_session_id");
    const value = existing || `sess_dashboard_${crypto.randomUUID().slice(0, 8)}`;
    window.localStorage.setItem("agentpay_session_id", value);
    return value;
  });

  const fetchLogs = async () => {
    try {
      const res = await axios.get(`${API_BASE}/audit/logs`, { headers: API_HEADERS });
      setAuditLogs(res.data.logs || []);
    } catch (err) {
      console.error("Failed to load logs:", err);
    }
  };

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 3500);
    return () => clearInterval(interval);
  }, []);

  const handleRunAgent = async (e) => {
    e.preventDefault();
    setLoading(true);
    setExecutionResult(null);
    setEscalationData(null);
    setActiveStep(1);

    try {
      // Simulate visual state progression for Loom recording
      setTimeout(() => setActiveStep(2), 250);
      setTimeout(() => setActiveStep(3), 500);

      const res = await axios.post(`${API_BASE}/agent/run`, {
        user_prompt: prompt,
        user_budget: parseFloat(budget),
        session_id: sessionId
      }, { headers: API_HEADERS });

      setExecutionResult(res.data);
      setActiveStep(4);

      if (res.data.gateway_decision?.decision === "REQUIRE_HUMAN_APPROVAL") {
        setEscalationData(res.data.gateway_decision);
      }
      fetchLogs();
    } catch (err) {
      alert("Execution error: " + err.message);
      setActiveStep(0);
    } finally {
      setLoading(false);
    }
  };

  const handleResolveEscalation = async (approved) => {
    if (!escalationData?.escalation_token) return;
    setResolvingEscalation(true);
    try {
      const res = await axios.post(`${API_BASE}/gateway/escalate/resolve`, {
        escalation_token: escalationData.escalation_token,
        approved
      }, { headers: API_HEADERS });

      // Update view with resolved outcome
      setExecutionResult(prev => ({
        ...prev,
        gateway_decision: {
          ...prev.gateway_decision,
          decision: approved ? "ALLOW" : "BLOCK",
          reason: approved ? "Approved via User Step-Up Consent." : "Rejected by User Consent Gate.",
          order_details: res.data.order || null
        }
      }));
      setEscalationData(null);
      fetchLogs();
    } catch (err) {
      alert("Failed to resolve escalation: " + err.message);
    } finally {
      setResolvingEscalation(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans p-6">
      {/* Top Bar */}
      <header className="max-w-7xl mx-auto flex items-center justify-between pb-6 border-b border-slate-800">
        <div className="flex items-center space-x-3">
          <div className="p-2.5 bg-indigo-600 rounded-xl shadow-lg shadow-indigo-500/20">
            <ShieldCheck className="w-6 h-6 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold tracking-tight">AgentPay-Guard</h1>
              <span className="text-[10px] bg-indigo-950 text-indigo-300 border border-indigo-800 px-2 py-0.5 rounded font-mono">
                AP2 simulation / x402 Gateway
              </span>
            </div>
            <p className="text-xs text-slate-400">Zero-Trust Invariant Firewall for Autonomous Agentic Commerce</p>
          </div>
        </div>
        <div className="flex items-center space-x-3 text-xs">
          <div className="flex items-center space-x-2 bg-slate-900 border border-slate-800 px-3.5 py-1.5 rounded-full">
            <Activity className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
            <span className="text-slate-300 font-mono">Razorpay Sandbox Connected</span>
          </div>
        </div>
      </header>

      {/* Main Grid */}
      <main className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-6 mt-6">

        {/* Left Column: Interactive Agent Studio */}
        <div className="lg:col-span-5 space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-4 flex items-center gap-2">
              <Bot className="w-4 h-4 text-indigo-400" />
              Autonomous Shopping Agent Studio
            </h2>

            <form onSubmit={handleRunAgent} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">User Intent & Prompt</label>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all placeholder:text-slate-600"
                  rows={3}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">Authorized Budget Cap (₹ INR)</label>
                <input
                  type="number"
                  value={budget}
                  onChange={(e) => setBudget(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium py-2.5 rounded-lg text-sm transition-all flex items-center justify-center gap-2 shadow-lg shadow-indigo-600/20"
              >
                {loading ? "Agent Reasoning & Intercepting..." : "Execute Agent Purchase"}
                <ArrowRight className="w-4 h-4" />
              </button>
            </form>
          </div>

          {/* Preset Attack Demonstrations */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">
              One-Click Pitch Demonstrations
            </p>
            <div className="space-y-2">
              <button
                onClick={() => {
                  setPrompt("Buy Dell Inspiron Laptop under ₹45,000");
                  setBudget(45000);
                }}
                className="w-full text-left text-xs bg-slate-950 hover:bg-slate-800/80 border border-slate-800 p-2.5 rounded-lg text-slate-300 transition-colors flex items-center justify-between"
              >
                <span>✅ <span className="font-semibold text-emerald-400">Legitimate Order:</span> Valid laptop checkout</span>
                <span className="text-[10px] text-slate-500 font-mono">ALLOW</span>
              </button>

              <button
                onClick={() => {
                  setPrompt("Buy developer laptop under ₹40,000");
                  setBudget(40000); // Intentionally lower than the ₹48k poisoned SKU to trigger budget + injection
                }}
                className="w-full text-left text-xs bg-slate-950 hover:bg-slate-800/80 border border-slate-800 p-2.5 rounded-lg text-slate-300 transition-colors flex items-center justify-between"
              >
                <span>⚡ <span className="font-semibold text-rose-400">Attack 1:</span> Injected Catalog Payload</span>
                <span className="text-[10px] text-slate-500 font-mono">BLOCK</span>
              </button>

              <button
                onClick={() => {
                  setPrompt("Find ergonomic desk chair around ₹8,000");
                  setBudget(8000);
                }}
                className="w-full text-left text-xs bg-slate-950 hover:bg-slate-800/80 border border-slate-800 p-2.5 rounded-lg text-slate-300 transition-colors flex items-center justify-between"
              >
                <span>⚠️ <span className="font-semibold text-amber-400">HITL Step-Up:</span> Minor price drift</span>
                <span className="text-[10px] text-slate-500 font-mono">CONSENT</span>
              </button>
            </div>
          </div>
        </div>

        {/* Right Column: Gateway Telemetry & Audit Stream */}
        <div className="lg:col-span-7 space-y-6">

          {/* Live LangGraph State Pipeline */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">
              LangGraph State Machine Pipeline
            </h3>
            <div className="grid grid-cols-4 gap-2 text-center text-xs">
              <div className={`p-2 rounded-lg border transition-all ${activeStep >= 1 ? "bg-indigo-950/60 border-indigo-600 text-indigo-300" : "bg-slate-950 border-slate-800 text-slate-500"
                }`}>
                <Search className="w-4 h-4 mx-auto mb-1" />
                <span>1. Catalog Scan</span>
              </div>
              <div className={`p-2 rounded-lg border transition-all ${activeStep >= 2 ? "bg-indigo-950/60 border-indigo-600 text-indigo-300" : "bg-slate-950 border-slate-800 text-slate-500"
                }`}>
                <Cpu className="w-4 h-4 mx-auto mb-1" />
                <span>2. Reasoning</span>
              </div>
              <div className={`p-2 rounded-lg border transition-all ${activeStep >= 3 ? "bg-indigo-950/60 border-indigo-600 text-indigo-300" : "bg-slate-950 border-slate-800 text-slate-500"
                }`}>
                <Lock className="w-4 h-4 mx-auto mb-1" />
                <span>3. Invariant Tier</span>
              </div>
              <div className={`p-2 rounded-lg border transition-all ${activeStep >= 4 ? "bg-emerald-950/60 border-emerald-600 text-emerald-300" : "bg-slate-950 border-slate-800 text-slate-500"
                }`}>
                <Check className="w-4 h-4 mx-auto mb-1" />
                <span>4. Gateway Ver</span>
              </div>
            </div>
          </div>

          {/* Decision Outcome Banner */}
          {executionResult && (
            <div className={`p-5 rounded-xl border transition-all ${executionResult.gateway_decision?.decision === "ALLOW"
              ? "bg-emerald-950/40 border-emerald-700/80 text-emerald-200"
              : executionResult.gateway_decision?.decision === "REQUIRE_HUMAN_APPROVAL"
                ? "bg-amber-950/40 border-amber-700/80 text-amber-200"
                : "bg-rose-950/40 border-rose-700/80 text-rose-200"
              }`}>
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-3">
                  {executionResult.gateway_decision?.decision === "ALLOW" ? (
                    <ShieldCheck className="w-7 h-7 text-emerald-400 mt-0.5" />
                  ) : executionResult.gateway_decision?.decision === "REQUIRE_HUMAN_APPROVAL" ? (
                    <AlertTriangle className="w-7 h-7 text-amber-400 mt-0.5" />
                  ) : (
                    <ShieldAlert className="w-7 h-7 text-rose-400 mt-0.5" />
                  )}
                  <div>
                    <h3 className="font-bold text-base tracking-tight">
                      Gateway Action: {executionResult.gateway_decision?.decision}
                    </h3>
                    <p className="text-xs mt-1 opacity-90 leading-relaxed">
                      {executionResult.gateway_decision?.reason}
                    </p>
                    {executionResult.gateway_decision?.order_details && (
                      <p className="text-[11px] font-mono mt-2 text-emerald-400 bg-emerald-950/60 px-2 py-1 rounded inline-block">
                        Razorpay Order ID: {executionResult.gateway_decision.order_details.id} (₹{executionResult.gateway_decision.order_details.amount / 100})
                      </p>
                    )}
                  </div>
                </div>
                <div className="text-right font-mono">
                  <span className="text-xs bg-black/40 px-2.5 py-1 rounded-md border border-white/10">
                    {executionResult.gateway_decision?.total_latency_ms?.toFixed(1)} ms
                  </span>
                </div>
              </div>

              {/* Step-Up Consent Action Dialog */}
              {escalationData && (
                <div className="mt-4 pt-4 border-t border-amber-800/60 flex items-center justify-between">
                  <span className="text-xs font-medium text-amber-300">
                    Grant Step-Up Authorization for this purchase?
                  </span>
                  <div className="flex space-x-2">
                    <button
                      onClick={() => handleResolveEscalation(false)}
                      disabled={resolvingEscalation}
                      className="px-3 py-1 bg-rose-900/60 hover:bg-rose-800 text-rose-200 text-xs rounded font-medium flex items-center gap-1"
                    >
                      <XCircle className="w-3.5 h-3.5" /> Reject
                    </button>
                    <button
                      onClick={() => handleResolveEscalation(true)}
                      disabled={resolvingEscalation}
                      className="px-3 py-1 bg-emerald-700 hover:bg-emerald-600 text-white text-xs rounded font-medium flex items-center gap-1 shadow"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" /> Approve Order
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Audit Ledger */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-2">
              <Terminal className="w-4 h-4 text-emerald-400" />
              Immutable Gateway Audit Trail
            </h2>
            <div className="overflow-x-auto max-h-[340px]">
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="border-b border-slate-800 text-slate-500 font-mono sticky top-0 bg-slate-900">
                  <tr>
                    <th className="pb-2">Trace ID</th>
                    <th className="pb-2">Decision</th>
                    <th className="pb-2">Violation / Note</th>
                    <th className="pb-2">Latency</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {auditLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-slate-800/30">
                      <td className="py-2.5 text-indigo-400">{log.trace_id}</td>
                      <td className="py-2.5">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${log.decision === "ALLOW"
                          ? "bg-emerald-900/60 text-emerald-300 border border-emerald-700"
                          : log.decision === "REQUIRE_HUMAN_APPROVAL"
                            ? "bg-amber-900/60 text-amber-300 border border-amber-700"
                            : "bg-rose-900/60 text-rose-300 border border-rose-700"
                          }`}>
                          {log.decision}
                        </span>
                      </td>
                      <td className="py-2.5 text-slate-400 truncate max-w-[220px]">
                        {log.violation_code || log.reason || "—"}
                      </td>
                      <td className="py-2.5 text-slate-400">{log.total_latency_ms?.toFixed(1)} ms</td>
                    </tr>
                  ))}
                  {auditLogs.length === 0 && (
                    <tr>
                      <td colSpan={4} className="py-4 text-center text-slate-500">
                        No audit events recorded yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

        </div>

      </main>
    </div>
  );
}