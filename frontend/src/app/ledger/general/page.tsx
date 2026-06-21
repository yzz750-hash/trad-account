"use client";

import { useState, useEffect } from "react";
import { apiFetch, errMsg } from "@/lib/api";
import { useLedger } from "@/context/LedgerContext";

interface GeneralLedgerRow {
  account_code: string;
  account_name: string;
  month: string;
  debit_sum: string;
  credit_sum: string;
  balance: string;
}

export default function GeneralLedgerPage() {
  const { currentLedger } = useLedger();
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);
  const [month, setMonth] = useState("");
  const [search, setSearch] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [rows, setRows] = useState<GeneralLedgerRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [totalRows, setTotalRows] = useState(0);
  const [triggerFetch, setTriggerFetch] = useState(0);
  const pageSize = 200;

  const fetchGeneralLedger = async (fetchAll = false) => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("year", String(year));
      if (month) params.set("month", month);
      if (search) params.set("search", search);
      if (minAmount) params.set("min_amount", minAmount);
      if (maxAmount) params.set("max_amount", maxAmount);
      params.set("page", String(page));
      params.set("page_size", String(pageSize));

      const data = await apiFetch<GeneralLedgerRow[]>(
        `/api/v1/reports/general-ledger?${params.toString()}`
      );
      setRows(data);
      // Approximate total: if we got a full page, there may be more
      if (fetchAll) {
        setTotalRows(data.length);
      } else {
        setTotalRows(data.length === pageSize ? page * pageSize + 1 : page * pageSize - pageSize + data.length);
      }
    } catch (err: unknown) {
      setError(errMsg(err) || "查询失败");
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchGeneralLedger();
  }, [page, triggerFetch]);

  const handleSearch = () => {
    setPage(1);
    setTriggerFetch(t => t + 1);
  };

  const exportToCSV = async () => {
    if (rows.length === 0) return;
    setLoading(true);
    try {
      const allRows: GeneralLedgerRow[] = [...rows];
      let p = 2;
      const fetchPageSize = 500;
      while (true) {
        const params = new URLSearchParams();
        params.set("year", String(year));
        if (month) params.set("month", month);
        if (search) params.set("search", search);
        if (minAmount) params.set("min_amount", minAmount);
        if (maxAmount) params.set("max_amount", maxAmount);
        params.set("page", String(p));
        params.set("page_size", String(fetchPageSize));
        const data = await apiFetch<GeneralLedgerRow[]>(
          `/api/v1/reports/general-ledger?${params.toString()}`
        );
        if (data.length === 0) break;
        allRows.push(...data);
        if (data.length < fetchPageSize) break;
        p++;
      }

      const BOM = "﻿";
      const headers = ["科目代码", "科目名称", "月份", "借方合计", "贷方合计", "余额"];
      const csvContent = [
        headers.join(","),
        ...allRows.map((r) =>
          [r.account_code, `"${r.account_name}"`, r.month, r.debit_sum, r.credit_sum, r.balance].join(",")
        ),
      ].join("\n");

      const blob = new Blob([BOM + csvContent], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `总账_${year}${month ? "_" + month + "月" : ""}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      setError("导出失败: " + (errMsg(err) || ""));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-8 py-10 min-h-screen">
      <header className="mb-10">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900 mb-2">总分类账</h1>
        <p className="text-slate-500">按科目查看月度发生额与余额汇总。</p>
        {currentLedger && (
          <p className="text-sm text-indigo-600 font-medium mt-1">{currentLedger.company_name || currentLedger.name}</p>
        )}
      </header>

      {/* Filter Bar */}
      <div className="bg-white p-4 rounded-xl shadow-sm border border-slate-200 mb-8 flex flex-wrap gap-4 items-end">
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-slate-600">年份</label>
          <input
            type="number"
            value={year}
            onChange={(e) => setYear(parseInt(e.target.value) || currentYear)}
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 w-28"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-slate-600">月份</label>
          <select
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          >
            <option value="">全年</option>
            {Array.from({ length: 12 }, (_, i) => (
              <option key={i + 1} value={String(i + 1)}>{i + 1}月</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5 w-48">
          <label className="text-sm font-medium text-slate-600">关键词</label>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="科目代码 / 名称..."
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            onKeyDown={(e) => { if (e.key === 'Enter') handleSearch(); }}
          />
        </div>
        <div className="flex flex-col gap-1.5 w-28">
          <label className="text-sm font-medium text-slate-600">最低金额</label>
          <input
            type="number"
            value={minAmount}
            onChange={(e) => setMinAmount(e.target.value)}
            placeholder="0.00"
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          />
        </div>
        <div className="flex flex-col gap-1.5 w-28">
          <label className="text-sm font-medium text-slate-600">最高金额</label>
          <input
            type="number"
            value={maxAmount}
            onChange={(e) => setMaxAmount(e.target.value)}
            placeholder="0.00"
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          />
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleSearch}
            className="bg-slate-900 text-white px-6 py-2 rounded-lg hover:bg-slate-800 transition-colors shadow-sm text-sm font-medium h-[38px]"
          >
            查询
          </button>
          <button
            onClick={exportToCSV}
            disabled={rows.length === 0}
            className={`px-4 py-2 rounded-lg border text-sm font-medium transition-colors shadow-sm h-[38px] flex items-center gap-2 ${rows.length > 0 ? 'bg-white border-slate-300 text-slate-700 hover:bg-slate-50' : 'bg-slate-50 border-slate-200 text-slate-400 cursor-not-allowed'}`}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
            导出 CSV
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm">
          {error}
          <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-red-600">&times;</button>
        </div>
      )}

      {loading ? (
        <div className="text-slate-500">加载中...</div>
      ) : (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-sm text-slate-500">
                <th className="py-4 px-6 font-medium">科目代码</th>
                <th className="py-4 px-6 font-medium">科目名称</th>
                <th className="py-4 px-6 font-medium">月份</th>
                <th className="py-4 px-6 font-medium text-right">借方合计</th>
                <th className="py-4 px-6 font-medium text-right">贷方合计</th>
                <th className="py-4 px-6 font-medium text-right">余额</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {rows.map((r, i) => (
                <tr key={`${r.account_code}-${r.month}-${i}`} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-4 px-6 font-mono text-slate-600">{r.account_code}</td>
                  <td className="py-4 px-6 font-medium text-slate-900">{r.account_name}</td>
                  <td className="py-4 px-6 text-slate-600">{r.month}</td>
                  <td className="py-4 px-6 text-right font-mono text-slate-700">{Number(r.debit_sum).toFixed(2)}</td>
                  <td className="py-4 px-6 text-right font-mono text-slate-700">{Number(r.credit_sum).toFixed(2)}</td>
                  <td className="py-4 px-6 text-right font-mono font-medium text-slate-800">{Number(r.balance).toFixed(2)}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-slate-500">暂无总账数据</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {!loading && totalRows > pageSize && (
        <div className="flex justify-between items-center mt-4 text-sm text-slate-600">
          <div>第 {page} 页</div>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(page - 1)}
              disabled={page <= 1}
              className={`px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors ${page <= 1 ? 'bg-slate-50 border-slate-200 text-slate-400 cursor-not-allowed' : 'bg-white border-slate-300 text-slate-700 hover:bg-slate-50'}`}
            >
              上一页
            </button>
            <button
              onClick={() => setPage(page + 1)}
              disabled={rows.length < pageSize}
              className={`px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors ${rows.length < pageSize ? 'bg-slate-50 border-slate-200 text-slate-400 cursor-not-allowed' : 'bg-white border-slate-300 text-slate-700 hover:bg-slate-50'}`}
            >
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
