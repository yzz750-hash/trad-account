"use client";

import { useState, useEffect } from "react";
import { apiFetch, errMsg } from "@/lib/api";
import { useLedger } from "@/context/LedgerContext";
import { d, sum } from "@/lib/decimal";

interface BalanceRow {
  account_id: number;
  account_code: string;
  account_name: string;
  balance_direction: string;
  opening_debit: string;
  opening_credit: string;
  period_debit: string;
  period_credit: string;
  ending_debit: string;
  ending_credit: string;
}

export default function AccountBalancePage() {
  const { currentLedger } = useLedger();
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);
  const [month, setMonth] = useState("");
  const [rows, setRows] = useState<BalanceRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchBalances = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("year", String(year));
      if (month) params.set("month", month);
      params.set("level", "1");
      const data = await apiFetch<BalanceRow[]>(
        `/api/v1/reports/account-balances?${params.toString()}`
      );
      setRows(data);
    } catch (err: unknown) {
      setError(errMsg(err) || "查询失败");
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBalances();
  }, [year, month]);

  // Compute totals
  const totalOpenDebit = sum(rows.map(r => r.opening_debit || "0"));
  const totalOpenCredit = sum(rows.map(r => r.opening_credit || "0"));
  const totalPeriodDebit = sum(rows.map(r => r.period_debit || "0"));
  const totalPeriodCredit = sum(rows.map(r => r.period_credit || "0"));
  const totalEndDebit = sum(rows.map(r => r.ending_debit || "0"));
  const totalEndCredit = sum(rows.map(r => r.ending_credit || "0"));

  const exportCSV = () => {
    const BOM = "﻿";
    const headers = ["科目编码", "科目名称", "方向", "期初借方", "期初贷方", "本期借方", "本期贷方", "期末借方", "期末贷方"];
    const csv = [
      headers.join(","),
      ...rows.map((r) =>
        [r.account_code, `"${r.account_name}"`, r.balance_direction, r.opening_debit, r.opening_credit, r.period_debit, r.period_credit, r.ending_debit, r.ending_credit].join(",")
      ),
    ].join("\n");
    const blob = new Blob([BOM + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `科目余额表_${year}${month ? "_" + month + "月" : ""}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <style dangerouslySetInnerHTML={{__html: `
        @page { size: A4 landscape; margin: 12mm; }
        @media print {
          body { font-family: 'SimSun', 'Songti SC', serif; font-size: 12px; color: #000 !important; }
          .print-header { display: flex !important; }
          table { border-color: #000 !important; }
          thead { background: #f5f5f5 !important; -webkit-print-color-adjust: exact; }
          tfoot { background: #f5f5f5 !important; -webkit-print-color-adjust: exact; border-color: #000 !important; }
          td, th { color: #000 !important; }
        }
      `}} />

      {/* Print-only header */}
      <div className="hidden print-header print:flex justify-between items-center mb-4 pb-2 border-b-2 border-black">
        <div className="text-lg font-bold">科目余额表</div>
        <div className="text-sm">
          <span>核算单位：{currentLedger?.company_name || currentLedger?.name || ""}</span>
          <span className="ml-8">年度：{year}{month ? ` / ${month}月` : " / 全年"}</span>
        </div>
      </div>

      <div className="print:hidden flex justify-between items-center mb-6">
        <h1 className="text-xl font-bold text-slate-800">科目余额表</h1>
        <div className="flex gap-3">
          <button
            onClick={exportCSV}
            disabled={rows.length === 0}
            className="px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors disabled:opacity-50"
          >
            导出 CSV
          </button>
          <button
            onClick={() => window.print()}
            disabled={rows.length === 0}
            className="px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors disabled:opacity-50 flex items-center gap-1"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" /></svg>
            打印
          </button>
        </div>
      </div>

      <div className="print:hidden flex flex-wrap gap-4 mb-6">
        <div>
          <label className="block text-xs font-medium text-slate-500 mb-1">年度</label>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))} className="border border-slate-300 rounded-lg px-3 py-2 text-sm">
            {Array.from({ length: 10 }, (_, i) => currentYear - 5 + i).map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500 mb-1">月份</label>
          <select value={month} onChange={(e) => setMonth(e.target.value)} className="border border-slate-300 rounded-lg px-3 py-2 text-sm">
            <option value="">全年</option>
            {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
              <option key={m} value={m}>{m}月</option>
            ))}
          </select>
        </div>
        <div className="flex items-end">
          <button onClick={fetchBalances} className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors">查询</button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm">{error}</div>
      )}

      {loading ? (
        <div className="text-slate-500 text-center py-12">加载中...</div>
      ) : (
        <div className="bg-white rounded-xl shadow-card border border-slate-100 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-500">
                <tr>
                  <th className="py-3 px-4 font-medium text-left">科目编码</th>
                  <th className="py-3 px-4 font-medium text-left">科目名称</th>
                  <th className="py-3 px-4 font-medium text-center">方向</th>
                  <th className="py-3 px-4 font-medium text-right" colSpan={2}>期初余额</th>
                  <th className="py-3 px-4 font-medium text-right" colSpan={2}>本期发生额</th>
                  <th className="py-3 px-4 font-medium text-right" colSpan={2}>期末余额</th>
                </tr>
                <tr className="bg-slate-50 border-b border-slate-200 text-slate-400 text-xs">
                  <th colSpan={3}></th>
                  <th className="py-1 px-4 font-medium text-right">借方</th>
                  <th className="py-1 px-4 font-medium text-right">贷方</th>
                  <th className="py-1 px-4 font-medium text-right">借方</th>
                  <th className="py-1 px-4 font-medium text-right">贷方</th>
                  <th className="py-1 px-4 font-medium text-right">借方</th>
                  <th className="py-1 px-4 font-medium text-right">贷方</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-12 text-center text-slate-400">
                      {currentLedger ? "暂无数据，请先过账凭证并结账" : "请选择账套"}
                    </td>
                  </tr>
                ) : (
                  rows.map((r) => (
                    <tr key={r.account_id} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="py-2 px-4 font-mono text-slate-600">{r.account_code}</td>
                      <td className="py-2 px-4 text-slate-700">{r.account_name}</td>
                      <td className={`py-2 px-4 text-center text-xs font-medium ${r.balance_direction === "借" ? "text-indigo-600" : "text-orange-600"}`}>{r.balance_direction}</td>
                      <td className="py-2 px-4 text-right font-mono text-slate-600">{r.opening_debit !== "0" ? d(r.opening_debit).toFixed(2) : ""}</td>
                      <td className="py-2 px-4 text-right font-mono text-slate-600">{r.opening_credit !== "0" ? d(r.opening_credit).toFixed(2) : ""}</td>
                      <td className="py-2 px-4 text-right font-mono text-slate-600">{r.period_debit !== "0" ? d(r.period_debit).toFixed(2) : ""}</td>
                      <td className="py-2 px-4 text-right font-mono text-slate-600">{r.period_credit !== "0" ? d(r.period_credit).toFixed(2) : ""}</td>
                      <td className="py-2 px-4 text-right font-mono font-medium text-slate-700">{r.ending_debit !== "0" ? d(r.ending_debit).toFixed(2) : ""}</td>
                      <td className="py-2 px-4 text-right font-mono font-medium text-slate-700">{r.ending_credit !== "0" ? d(r.ending_credit).toFixed(2) : ""}</td>
                    </tr>
                  ))
                )}
              </tbody>
              {rows.length > 0 && (
                <tfoot className="bg-slate-50 border-t-2 border-slate-300 text-sm font-bold text-slate-700">
                  <tr>
                    <td colSpan={3} className="py-3 px-4 text-right">合计</td>
                    <td className="py-3 px-4 text-right font-mono">{d(totalOpenDebit).gt(0) ? totalOpenDebit : ""}</td>
                    <td className="py-3 px-4 text-right font-mono">{d(totalOpenCredit).gt(0) ? totalOpenCredit : ""}</td>
                    <td className="py-3 px-4 text-right font-mono">{d(totalPeriodDebit).gt(0) ? totalPeriodDebit : ""}</td>
                    <td className="py-3 px-4 text-right font-mono">{d(totalPeriodCredit).gt(0) ? totalPeriodCredit : ""}</td>
                    <td className="py-3 px-4 text-right font-mono">{d(totalEndDebit).gt(0) ? totalEndDebit : ""}</td>
                    <td className="py-3 px-4 text-right font-mono">{d(totalEndCredit).gt(0) ? totalEndCredit : ""}</td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
