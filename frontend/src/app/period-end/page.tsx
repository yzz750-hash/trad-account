"use client";

import { useState, useEffect } from "react";
import { apiFetch, errMsg } from "@/lib/api";
import { useLedger } from "@/context/LedgerContext";

export default function PeriodEndPage() {
  const { currentLedgerId, currentLedger } = useLedger();
  const [year, setYear] = useState<number>(new Date().getFullYear());
  const [month, setMonth] = useState<number>(new Date().getMonth() + 1);
  const [periodStatus, setPeriodStatus] = useState<string>("OPEN");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{type: "success" | "error", text: string} | null>(null);

  const fetchPeriodStatus = async () => {
    try {
      const data = await apiFetch("/api/v1/system/periods/current");
      if (data && data.year === year && data.month === month) {
        setPeriodStatus(data.status);
      } else {
        setPeriodStatus("OPEN");
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchPeriodStatus();
  }, [year, month, currentLedgerId]);

  const handleAction = async (endpoint: string) => {
    setLoading(true);
    setMessage(null);
    try {
      const data = await apiFetch(`/api/v1/closing/${endpoint}?year=${year}&month=${month}`, {
        method: "POST"
      });
      setMessage({ type: "success", text: data.message });
      if (endpoint === "close" || endpoint === "unclose") {
        setPeriodStatus(endpoint === "close" ? "CLOSED" : "OPEN");
      }
    } catch (err: unknown) {
      setMessage({ type: "error", text: errMsg(err) || "操作失败" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="flex justify-between items-end mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">期末结转与关账</h1>
          <p className="text-slate-500 mt-1">按月执行计提折旧、外币重估、损益结转，完成后可关闭账期锁定凭证。</p>
          {currentLedger && (
            <p className="text-sm text-indigo-600 font-medium mt-1">{currentLedger.company_name || currentLedger.name}</p>
          )}
        </div>
        <div className="flex gap-4">
          <select value={year} onChange={e => setYear(parseInt(e.target.value))} className="border border-slate-300 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-slate-900">
            {[2023, 2024, 2025, 2026].map(y => <option key={y} value={y}>{y}年</option>)}
          </select>
          <select value={month} onChange={e => setMonth(parseInt(e.target.value))} className="border border-slate-300 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-slate-900">
            {Array.from({length: 12}, (_, i) => i + 1).map(m => <option key={m} value={m}>{m}月</option>)}
          </select>
        </div>
      </div>

      {message && (
        <div className={`p-4 mb-6 rounded-lg border ${message.type === 'success' ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-red-50 border-red-200 text-red-800'}`}>
          {message.text}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div>
            <div className="w-10 h-10 bg-blue-100 text-blue-600 rounded-lg flex items-center justify-center mb-4 font-bold text-lg">1</div>
            <h3 className="text-lg font-bold text-slate-900">计提折旧</h3>
            <p className="text-slate-500 text-sm mt-2">按固定资产分类自动计算当月折旧额，生成折旧凭证。</p>
          </div>
          <button
            disabled={loading || periodStatus === "CLOSED"}
            onClick={() => handleAction("depreciate")}
            className="mt-6 w-full py-2 bg-white border border-slate-300 text-slate-700 font-medium rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50"
          >
            执行折旧计提
          </button>
        </div>

        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div>
            <div className="w-10 h-10 bg-indigo-100 text-indigo-600 rounded-lg flex items-center justify-center mb-4 font-bold text-lg">2</div>
            <h3 className="text-lg font-bold text-slate-900">外币重估</h3>
            <p className="text-slate-500 text-sm mt-2">按期末汇率重新评估外币资产/负债余额，生成汇兑损益凭证。</p>
          </div>
          <button
            disabled={loading || periodStatus === "CLOSED"}
            onClick={() => handleAction("fx-revaluation")}
            className="mt-6 w-full py-2 bg-white border border-slate-300 text-slate-700 font-medium rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50"
          >
            执行期末重估
          </button>
        </div>

        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div>
            <div className="w-10 h-10 bg-purple-100 text-purple-600 rounded-lg flex items-center justify-center mb-4 font-bold text-lg">3</div>
            <h3 className="text-lg font-bold text-slate-900">损益结转</h3>
            <p className="text-slate-500 text-sm mt-2">将所有收入/费用科目余额结转至本年利润，清零当期损益类科目。</p>
          </div>
          <button
            disabled={loading || periodStatus === "CLOSED"}
            onClick={() => handleAction("profit-loss")}
            className="mt-6 w-full py-2 bg-white border border-slate-300 text-slate-700 font-medium rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50"
          >
            执行损益结转
          </button>
        </div>

        <div className={`p-6 rounded-xl border flex flex-col justify-between ${periodStatus === 'CLOSED' ? 'bg-amber-50 border-amber-200' : 'bg-slate-50 border-slate-200'}`}>
          <div>
            <div className="w-10 h-10 bg-slate-200 text-slate-600 rounded-lg flex items-center justify-center mb-4 font-bold text-lg">{periodStatus === 'CLOSED' ? '🔒' : '🔓'}</div>
            <h3 className="text-lg font-bold text-slate-900">期末关账</h3>
            <p className="text-slate-500 text-sm mt-2">
              当前状态: <span className={`font-bold ${periodStatus === 'CLOSED' ? 'text-amber-700' : 'text-emerald-600'}`}>{periodStatus === 'CLOSED' ? '已关账' : '未关账'}</span><br/>
              关账后将禁止新增和修改凭证，请确认所有操作已完成。如需修改请先执行反关账。
            </p>
          </div>
          <div className="flex gap-4 mt-6">
            {periodStatus === 'OPEN' ? (
              <button
                disabled={loading}
                onClick={() => handleAction("close")}
                className="flex-1 py-2 bg-accent text-white font-medium rounded-lg hover:bg-accent-light transition-colors disabled:opacity-50"
              >
                执行期末关账
              </button>
            ) : (
              <button
                disabled={loading}
                onClick={() => handleAction("unclose")}
                className="flex-1 py-2 bg-amber-100 text-amber-800 font-medium rounded-lg hover:bg-amber-200 transition-colors disabled:opacity-50"
              >
                反关账(重新打开)
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
