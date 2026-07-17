"use client";

import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";
import { useLedger } from "@/context/LedgerContext";
import { d } from "@/lib/decimal";
import type { AccountInfo } from "@/lib/types";
import AccountSelect from "@/components/AccountSelect";

interface SubsidiaryEntry {
  date: string; voucher_number: string; summary: string;
  debit_amount: number | null; credit_amount: number | null;
  balance_direction: string; balance: number;
}

export default function SubsidiaryLedger() {
  const { currentLedger } = useLedger();
  const [accountCode, setAccountCode] = useState("1403");
  const [startDate, setStartDate] = useState("2026-06-01");
  const [endDate, setEndDate] = useState("2026-06-30");
  const [search, setSearch] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [entries, setEntries] = useState<SubsidiaryEntry[]>([]);
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchAccounts = async () => {
    try {
      const data = await apiFetch<AccountInfo[]>('/api/v1/accounts');
      setAccounts(data);
    } catch {
      // accounts fetch is non-critical
    }
  };

  useEffect(() => { fetchAccounts(); }, []);

  // Template Print Settings
  const [isTemplatePrint, setIsTemplatePrint] = useState(false);
  const [templateRowHeight, setTemplateRowHeight] = useState(10); // mm
  const [templateMarginTop, setTemplateMarginTop] = useState(20); // mm
  const [templateMarginLeft, setTemplateMarginLeft] = useState(15); // mm

  const fetchLedger = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ account_code: accountCode, start_date: startDate, end_date: endDate });
      if (search) params.set("search", search);
      if (minAmount) params.set("min_amount", minAmount);
      if (maxAmount) params.set("max_amount", maxAmount);
      const data = await apiFetch<SubsidiaryEntry[]>(`/api/v1/reports/subsidiary-ledger?${params.toString()}`);
      setEntries(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "查询失败");
      setEntries([]);
    } finally {
      setLoading(false);
    }
  };

  const exportToCSV = async () => {
    if (!entries.length) return;

    setLoading(true);
    try {
      // Fetch ALL pages to get complete data (not just current page)
      const allEntries: SubsidiaryEntry[] = [...entries];
      const pageSize = 500;
      let page = 2;
      while (true) {
        const data = await apiFetch<SubsidiaryEntry[]>(
          `/api/v1/reports/subsidiary-ledger?account_code=${accountCode}&start_date=${startDate}&end_date=${endDate}&page=${page}&page_size=${pageSize}`
        );
        if (!data || data.length === 0) break;
        allEntries.push(...data);
        if (data.length < pageSize) break;
        page++;
      }

      const headers = ["日期", "凭证字号", "摘要", "借方金额", "贷方金额", "方向", "余额"];
      const rows = allEntries.map(e => [
      e.date,
      e.voucher_number || "",
      e.summary,
      e.debit_amount !== null && e.debit_amount !== undefined ? d(e.debit_amount).toFixed(2) : "",
      e.credit_amount !== null && e.credit_amount !== undefined ? d(e.credit_amount).toFixed(2) : "",
      e.balance_direction,
      d(e.balance).toFixed(2)
    ]);
    
    const csvEscape = (val: string) => {
      if (val.includes(",") || val.includes('"') || val.includes("\n")) {
        return '"' + val.replace(/"/g, '""') + '"';
      }
      return val;
    };
    const csvContent = "\uFEFF"
      + headers.map(csvEscape).join(",") + "\n"
      + rows.map(r => r.map(csvEscape).join(",")).join("\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `明细账_${accountCode}_${startDate}_${endDate}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => URL.revokeObjectURL(url), 100);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "CSV导出失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
  }, []); // Initial load

  const handleFxRevaluation = async () => {
    try {
      const year = parseInt(startDate.substring(0, 4)) || new Date().getFullYear();
      const month = parseInt(startDate.substring(5, 7)) || new Date().getMonth() + 1;
      const data = await apiFetch<{ status: string; message: string }>(`/api/v1/closing/fx-revaluation?year=${year}&month=${month}`, { method: "POST" });
      alert(data.message);
      if (data.status === "success") fetchLedger();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "期末调汇失败");
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-8 py-10 min-h-screen">
      <header className="mb-10">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900 mb-2">明细分类账</h1>
        <p className="text-slate-500">按会计科目查询明细流水与实时余额。</p>
        {currentLedger && (
          <p className="text-sm text-indigo-600 font-medium mt-1">{currentLedger.company_name || currentLedger.name}</p>
        )}
      </header>

      {/* Filter Bar — Row 1: Filters */}
      <div className="bg-white p-4 rounded-xl shadow-sm border border-slate-200 mb-4 flex gap-4 items-end">
        <div className="flex flex-col gap-1.5 min-w-[200px] flex-[2]">
          <label className="text-sm font-medium text-slate-600">科目代码</label>
          <AccountSelect
            accounts={accounts}
            value={accountCode}
            onChange={(val) => setAccountCode(val)}
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 w-full"
            placeholder="选择或输入科目代码"
          />
        </div>
        <div className="flex flex-col gap-1.5 w-36">
          <label className="text-sm font-medium text-slate-600">开始日期</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          />
        </div>
        <div className="flex flex-col gap-1.5 w-36">
          <label className="text-sm font-medium text-slate-600">结束日期</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          />
        </div>
        <div className="flex flex-col gap-1.5 flex-1 min-w-[120px]">
          <label className="text-sm font-medium text-slate-600">关键词</label>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="凭证字号 / 摘要..."
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            onKeyDown={(e) => { if (e.key === 'Enter') fetchLedger(); }}
          />
        </div>
        <div className="flex flex-col gap-1.5 w-24">
          <label className="text-sm font-medium text-slate-600">最低金额</label>
          <input
            type="number"
            value={minAmount}
            onChange={(e) => setMinAmount(e.target.value)}
            placeholder="0.00"
            className="border border-slate-200 rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          />
        </div>
        <div className="flex flex-col gap-1.5 w-24">
          <label className="text-sm font-medium text-slate-600">最高金额</label>
          <input
            type="number"
            value={maxAmount}
            onChange={(e) => setMaxAmount(e.target.value)}
            placeholder="0.00"
            className="border border-slate-200 rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          />
        </div>
        <button
          onClick={fetchLedger}
          className="bg-slate-900 text-white px-6 py-2 rounded-lg hover:bg-slate-800 transition-colors shadow-sm text-sm font-medium shrink-0 h-[38px]"
        >
          查询
        </button>
      </div>

      {/* Filter Bar — Row 2: Actions */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-2">
          <button
            onClick={handleFxRevaluation}
            className="bg-purple-600 text-white px-4 py-2 rounded-lg hover:bg-purple-700 transition-colors shadow-sm text-sm font-medium inline-flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            期末自动调汇
          </button>
          <button
            onClick={exportToCSV}
            disabled={entries.length === 0}
            className={`px-4 py-2 rounded-lg border text-sm font-medium transition-colors shadow-sm inline-flex items-center gap-2 ${entries.length > 0 ? 'bg-white border-slate-300 text-slate-700 hover:bg-slate-50' : 'bg-slate-50 border-slate-200 text-slate-400 cursor-not-allowed'}`}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
            导出 CSV
          </button>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex bg-slate-100 rounded-lg p-1">
            <button
              onClick={() => setIsTemplatePrint(false)}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${!isTemplatePrint ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}
            >
              普通打印
            </button>
            <button
              onClick={() => setIsTemplatePrint(true)}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${isTemplatePrint ? 'bg-white shadow-sm text-indigo-600' : 'text-slate-500 hover:text-slate-700'}`}
            >
              启用套打
            </button>
          </div>
          <button
            onClick={() => window.print()}
            disabled={entries.length === 0}
            className={`px-4 py-2 rounded-lg border text-sm font-medium transition-colors shadow-sm inline-flex items-center gap-2 ${entries.length > 0 ? (isTemplatePrint ? 'bg-indigo-600 border-indigo-600 text-white hover:bg-indigo-700' : 'bg-white border-slate-300 text-slate-700 hover:bg-slate-50') : 'bg-slate-50 border-slate-200 text-slate-400 cursor-not-allowed'}`}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" /></svg>
            {isTemplatePrint ? '执行套打' : '打印排版'}
          </button>
        </div>
      </div>

      {isTemplatePrint && (
        <div className="bg-indigo-50 border border-indigo-100 p-4 rounded-xl mb-6 flex gap-6 items-center print:hidden">
          <div className="text-sm font-medium text-indigo-800 flex items-center gap-2">
            <svg className="w-5 h-5 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
            套打微调参数 (mm)
          </div>
          <div className="flex gap-4">
            <div className="flex items-center gap-2">
              <label className="text-xs text-slate-600">上边距:</label>
              <input type="number" value={templateMarginTop} onChange={e => setTemplateMarginTop(Number(e.target.value))} className="w-16 border border-slate-300 rounded px-2 py-1 text-xs" />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-slate-600">左边距:</label>
              <input type="number" value={templateMarginLeft} onChange={e => setTemplateMarginLeft(Number(e.target.value))} className="w-16 border border-slate-300 rounded px-2 py-1 text-xs" />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-slate-600">行高:</label>
              <input type="number" value={templateRowHeight} onChange={e => setTemplateRowHeight(Number(e.target.value))} className="w-16 border border-slate-300 rounded px-2 py-1 text-xs" />
            </div>
          </div>
          <div className="text-xs text-indigo-600 flex-1 text-right">
            提示：套打模式下打印将隐藏所有边框、表头与无关背景。
          </div>
        </div>
      )}

      {isTemplatePrint && (
        <style dangerouslySetInnerHTML={{__html: `
          @media print {
            body * { visibility: hidden; }
            .template-print-area, .template-print-area * { visibility: visible; }
            .template-print-area {
              position: absolute;
              left: ${templateMarginLeft}mm;
              top: ${templateMarginTop}mm;
              width: 100%;
            }
            /* Hide non-data elements */
            .template-print-area thead { display: none; }
            /* Remove background and borders */
            .template-print-area, .template-print-area table, .template-print-area tr, .template-print-area td {
              background: transparent !important;
              border: none !important;
              box-shadow: none !important;
            }
            .template-print-area td {
              height: ${templateRowHeight}mm;
              padding: 0 !important;
              vertical-align: bottom;
              font-family: 'SimSun', 'Songti SC', serif;
              font-size: 12px;
            }
          }
        `}} />
      )}

      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 rounded-xl p-4 mb-6 text-sm">
          {error}
          <button onClick={fetchLedger} className="ml-3 underline font-medium hover:text-rose-800">重试</button>
        </div>
      )}
      {loading ? (
        <div className="text-slate-500 text-sm">数据加载中...</div>
      ) : (
        <div className={`bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden template-print-area ${isTemplatePrint ? 'print:border-none print:shadow-none' : ''}`}>
          <table className="w-full text-left border-collapse table-fixed">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-sm print:text-xs text-slate-500">
                <th className="py-3 px-4 print:py-1 print:px-2 font-medium w-24">日期</th>
                <th className="py-3 px-4 print:py-1 print:px-2 font-medium w-32">凭证字号</th>
                <th className="py-3 px-4 print:py-1 print:px-2 font-medium">摘要</th>
                <th className="py-3 px-4 print:py-1 print:px-2 font-medium text-right w-28">借方金额</th>
                <th className="py-3 px-4 print:py-1 print:px-2 font-medium text-right w-28">贷方金额</th>
                <th className="py-3 px-4 print:py-1 print:px-2 font-medium text-center w-16">方向</th>
                <th className="py-3 px-4 print:py-1 print:px-2 font-medium text-right w-32">余额</th>
              </tr>
            </thead>
            <tbody className="text-sm print:text-xs">
              {entries.map((e, idx) => (
                <tr key={idx} className="border-b border-slate-100 hover:bg-slate-50 transition-colors">
                  <td className="py-2 px-4 print:py-1 print:px-2 text-slate-600">{e.date}</td>
                  <td className="py-2 px-4 print:py-1 print:px-2 font-medium text-indigo-600 break-words">{e.voucher_number || "-"}</td>
                  <td className="py-2 px-4 print:py-1 print:px-2 text-slate-700 break-words whitespace-normal">{e.summary}</td>
                  <td className="py-2 px-4 print:py-1 print:px-2 text-right font-mono text-slate-700">{d(e.debit_amount).gt(0) ? d(e.debit_amount).toFixed(2) : ""}</td>
                  <td className="py-2 px-4 print:py-1 print:px-2 text-right font-mono text-slate-700">{d(e.credit_amount).gt(0) ? d(e.credit_amount).toFixed(2) : ""}</td>
                  <td className="py-2 px-4 print:py-1 print:px-2 text-center text-slate-500">{e.balance_direction}</td>
                  <td className="py-2 px-4 print:py-1 print:px-2 text-right font-mono font-medium text-slate-900">{d(e.balance).toFixed(2)}</td>
                </tr>
              ))}
              {entries.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-500">
                    该期间内无流水记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
