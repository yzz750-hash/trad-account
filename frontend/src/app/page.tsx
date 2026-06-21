"use client";

import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";
import { useLedger } from "@/context/LedgerContext";
import Link from "next/link"
import { KpiCardSkeleton, ChartSkeleton, Skeleton } from "@/components/Skeleton";

interface DashboardSummary {
  monthly_revenue: number;
  monthly_revenue_trend: number;
  pending_prepayments: number;
  pending_prepayment_count: number;
  unmatched_bank_txns: number;
  pending_tasks: { type: string; title: string; description: string }[];
}

const taskColors: Record<string, string> = {
  prepayment: "bg-orange-400",
  bank_txn: "bg-blue-400",
  oem_commission: "bg-purple-400",
};

export default function Home() {
  const { currentLedgerId, currentLedger } = useLedger();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!currentLedgerId) return;
    setLoading(true);
    setError(null);
    apiFetch<DashboardSummary>("/api/v1/reports/dashboard-summary")
      .then((data) => { setSummary(data); setError(null); })
      .catch((err) => { setError(err.message || "加载仪表盘数据失败，请重试"); console.error(err); })
      .finally(() => setLoading(false));
  }, [currentLedgerId]);

  const formatMoney = (val: number | string) =>
    new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(Number(val));

  return (
    <main className="min-h-screen">
      <div className="max-w-7xl mx-auto px-8 py-10">
        <header className="mb-10">
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 mb-2">财务仪表盘</h1>
          <p className="text-slate-500">欢迎使用智能外贸财务系统，实时掌握公司财务状况与待处理业务。</p>
          {currentLedger && (
            <p className="text-sm text-indigo-600 font-medium mt-1">{currentLedger.company_name || currentLedger.name}</p>
          )}
        </header>

        {error && (
          <div className="bg-rose-50 border border-rose-200 text-rose-700 rounded-xl p-4 mb-6 text-sm">
            {error}
            <button onClick={() => { setError(null); setLoading(true); apiFetch<DashboardSummary>("/api/v1/reports/dashboard-summary").then(setSummary).catch(() => setError("加载失败，请重试")).finally(() => setLoading(false)); }} className="ml-3 underline font-medium hover:text-rose-800">重试</button>
          </div>
        )}
        {loading ? (
          <>
            <div className="grid grid-cols-3 gap-6 mb-10">
              <KpiCardSkeleton />
              <KpiCardSkeleton />
              <KpiCardSkeleton />
            </div>
            <div className="grid grid-cols-3 gap-6">
              <div className="col-span-2">
                <ChartSkeleton />
              </div>
              <div className="col-span-1 bg-white rounded-xl p-6 shadow-card border border-slate-100">
                <Skeleton className="h-5 w-24 mb-4" />
                <div className="space-y-3">
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                </div>
              </div>
            </div>
          </>
        ) : (
          <>
            {/* KPI Cards */}
            <div className="grid grid-cols-3 gap-6 mb-10">
              <div className="bg-white p-6 rounded-xl shadow-card border border-slate-100">
                <div className="text-sm font-medium text-slate-500 mb-2">本月销售收入 (CNY)</div>
                <div className="text-3xl font-bold tracking-tight mb-2">
                  {summary ? formatMoney(summary.monthly_revenue) : "¥0.00"}
                </div>
                <div className={`text-xs font-medium inline-block px-2 py-1 rounded-md ${
                  (summary?.monthly_revenue_trend ?? 0) >= 0
                    ? "text-emerald-600 bg-emerald-50"
                    : "text-rose-600 bg-rose-50"
                }`}>
                  {summary ? `${summary.monthly_revenue_trend >= 0 ? "+" : ""}${summary.monthly_revenue_trend}%` : "—"}
                </div>
              </div>
              <div className="bg-white p-6 rounded-xl shadow-card border border-slate-100">
                <div className="text-sm font-medium text-slate-500 mb-2">待核销预付款余额 (CNY)</div>
                <div className="text-3xl font-bold tracking-tight mb-2">
                  {summary ? formatMoney(summary.pending_prepayments) : "¥0.00"}
                </div>
                <div className="text-xs font-medium text-amber-600 bg-amber-50 inline-block px-2 py-1 rounded-md">
                  {summary ? `${summary.pending_prepayment_count} 笔待核销` : "—"}
                </div>
              </div>
              <div className="bg-white p-6 rounded-xl shadow-card border border-slate-100">
                <div className="text-sm font-medium text-slate-500 mb-2">未匹配银行流水 (笔)</div>
                <div className="text-3xl font-bold tracking-tight mb-2">
                  {summary ? `${summary.unmatched_bank_txns} 笔` : "—"}
                </div>
                <div className="text-xs font-medium text-indigo-600 bg-indigo-50 inline-block px-2 py-1 rounded-md">
                  AI 智能匹配待处理
                </div>
              </div>
            </div>

            {/* Content Area */}
            <div className="grid grid-cols-3 gap-6">
              <div className="col-span-2 bg-white rounded-xl p-6 shadow-card border border-slate-100 h-96 flex flex-col items-center justify-center">
                <svg className="w-16 h-16 text-slate-200 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
                </svg>
                <div className="text-slate-400 text-sm mb-2">财务报表图表即将上线，敬请期待</div>
                <Link href="/reports" className="text-indigo-600 text-sm font-medium hover:text-indigo-800 transition-colors">
                  前往报表中心 →
                </Link>
              </div>
              <div className="col-span-1 bg-white rounded-xl p-6 shadow-card border border-slate-100">
                <h3 className="font-semibold mb-4">待处理任务</h3>
                {summary && summary.pending_tasks.length > 0 ? (
                  <ul className="space-y-4">
                    {summary.pending_tasks.map((task, i) => (
                      <li key={i} className="flex gap-3 text-sm">
                        <div className={`w-2 h-2 rounded-full mt-1.5 ${taskColors[task.type] || "bg-slate-400"}`}></div>
                        <div>
                          <div className="font-medium">{task.title}</div>
                          <div className="text-slate-500 text-xs mt-0.5">{task.description}</div>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-slate-400 text-sm py-4 text-center">暂无待处理任务</div>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
