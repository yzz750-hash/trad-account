"use client";

import { useState, useEffect } from "react";
import { apiFetch, apiDownload, errMsg } from "@/lib/api";
import { useLedger } from "@/context/LedgerContext";
import { d, percent as pct } from "@/lib/decimal";

async function downloadExport(endpoint: string, filename: string) {
  try {
    const blob = await apiDownload(`/api/v1/export/${endpoint}`);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 100);
  } catch (e) {
    console.error("Export download failed:", e);
  }
}

type BalanceSheetItem = {
  item_name: string;
  amount: string;
};

type BalanceSheetData = {
  assets: BalanceSheetItem[];
  liabilities: BalanceSheetItem[];
  equity: BalanceSheetItem[];
  total_assets: string;
  total_liabilities: string;
  total_equity: string;
};

type IncomeStatementItem = {
  item_name: string;
  amount: string;
};

type IncomeStatementData = {
  revenues: IncomeStatementItem[];
  expenses: IncomeStatementItem[];
  total_revenue: string;
  total_expense: string;
  net_income: string;
};

type CashFlowItem = {
  item_name: string;
  amount: string;
};

type CashFlowData = {
  operating_inflows: CashFlowItem[];
  operating_outflows: CashFlowItem[];
  investing_inflows: CashFlowItem[];
  investing_outflows: CashFlowItem[];
  financing_inflows: CashFlowItem[];
  financing_outflows: CashFlowItem[];
  net_operating_cash_flow: string;
  net_investing_cash_flow: string;
  net_financing_cash_flow: string;
  net_increase_in_cash: string;
  ending_cash_balance: string;
};

export default function ReportsDashboard() {
  const { currentLedgerId, currentLedger } = useLedger();
  const [activeTab, setActiveTab] = useState<"balance" | "income" | "cash" | "oem" | "commission">("balance");

  const now = new Date();
  const todayStr = now.toISOString().slice(0, 10);
  const firstOfMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
  const lastOfMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).toISOString().slice(0, 10);

  const [asOfDate, setAsOfDate] = useState(lastOfMonth);
  const [startDate, setStartDate] = useState(firstOfMonth);
  const [endDate, setEndDate] = useState(todayStr);
  const currentYear = String(now.getFullYear());

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bsData, setBsData] = useState<BalanceSheetData | null>(null);
  const [isData, setIsData] = useState<IncomeStatementData | null>(null);
  const [cfData, setCfData] = useState<CashFlowData | null>(null);

  const [contractNumber, setContractNumber] = useState("");
  const [oemYear, setOemYear] = useState(currentYear);
  const [oemMonth, setOemMonth] = useState("");

  type OemEntry = {
    date: string;
    voucher_number: string;
    account_code: string;
    account_name: string;
    summary: string;
    direction: string;
    amount: string;
    category: string;
  };

  type OemData = {
    contract_number: string;
    revenue: string;
    cost: string;
    expenses: string;
    gross_profit: string;
    net_profit: string;
    entries: OemEntry[];
  };

  const [oemData, setOemData] = useState<OemData | null>(null);

  const [commissionYear, setCommissionYear] = useState("2026");
  const [commissionMonth, setCommissionMonth] = useState("");

  type CommissionContractItem = {
    contract_number: string;
    customer_name: string | null;
    revenue: string;
    cost: string;
    gross_profit: string;
    basis_amount: string;
    rate: string;
    commission_amount: string;
  };

  type CommissionSalespersonItem = {
    salesperson_id: number;
    salesperson_name: string;
    department: string | null;
    contracts: CommissionContractItem[];
    total_commission: string;
  };

  type CommissionData = {
    period: string;
    salespersons: CommissionSalespersonItem[];
    total_commission: string;
    contract_count: number;
  };

  const [commissionData, setCommissionData] = useState<CommissionData | null>(null);

  const formatMoney = (val: number | string) => {
    return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(Number(val));
  };

  const fetchBalanceSheet = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/v1/reports/balance-sheet?as_of_date=${asOfDate}`);
      setBsData(data);
    } catch (e: unknown) {
      setError(errMsg(e) || "资产负债表加载失败");
    }
    setLoading(false);
  };

  const fetchIncomeStatement = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/v1/reports/income-statement?start_date=${startDate}&end_date=${endDate}`);
      setIsData(data);
    } catch (e: unknown) {
      setError(errMsg(e) || "利润表加载失败");
    }
    setLoading(false);
  };

  const fetchCashFlow = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/v1/reports/cash-flow?start_date=${startDate}&end_date=${endDate}`);
      setCfData(data);
    } catch (e: unknown) {
      setError(errMsg(e) || "现金流量表加载失败");
    }
    setLoading(false);
  };

  const fetchOemContract = async () => {
    if (!contractNumber.trim()) {
      setError("请输入合同编号");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      let url = `/api/v1/reports/oem-contract/${encodeURIComponent(contractNumber.trim())}`;
      const params = new URLSearchParams();
      if (oemYear) params.set("year", oemYear);
      if (oemMonth) params.set("month", oemMonth);
      const qs = params.toString();
      if (qs) url += `?${qs}`;
      const data = await apiFetch(url);
      setOemData(data);
    } catch (e: unknown) {
      setError(errMsg(e) || "合同报表加载失败");
    }
    setLoading(false);
  };

  const fetchCommission = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (commissionYear) params.set("year", commissionYear);
      if (commissionMonth) params.set("month", commissionMonth);
      const data = await apiFetch(`/api/v1/reports/commission?${params.toString()}`);
      setCommissionData(data);
    } catch (e: unknown) {
      setError(errMsg(e) || "提成报表加载失败");
    }
    setLoading(false);
  };

  useEffect(() => {
    if (activeTab === "balance") {
      fetchBalanceSheet();
    } else if (activeTab === "income") {
      fetchIncomeStatement();
    } else if (activeTab === "cash") {
      fetchCashFlow();
    }
  }, [activeTab, asOfDate, startDate, endDate, currentLedgerId]);

  useEffect(() => {
    if (activeTab === "commission") {
      fetchCommission();
    }
  }, [activeTab, commissionYear, commissionMonth, currentLedgerId]);

  return (
    <div className="max-w-7xl mx-auto px-8 py-10 min-h-screen">
      <header className="mb-8 flex justify-between items-end print:hidden">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 mb-2">报表中心 (Financial Dashboard)</h1>
          <p className="text-slate-500">查看财务报表与实时业务指标</p>
          {currentLedger && (
            <p className="text-sm text-indigo-600 font-medium mt-1">{currentLedger.company_name || currentLedger.name}</p>
          )}
        </div>

        <div className="flex items-center gap-4">
          <button
            onClick={() => window.print()}
            className="bg-white border border-slate-200 text-slate-700 px-4 py-2 rounded-lg hover:bg-slate-50 transition-colors shadow-sm text-sm font-medium flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" /></svg>
            打印报表
          </button>
          <button
            onClick={() => {
              if (activeTab === "balance") {
                downloadExport(`balance-sheet?as_of_date=${asOfDate}`, `balance_sheet_${asOfDate}.xlsx`);
              } else if (activeTab === "income") {
                downloadExport(`income-statement?start_date=${startDate}&end_date=${endDate}`, `income_statement_${startDate}_${endDate}.xlsx`);
              } else if (activeTab === "cash") {
                downloadExport(`cash-flow?start_date=${startDate}&end_date=${endDate}`, `cash_flow_${startDate}_${endDate}.xlsx`);
              } else if (activeTab === "commission") {
                downloadExport(`commission?year=${commissionYear}${commissionMonth ? `&month=${commissionMonth}` : ''}`, `commission_${commissionYear}${commissionMonth ? `_${commissionMonth}` : ''}.xlsx`);
              }
            }}
            className={`px-4 py-2 rounded-lg transition-colors shadow-sm text-sm font-medium flex items-center gap-2 ${activeTab === "oem" ? "bg-slate-300 text-slate-500 cursor-not-allowed" : "bg-green-600 text-white hover:bg-green-700"}`}
            disabled={activeTab === "oem"}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
            导出 Excel
          </button>

          <div className="bg-slate-100 p-1 rounded-xl flex border border-slate-200">
            <button
              onClick={() => setActiveTab("balance")}
              className={`px-6 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === 'balance' ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}
            >
              资产负债表
            </button>
            <button
              onClick={() => setActiveTab("income")}
              className={`px-6 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === 'income' ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}
            >
              利润表
            </button>
            <button
              onClick={() => setActiveTab("cash")}
              className={`px-6 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === 'cash' ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}
            >
              现金流量表
            </button>
            <button
              onClick={() => setActiveTab("oem")}
              className={`px-6 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === 'oem' ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}
            >
              合同损益
            </button>
            <button
              onClick={() => setActiveTab("commission")}
              className={`px-6 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === 'commission' ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}
            >
              提成
            </button>
          </div>
        </div>
      </header>

      {/* Date Controls */}
      <div className="bg-white p-4 rounded-xl shadow-sm border border-slate-200 mb-8 flex gap-4 items-center print:hidden">
        <svg className="w-5 h-5 text-slate-400 ml-2" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>

        {activeTab === "commission" ? (
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm font-medium text-slate-600">年份</span>
            <input
              type="number"
              value={commissionYear}
              onChange={(e) => setCommissionYear(e.target.value)}
              placeholder="2026"
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 w-24"
            />
            <span className="text-sm font-medium text-slate-600">月份</span>
            <input
              type="number"
              value={commissionMonth}
              onChange={(e) => setCommissionMonth(e.target.value)}
              placeholder="全部"
              min="1"
              max="12"
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 w-20"
            />
            <button
              onClick={fetchCommission}
              className="bg-indigo-600 text-white px-6 py-1.5 rounded-lg hover:bg-indigo-700 transition-colors text-sm font-medium ml-2"
            >
              查询
            </button>
          </div>
        ) : activeTab === "oem" ? (
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm font-medium text-slate-600">合同号：</span>
            <input
              type="text"
              value={contractNumber}
              onChange={(e) => setContractNumber(e.target.value)}
              placeholder="如: OEM-2024-001"
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 w-48"
              onKeyDown={(e) => { if (e.key === "Enter") fetchOemContract(); }}
            />
            <span className="text-sm font-medium text-slate-600 ml-2">年份</span>
            <input
              type="number"
              value={oemYear}
              onChange={(e) => setOemYear(e.target.value)}
              placeholder="2026"
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 w-24"
            />
            <span className="text-sm font-medium text-slate-600">月份</span>
            <input
              type="number"
              value={oemMonth}
              onChange={(e) => setOemMonth(e.target.value)}
              placeholder="全部"
              min="1"
              max="12"
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 w-20"
            />
            <button
              onClick={fetchOemContract}
              className="bg-indigo-600 text-white px-6 py-1.5 rounded-lg hover:bg-indigo-700 transition-colors text-sm font-medium ml-2"
            >
              查询
            </button>
          </div>
        ) : activeTab === "balance" ? (
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-slate-600">截至日期：</span>
            <input
              type="date"
              value={asOfDate}
              onChange={(e) => setAsOfDate(e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            />
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-slate-600">统计期间：</span>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            />
            <span className="text-slate-400">-</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            />
          </div>
        )}
      </div>

      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 rounded-xl p-4 mb-6 text-sm">
          {error}
          <button onClick={() => {
            if (activeTab === "balance") fetchBalanceSheet();
            else if (activeTab === "income") fetchIncomeStatement();
            else if (activeTab === "cash") fetchCashFlow();
            else if (activeTab === "oem") fetchOemContract();
            else if (activeTab === "commission") fetchCommission();
          }} className="ml-3 underline font-medium hover:text-rose-800">重试</button>
        </div>
      )}
      {loading ? (
        <div className="flex justify-center items-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
        </div>
      ) : (
        <>
          {activeTab === "balance" && bsData && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div className="grid grid-cols-3 gap-6">
                <div className="bg-gradient-to-br from-indigo-500 to-indigo-600 p-6 rounded-xl shadow-lg text-white">
                  <div className="text-indigo-100 text-sm font-medium mb-1">总资产 (Assets)</div>
                  <div className="text-3xl font-bold font-mono tracking-tight">{formatMoney(bsData.total_assets)}</div>
                </div>
                <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200 relative overflow-hidden">
                  <div className="absolute top-0 right-0 w-24 h-24 bg-rose-50 rounded-full -mr-10 -mt-10"></div>
                  <div className="text-slate-500 text-sm font-medium mb-1 relative z-10">总负债 (Liabilities)</div>
                  <div className="text-3xl font-bold font-mono text-slate-800 tracking-tight relative z-10">{formatMoney(bsData.total_liabilities)}</div>
                </div>
                <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200 relative overflow-hidden">
                  <div className="absolute top-0 right-0 w-24 h-24 bg-emerald-50 rounded-full -mr-10 -mt-10"></div>
                  <div className="text-slate-500 text-sm font-medium mb-1 relative z-10">总权益 (Equity)</div>
                  <div className="text-3xl font-bold font-mono text-slate-800 tracking-tight relative z-10">{formatMoney(bsData.total_equity)}</div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-8">
                <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                  <h3 className="text-lg font-bold text-slate-800 mb-4 pb-4 border-b border-slate-100">资产明细</h3>
                  <div className="space-y-4">
                    {bsData.assets.map((item, idx) => {
                      const percentage = pct(item.amount, bsData.total_assets);
                      return (
                        <div key={idx} className="group">
                          <div className="flex justify-between text-sm mb-1.5">
                            <span className="text-slate-600 font-medium">{item.item_name}</span>
                            <span className="text-slate-900 font-mono">{formatMoney(item.amount)}</span>
                          </div>
                          <div className="h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-indigo-500 rounded-full transition-all duration-1000 ease-out group-hover:bg-indigo-600"
                              style={{ width: `${percentage}%` }}
                            ></div>
                          </div>
                        </div>
                      )
                    })}
                    {bsData.assets.length === 0 && <div className="text-slate-400 text-sm text-center py-4">暂无资产数据</div>}
                  </div>
                </div>

                <div className="space-y-8">
                  <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                    <h3 className="text-lg font-bold text-slate-800 mb-4 pb-4 border-b border-slate-100">负债明细</h3>
                    <div className="space-y-4">
                      {bsData.liabilities.map((item, idx) => {
                        const percentage = pct(item.amount, bsData.total_liabilities);
                        return (
                          <div key={idx} className="group">
                            <div className="flex justify-between text-sm mb-1.5">
                              <span className="text-slate-600 font-medium">{item.item_name}</span>
                              <span className="text-slate-900 font-mono">{formatMoney(item.amount)}</span>
                            </div>
                            <div className="h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-rose-400 rounded-full transition-all duration-1000 ease-out group-hover:bg-rose-500"
                                style={{ width: `${percentage}%` }}
                              ></div>
                            </div>
                          </div>
                        )
                      })}
                      {bsData.liabilities.length === 0 && <div className="text-slate-400 text-sm text-center py-4">暂无负债数据</div>}
                    </div>
                  </div>

                  <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                    <h3 className="text-lg font-bold text-slate-800 mb-4 pb-4 border-b border-slate-100">所有者权益明细</h3>
                    <div className="space-y-4">
                      {bsData.equity.map((item, idx) => {
                        const percentage = pct(item.amount, bsData.total_equity);
                        return (
                          <div key={idx} className="group">
                            <div className="flex justify-between text-sm mb-1.5">
                              <span className="text-slate-600 font-medium">{item.item_name}</span>
                              <span className="text-slate-900 font-mono">{formatMoney(item.amount)}</span>
                            </div>
                            <div className="h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-emerald-400 rounded-full transition-all duration-1000 ease-out group-hover:bg-emerald-500"
                                style={{ width: `${percentage}%` }}
                              ></div>
                            </div>
                          </div>
                        )
                      })}
                      {bsData.equity.length === 0 && <div className="text-slate-400 text-sm text-center py-4">暂无权益数据</div>}
                    </div>
                  </div>
                </div>
              </div>

              <div className={`p-4 rounded-xl border flex items-center justify-between text-sm font-medium ${d(bsData.total_assets).minus(d(bsData.total_liabilities)).minus(d(bsData.total_equity)).abs().lt(0.01) ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-rose-50 text-rose-700 border-rose-200'}`}>
                <div className="flex items-center gap-2">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                  会计等式：资产 ({formatMoney(bsData.total_assets)}) = 负债 ({formatMoney(bsData.total_liabilities)}) + 权益 ({formatMoney(bsData.total_equity)})
                </div>
                <div>
                  {d(bsData.total_assets).minus(d(bsData.total_liabilities)).minus(d(bsData.total_equity)).abs().lt(0.01) ? '试算平衡 ✓' : '试算不平衡'}
                </div>
              </div>
            </div>
          )}

          {activeTab === "income" && isData && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div className="grid grid-cols-3 gap-6">
                <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200 relative overflow-hidden">
                  <div className="absolute top-0 right-0 w-24 h-24 bg-blue-50 rounded-full -mr-10 -mt-10"></div>
                  <div className="text-slate-500 text-sm font-medium mb-1 relative z-10">总收入 (Total Revenue)</div>
                  <div className="text-3xl font-bold font-mono text-slate-800 tracking-tight relative z-10">{formatMoney(isData.total_revenue)}</div>
                </div>
                <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200 relative overflow-hidden">
                  <div className="absolute top-0 right-0 w-24 h-24 bg-orange-50 rounded-full -mr-10 -mt-10"></div>
                  <div className="text-slate-500 text-sm font-medium mb-1 relative z-10">总费用 (Total Expenses)</div>
                  <div className="text-3xl font-bold font-mono text-slate-800 tracking-tight relative z-10">{formatMoney(isData.total_expense)}</div>
                </div>
                <div className={`p-6 rounded-xl shadow-lg text-white ${Number(isData.net_income) >= 0 ? 'bg-gradient-to-br from-emerald-500 to-emerald-600' : 'bg-gradient-to-br from-rose-500 to-rose-600'}`}>
                  <div className="text-white/80 text-sm font-medium mb-1">净利润 (Net Income)</div>
                  <div className="text-3xl font-bold font-mono tracking-tight">{formatMoney(isData.net_income)}</div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-8">
                <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                  <h3 className="text-lg font-bold text-slate-800 mb-4 pb-4 border-b border-slate-100 flex items-center gap-2">
                    <span className="w-2 h-6 bg-blue-500 rounded-sm"></span>
                    收入构成
                  </h3>
                  <div className="space-y-5 mt-6">
                    {isData.revenues.map((item, idx) => {
                      const percentage = pct(item.amount, isData.total_revenue);
                      return (
                        <div key={idx} className="group">
                          <div className="flex justify-between items-end mb-2">
                            <span className="text-slate-700 font-medium">{item.item_name}</span>
                            <div className="text-right">
                              <div className="text-slate-900 font-mono font-medium">{formatMoney(item.amount)}</div>
                              <div className="text-xs text-slate-400 font-mono mt-0.5">{percentage.toFixed(1)}%</div>
                            </div>
                          </div>
                          <div className="h-2 w-full bg-slate-100 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-blue-500 rounded-full transition-all duration-1000 ease-out group-hover:bg-blue-600"
                              style={{ width: `${percentage}%` }}
                            ></div>
                          </div>
                        </div>
                      )
                    })}
                    {isData.revenues.length === 0 && <div className="text-slate-400 text-sm text-center py-4">暂无收入数据</div>}
                  </div>
                </div>

                <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                  <h3 className="text-lg font-bold text-slate-800 mb-4 pb-4 border-b border-slate-100 flex items-center gap-2">
                    <span className="w-2 h-6 bg-orange-400 rounded-sm"></span>
                    费用构成
                  </h3>
                  <div className="space-y-5 mt-6">
                    {isData.expenses.map((item, idx) => {
                      const percentage = pct(item.amount, isData.total_expense);
                      return (
                        <div key={idx} className="group">
                          <div className="flex justify-between items-end mb-2">
                            <span className="text-slate-700 font-medium">{item.item_name}</span>
                            <div className="text-right">
                              <div className="text-slate-900 font-mono font-medium">{formatMoney(item.amount)}</div>
                              <div className="text-xs text-slate-400 font-mono mt-0.5">{percentage.toFixed(1)}%</div>
                            </div>
                          </div>
                          <div className="h-2 w-full bg-slate-100 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-orange-400 rounded-full transition-all duration-1000 ease-out group-hover:bg-orange-500"
                              style={{ width: `${percentage}%` }}
                            ></div>
                          </div>
                        </div>
                      )
                    })}
                    {isData.expenses.length === 0 && <div className="text-slate-400 text-sm text-center py-4">暂无费用数据</div>}
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === "cash" && cfData && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <h2 className="text-2xl font-bold text-slate-900 hidden print:block mb-6 pb-2 border-b">现金流量表 (Cash Flow Statement)</h2>

              <div className="grid grid-cols-4 gap-6">
                <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                  <div className="text-slate-500 text-sm font-medium mb-1">经营性现金流</div>
                  <div className={`text-2xl font-bold font-mono tracking-tight ${d(cfData.net_operating_cash_flow).gte(0) ? 'text-emerald-600' : 'text-rose-600'}`}>{formatMoney(cfData.net_operating_cash_flow)}</div>
                </div>
                <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                  <div className="text-slate-500 text-sm font-medium mb-1">投资性现金流</div>
                  <div className={`text-2xl font-bold font-mono tracking-tight ${d(cfData.net_investing_cash_flow).gte(0) ? 'text-emerald-600' : 'text-rose-600'}`}>{formatMoney(cfData.net_investing_cash_flow)}</div>
                </div>
                <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                  <div className="text-slate-500 text-sm font-medium mb-1">融资性现金流</div>
                  <div className={`text-2xl font-bold font-mono tracking-tight ${d(cfData.net_financing_cash_flow).gte(0) ? 'text-emerald-600' : 'text-rose-600'}`}>{formatMoney(cfData.net_financing_cash_flow)}</div>
                </div>
                <div className="bg-gradient-to-br from-slate-800 to-slate-900 p-6 rounded-xl shadow-lg text-white">
                  <div className="text-slate-300 text-sm font-medium mb-1">期末现金余额</div>
                  <div className="text-2xl font-bold font-mono tracking-tight">{formatMoney(cfData.ending_cash_balance)}</div>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-6">
                <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                  <h3 className="text-lg font-bold text-slate-800 mb-4 pb-4 border-b border-slate-100 flex items-center gap-2">
                    <span className="w-2 h-6 bg-emerald-500 rounded-sm"></span>
                    经营活动 (Operating)
                  </h3>
                  <div className="space-y-4">
                    <div className="text-sm font-semibold text-emerald-600">现金流入 (Inflows)</div>
                    {cfData.operating_inflows.map((item, idx) => (
                      <div key={`oi-${idx}`} className="flex justify-between text-sm">
                        <span className="text-slate-600">{item.item_name}</span>
                        <span className="text-slate-900 font-mono">{formatMoney(item.amount)}</span>
                      </div>
                    ))}
                    {cfData.operating_inflows.length === 0 && <div className="text-xs text-slate-400">暂无数据</div>}

                    <div className="text-sm font-semibold text-rose-500 mt-4 pt-4 border-t border-slate-50">现金流出 (Outflows)</div>
                    {cfData.operating_outflows.map((item, idx) => (
                      <div key={`oo-${idx}`} className="flex justify-between text-sm">
                        <span className="text-slate-600">{item.item_name}</span>
                        <span className="text-slate-900 font-mono">{formatMoney(item.amount)}</span>
                      </div>
                    ))}
                    {cfData.operating_outflows.length === 0 && <div className="text-xs text-slate-400">暂无数据</div>}
                  </div>
                </div>

                <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                  <h3 className="text-lg font-bold text-slate-800 mb-4 pb-4 border-b border-slate-100 flex items-center gap-2">
                    <span className="w-2 h-6 bg-blue-500 rounded-sm"></span>
                    投资活动 (Investing)
                  </h3>
                  <div className="space-y-4">
                    <div className="text-sm font-semibold text-emerald-600">现金流入 (Inflows)</div>
                    {cfData.investing_inflows.map((item, idx) => (
                      <div key={`ii-${idx}`} className="flex justify-between text-sm">
                        <span className="text-slate-600">{item.item_name}</span>
                        <span className="text-slate-900 font-mono">{formatMoney(item.amount)}</span>
                      </div>
                    ))}
                    {cfData.investing_inflows.length === 0 && <div className="text-xs text-slate-400">暂无数据</div>}

                    <div className="text-sm font-semibold text-rose-500 mt-4 pt-4 border-t border-slate-50">现金流出 (Outflows)</div>
                    {cfData.investing_outflows.map((item, idx) => (
                      <div key={`io-${idx}`} className="flex justify-between text-sm">
                        <span className="text-slate-600">{item.item_name}</span>
                        <span className="text-slate-900 font-mono">{formatMoney(item.amount)}</span>
                      </div>
                    ))}
                    {cfData.investing_outflows.length === 0 && <div className="text-xs text-slate-400">暂无数据</div>}
                  </div>
                </div>

                <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                  <h3 className="text-lg font-bold text-slate-800 mb-4 pb-4 border-b border-slate-100 flex items-center gap-2">
                    <span className="w-2 h-6 bg-purple-500 rounded-sm"></span>
                    筹资活动 (Financing)
                  </h3>
                  <div className="space-y-4">
                    <div className="text-sm font-semibold text-emerald-600">现金流入 (Inflows)</div>
                    {cfData.financing_inflows.map((item, idx) => (
                      <div key={`fi-${idx}`} className="flex justify-between text-sm">
                        <span className="text-slate-600">{item.item_name}</span>
                        <span className="text-slate-900 font-mono">{formatMoney(item.amount)}</span>
                      </div>
                    ))}
                    {cfData.financing_inflows.length === 0 && <div className="text-xs text-slate-400">暂无数据</div>}

                    <div className="text-sm font-semibold text-rose-500 mt-4 pt-4 border-t border-slate-50">现金流出 (Outflows)</div>
                    {cfData.financing_outflows.map((item, idx) => (
                      <div key={`fo-${idx}`} className="flex justify-between text-sm">
                        <span className="text-slate-600">{item.item_name}</span>
                        <span className="text-slate-900 font-mono">{formatMoney(item.amount)}</span>
                      </div>
                    ))}
                    {cfData.financing_outflows.length === 0 && <div className="text-xs text-slate-400">暂无数据</div>}
                  </div>
                </div>
              </div>

              <div className={`p-4 rounded-xl border flex items-center justify-between text-sm font-medium ${d(cfData.net_increase_in_cash).gte(0) ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-rose-50 text-rose-700 border-rose-200'}`}>
                <div className="flex items-center gap-2">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                  本期现金净增加额：{formatMoney(cfData.net_increase_in_cash)}
                </div>
              </div>
            </div>
          )}

          {activeTab === "oem" && oemData && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div className="grid grid-cols-4 gap-6">
                <div className="bg-gradient-to-br from-blue-500 to-blue-600 p-6 rounded-xl shadow-lg text-white">
                  <div className="text-blue-100 text-sm font-medium mb-1">收入 (Revenue)</div>
                  <div className="text-3xl font-bold font-mono tracking-tight">{formatMoney(oemData.revenue)}</div>
                </div>
                <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200 relative overflow-hidden">
                  <div className="absolute top-0 right-0 w-24 h-24 bg-orange-50 rounded-full -mr-10 -mt-10"></div>
                  <div className="text-slate-500 text-sm font-medium mb-1 relative z-10">成本 (Cost)</div>
                  <div className="text-3xl font-bold font-mono text-slate-800 tracking-tight relative z-10">{formatMoney(oemData.cost)}</div>
                </div>
                <div className={`p-6 rounded-xl shadow-lg text-white ${d(oemData.gross_profit).gte(0) ? 'bg-gradient-to-br from-emerald-500 to-emerald-600' : 'bg-gradient-to-br from-rose-500 to-rose-600'}`}>
                  <div className="text-white/80 text-sm font-medium mb-1">毛利 (Gross Profit)</div>
                  <div className="text-3xl font-bold font-mono tracking-tight">{formatMoney(oemData.gross_profit)}</div>
                  <div className="text-sm text-white/70 mt-1 font-mono">
                    毛利率 {d(oemData.revenue).gt(0) ? pct(oemData.gross_profit, oemData.revenue).toFixed(1) : "0.0"}%
                  </div>
                </div>
                <div className={`p-6 rounded-xl shadow-lg text-white ${d(oemData.net_profit).gte(0) ? 'bg-gradient-to-br from-indigo-500 to-indigo-600' : 'bg-gradient-to-br from-rose-500 to-rose-600'}`}>
                  <div className="text-white/80 text-sm font-medium mb-1">净利润 (Net Profit)</div>
                  <div className="text-3xl font-bold font-mono tracking-tight">{formatMoney(oemData.net_profit)}</div>
                </div>
              </div>

              <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                <h3 className="text-lg font-bold text-slate-800 mb-4 pb-4 border-b border-slate-100 flex items-center gap-2">
                  <span className="w-2 h-6 bg-indigo-500 rounded-sm"></span>
                  凭证明细 (Entries)
                  <span className="ml-auto text-sm font-normal text-slate-400">
                    合同号: {oemData.contract_number}
                  </span>
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-100 text-left text-slate-500">
                        <th className="pb-3 font-medium">日期</th>
                        <th className="pb-3 font-medium">凭证号</th>
                        <th className="pb-3 font-medium">科目编码</th>
                        <th className="pb-3 font-medium">科目名称</th>
                        <th className="pb-3 font-medium">摘要</th>
                        <th className="pb-3 font-medium text-center">方向</th>
                        <th className="pb-3 font-medium text-right">金额</th>
                        <th className="pb-3 font-medium text-center">分类</th>
                      </tr>
                    </thead>
                    <tbody>
                      {oemData.entries.map((entry, idx) => {
                        const categoryLabel: Record<string, string> = {
                          revenue: "收入",
                          cost: "成本",
                          expenses: "费用",
                          other: "其他",
                        };
                        const categoryColor: Record<string, string> = {
                          revenue: "bg-blue-100 text-blue-700",
                          cost: "bg-orange-100 text-orange-700",
                          expenses: "bg-rose-100 text-rose-700",
                          other: "bg-slate-100 text-slate-500",
                        };
                        return (
                          <tr key={idx} className="border-b border-slate-50 hover:bg-slate-50/50 transition-colors">
                            <td className="py-3 text-slate-700">{entry.date}</td>
                            <td className="py-3 text-slate-800 font-medium">{entry.voucher_number}</td>
                            <td className="py-3 text-slate-500 font-mono text-xs">{entry.account_code}</td>
                            <td className="py-3 text-slate-700">{entry.account_name}</td>
                            <td className="py-3 text-slate-500 max-w-[200px] truncate" title={entry.summary}>{entry.summary}</td>
                            <td className="py-3 text-center">
                              <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${entry.direction === "DEBIT" ? "bg-slate-100 text-slate-700" : "bg-slate-100 text-slate-500"}`}>
                                {entry.direction === "DEBIT" ? "借" : "贷"}
                              </span>
                            </td>
                            <td className="py-3 text-right font-mono text-slate-800">{formatMoney(entry.amount)}</td>
                            <td className="py-3 text-center">
                              <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${categoryColor[entry.category] || categoryColor.other}`}>
                                {categoryLabel[entry.category] || entry.category}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {oemData.entries.length === 0 && (
                    <div className="text-slate-400 text-sm text-center py-8">暂无凭证明细</div>
                  )}
                </div>
              </div>

              <div className={`p-4 rounded-xl border flex items-center justify-between text-sm font-medium ${d(oemData.net_profit).gte(0) ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-rose-50 text-rose-700 border-rose-200'}`}>
                <div className="flex items-center gap-2">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
                  利润构成：收入 {formatMoney(oemData.revenue)} - 成本 {formatMoney(oemData.cost)} - 费用 {formatMoney(oemData.expenses)} = 净利润 {formatMoney(oemData.net_profit)}
                </div>
                <div className="font-mono">
                  净利率 {d(oemData.revenue).gt(0) ? pct(oemData.net_profit, oemData.revenue).toFixed(2) : "0.00"}%
                </div>
              </div>
            </div>
          )}

          {activeTab === "commission" && commissionData && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div className="grid grid-cols-4 gap-6">
                <div className="bg-gradient-to-br from-violet-500 to-violet-600 p-6 rounded-xl shadow-lg text-white">
                  <div className="text-violet-100 text-sm font-medium mb-1">业务员人数</div>
                  <div className="text-3xl font-bold font-mono tracking-tight">{commissionData.salespersons.length}</div>
                </div>
                <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                  <div className="text-slate-500 text-sm font-medium mb-1">合同数量</div>
                  <div className="text-3xl font-bold font-mono text-slate-800 tracking-tight">{commissionData.contract_count}</div>
                </div>
                <div className="bg-gradient-to-br from-emerald-500 to-emerald-600 p-6 rounded-xl shadow-lg text-white col-span-2">
                  <div className="text-emerald-100 text-sm font-medium mb-1">总提成金额</div>
                  <div className="text-3xl font-bold font-mono tracking-tight">{formatMoney(commissionData.total_commission)}</div>
                </div>
              </div>

              {commissionData.salespersons.map((sp) => (
                <div key={sp.salesperson_id} className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                  <h3 className="text-lg font-bold text-slate-800 mb-4 pb-4 border-b border-slate-100 flex items-center gap-2">
                    <span className="w-2 h-6 bg-violet-500 rounded-sm"></span>
                    {sp.salesperson_name}
                    {sp.department && <span className="text-sm font-normal text-slate-400 ml-2">({sp.department})</span>}
                    <span className="ml-auto text-sm font-normal text-violet-600 font-mono">
                      总提成: {formatMoney(sp.total_commission)}
                    </span>
                  </h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-slate-100 text-left text-slate-500">
                          <th className="pb-3 font-medium">合同号</th>
                          <th className="pb-3 font-medium">客户名称</th>
                          <th className="pb-3 font-medium text-right">收入</th>
                          <th className="pb-3 font-medium text-right">成本</th>
                          <th className="pb-3 font-medium text-right">毛利</th>
                          <th className="pb-3 font-medium text-right">提成基数</th>
                          <th className="pb-3 font-medium text-center">提成率</th>
                          <th className="pb-3 font-medium text-right">提成金额</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sp.contracts.map((ct, idx) => (
                          <tr key={idx} className="border-b border-slate-50 hover:bg-slate-50/50 transition-colors">
                            <td className="py-3 text-slate-800 font-medium">{ct.contract_number}</td>
                            <td className="py-3 text-slate-500">{ct.customer_name || "-"}</td>
                            <td className="py-3 text-right font-mono text-slate-700">{formatMoney(ct.revenue)}</td>
                            <td className="py-3 text-right font-mono text-slate-700">{formatMoney(ct.cost)}</td>
                            <td className="py-3 text-right font-mono text-slate-800 font-medium">{formatMoney(ct.gross_profit)}</td>
                            <td className="py-3 text-right font-mono text-slate-700">{formatMoney(ct.basis_amount)}</td>
                            <td className="py-3 text-center">
                              <span className="inline-block px-2 py-0.5 rounded text-xs bg-violet-100 text-violet-700 font-mono">
                                {d(ct.rate).times(100).toFixed(2)}%
                              </span>
                            </td>
                            <td className="py-3 text-right font-mono text-violet-700 font-bold">{formatMoney(ct.commission_amount)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {sp.contracts.length === 0 && (
                      <div className="text-slate-400 text-sm text-center py-4">暂无合同数据</div>
                    )}
                  </div>
                </div>
              ))}

              {commissionData.salespersons.length === 0 && (
                <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-12 text-center">
                  <svg className="w-12 h-12 mx-auto mb-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <p className="text-slate-500 text-sm">暂无提成数据</p>
                  <p className="text-slate-400 text-xs mt-1">请先添加业务员并匹配有效合同</p>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
