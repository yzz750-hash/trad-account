"use client";

import React, { useEffect, useState } from "react";
import { useLedger } from "@/context/LedgerContext";
import { apiFetch } from "@/lib/api";
import { d, mul, sum } from "@/lib/decimal";
import type { Voucher, VoucherEntry, VoucherEntryDraft, AccountInfo } from "@/lib/types";
import VoucherFilterBar from "@/components/voucher/VoucherFilterBar";
import VoucherRow from "@/components/voucher/VoucherRow";
import VoucherRowDetail from "@/components/voucher/VoucherRowDetail";
import BatchToolbar from "@/components/voucher/BatchToolbar";
import BatchPrintTemplate from "@/components/voucher/BatchPrintTemplate";
import { TableRowSkeleton } from "@/components/Skeleton";
import CreateVoucherModal from "@/components/voucher/CreateVoucherModal";

interface Partner { id: number; name: string; type: string; }
interface Currency { id: number; code: string; name: string; }

export default function VoucherList() {
  const { currentLedgerId, currentLedger } = useLedger();
  const [vouchers, setVouchers] = useState<Voucher[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editEntries, setEditEntries] = useState<VoucherEntry[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showInvoiceId, setShowInvoiceId] = useState<number | null>(null);
  const [createDate, setCreateDate] = useState("");
  const [createEntries, setCreateEntries] = useState<VoucherEntryDraft[]>([
    { account_code: "", summary: "", direction: "借", amount: "", partner_id: "", currency_code: "CNY", original_amount: "" },
    { account_code: "", summary: "", direction: "借", amount: "", partner_id: "", currency_code: "CNY", original_amount: "" },
  ]);
  const [partners, setPartners] = useState<Partner[]>([]);
  const [currencies, setCurrencies] = useState<Currency[]>([]);
  const [rates, setRates] = useState<Record<string, number>>({});
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [isBatchPrinting, setIsBatchPrinting] = useState(false);
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Filter & pagination state
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterStartDate, setFilterStartDate] = useState("");
  const [filterEndDate, setFilterEndDate] = useState("");
  const [filterMinAmount, setFilterMinAmount] = useState("");
  const [filterMaxAmount, setFilterMaxAmount] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [triggerFetch, setTriggerFetch] = useState(0);
  const pageSize = 100;

  const authHeaders = () => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (currentLedgerId) h["X-Ledger-Id"] = currentLedgerId.toString();
    return h;
  };

  const fetchVouchers = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      if (filterStatus) params.set("status", filterStatus);
      if (filterStartDate) params.set("start_date", filterStartDate);
      if (filterEndDate) params.set("end_date", filterEndDate);
      if (filterMinAmount) params.set("min_amount", filterMinAmount);
      if (filterMaxAmount) params.set("max_amount", filterMaxAmount);
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      const qs = params.toString();
      const data = await apiFetch<{ items: Voucher[]; total: number; page: number; page_size: number }>(
        `/api/v1/vouchers/${qs ? "?" + qs : ""}`
      );
      setVouchers(data.items);
      setTotal(data.total);
    } catch (err) {
      setError("加载凭证列表失败: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  // useEffect drives fetch whenever page, ledger, or triggerFetch changes
  useEffect(() => {
    fetchVouchers();
  }, [page, currentLedgerId, triggerFetch]);

  const fetchPartnersAndCurrencies = async () => {
    try {
      const [pRes, cRes] = await Promise.all([
        apiFetch<Partner[]>("/api/v1/partners"),
        apiFetch<Currency[]>("/api/v1/system/currencies"),
      ]);
      setPartners(pRes);
      setCurrencies(cRes);
    } catch {
      // partners/currencies fetch is non-critical
    }
  };

  const fetchExchangeRates = async () => {
    try {
      const now = new Date();
      const r = await apiFetch<Array<{ currency_code: string; rate: number }>>(`/api/v1/system/rates?year=${now.getFullYear()}&month=${now.getMonth() + 1}`);
      const rateMap: Record<string, number> = {};
      r.forEach((item) => { rateMap[item.currency_code] = item.rate; });
      setRates(rateMap);
    } catch {
      // rates not critical for UI
    }
  };

  const fetchAccounts = async () => {
    try {
      const data = await apiFetch<AccountInfo[]>('/api/v1/accounts');
      setAccounts(data);
    } catch {
      // accounts fetch is non-critical
    }
  };

  useEffect(() => {
    fetchPartnersAndCurrencies();
    fetchExchangeRates();
    fetchAccounts();
  }, [currentLedgerId]);

  // --- Selection ---
  const toggleSelectAll = () => {
    if (selectedIds.size === vouchers.length && vouchers.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(vouchers.map((v) => v.id)));
    }
  };

  const makeToggleSelect = (id: number) => () => {
    const newSet = new Set(selectedIds);
    if (newSet.has(id)) newSet.delete(id);
    else newSet.add(id);
    setSelectedIds(newSet);
  };

  // --- Voucher CRUD ---
  const startEditing = (v: Voucher) => {
    setEditingId(v.id);
    setEditEntries(JSON.parse(JSON.stringify(v.entries)));
  };

  const cancelEditing = () => {
    setEditingId(null);
    setEditEntries([]);
  };

  const updateEntry = (index: number, field: string, value: string | number) => {
    const newEntries = [...editEntries];
    if (field === "account_code") {
      newEntries[index].account = { ...newEntries[index].account, code: value as string };
    } else {
      (newEntries[index] as unknown as Record<string, unknown>)[field] = value;
    }
    setEditEntries(newEntries);
  };

  const saveEditing = async (id: number) => {
    setLoading(true);
    try {
      const payload = {
        entries: editEntries.map((e) => {
          const code = e.account?.code;
          if (!code) {
            throw new Error("请至少填写一条分录明细");
          }
          return {
            account_code: code,
            summary: e.summary,
            direction: e.direction,
            amount: e.amount,
            currency_code: e.currency_code || "CNY",
          };
        }),
      };
      await apiFetch(`/api/v1/vouchers/${id}`, {
        method: "PUT",
        headers: authHeaders(),
        body: JSON.stringify(payload),
      });
      setTriggerFetch(t => t + 1);
      setEditingId(null);
    } catch (err) {
      setError("保存凭证失败: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  const postVoucher = async (id: number) => {
    setLoading(true);
    try {
      await apiFetch(`/api/v1/vouchers/${id}/post`, { method: "POST" });
      setTriggerFetch(t => t + 1);
    } catch (err) {
      setError("审核失败: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  const unpostVoucher = async (id: number) => {
    setLoading(true);
    try {
      await apiFetch(`/api/v1/vouchers/${id}/unpost`, { method: "POST" });
      setTriggerFetch(t => t + 1);
    } catch (err) {
      setError("反审核失败: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  const handleBatchReview = async () => {
    if (selectedIds.size === 0) return;
    setLoading(true);
    try {
      const data = await apiFetch<{ reviewed_count: number; failed_count: number; errors: { id: number; voucher_number: string; reason: string }[] }>(
        `/api/v1/vouchers/batch-review`,
        { method: "POST", body: JSON.stringify({ voucher_ids: [...selectedIds] }) }
      );
      setTriggerFetch(t => t + 1);
      setSelectedIds(new Set());
      if (data.errors.length > 0) {
        const errList = data.errors.map(e => `${e.voucher_number || e.id}: ${e.reason}`).join("\n");
        setError(`批量审核完成。成功 ${data.reviewed_count} 条，失败 ${data.failed_count} 条：${errList}`);
      } else {
        alert(`批量审核完成。成功 ${data.reviewed_count} 条`);
      }
    } catch (err) {
      setError("批量审核失败: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  const handleBatchUnpost = async () => {
    if (selectedIds.size === 0) return;
    setLoading(true);
    try {
      const data = await apiFetch<{ unposted_count: number; failed_count: number; errors: { id: number; voucher_number: string; reason: string }[] }>(
        `/api/v1/vouchers/batch-unpost`,
        { method: "POST", body: JSON.stringify({ voucher_ids: [...selectedIds] }) }
      );
      setTriggerFetch(t => t + 1);
      setSelectedIds(new Set());
      if (data.errors.length > 0) {
        const errList = data.errors.map(e => `${e.voucher_number || e.id}: ${e.reason}`).join("\n");
        setError(`批量反过账完成。成功 ${data.unposted_count} 条，失败 ${data.failed_count} 条：${errList}`);
      } else {
        alert(`批量反过账完成。成功 ${data.unposted_count} 条`);
      }
    } catch (err) {
      setError("批量反过账失败: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  const handleBatchPrint = () => {
    setIsBatchPrinting(true);
    setTimeout(() => {
      window.print();
      setIsBatchPrinting(false);
    }, 100);
  };

  const deleteVoucher = async (id: number) => {
    if (!confirm("确定要删除该凭证吗？此操作不可撤销。")) return;
    setLoading(true);
    try {
      await apiFetch(`/api/v1/vouchers/${id}`, { method: "DELETE" });
      setTriggerFetch(t => t + 1);
    } catch (err) {
      setError("删除凭证失败: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  const reverseVoucher = async (id: number) => {
    setLoading(true);
    try {
      await apiFetch(`/api/v1/vouchers/${id}/reverse`, { method: "POST" });
      setTriggerFetch(t => t + 1);
    } catch (err) {
      setError("冲销失败: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  // --- Create modal handlers ---
  const handleAddEntry = () => {
    setCreateEntries([...createEntries, { account_code: "", summary: "", direction: "借", amount: "", partner_id: "", currency_code: "CNY", original_amount: "" }]);
  };

  const handleCreateUpdateEntry = (index: number, field: string, value: string) => {
    const newEntries = [...createEntries];
    (newEntries[index] as unknown as Record<string, unknown>)[field] = value;

    const e = newEntries[index];
    if (field === "currency_code" && value !== "CNY" && !e.exchange_rate) {
      e.exchange_rate = String(rates[value] || 1.0);
    }
    if ((field === "original_amount" || field === "exchange_rate" || field === "currency_code") && e.currency_code !== "CNY") {
      const orig = d(e.original_amount || "0");
      const rate = d(e.exchange_rate || "1");
      if (orig.gt(0)) {
        e.amount = orig.times(rate).toFixed(2);
      }
    }
    setCreateEntries(newEntries);
  };

  const handleDeleteEntry = (index: number) => {
    setCreateEntries(createEntries.filter((_, i) => i !== index));
  };

  const handleCreateVoucher = async () => {
    const debit = sum(createEntries.filter((e) => e.direction === "借").map((e) => e.amount));
    const credit = sum(createEntries.filter((e) => e.direction === "贷").map((e) => e.amount));
    if (!d(debit).eq(d(credit)) || d(debit).eq(0)) return;

    setLoading(true);
    try {
      const payload = {
        voucher_date: createDate || new Date().toISOString().split("T")[0],
        voucher_number: "AUTO",
        attachments_count: 0,
        entries: createEntries.map((e) => ({
          account_code: e.account_code,
          summary: e.summary,
          direction: e.direction,
          amount: e.amount,
          currency_code: e.currency_code || "CNY",
          original_amount: e.original_amount || null,
          exchange_rate: e.exchange_rate || "1.0",
          partner_id: e.partner_id ? parseInt(e.partner_id) : null,
        })),
      };

      await apiFetch("/api/v1/vouchers", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      setShowCreateModal(false);
      setCreateEntries([
        { account_code: "", summary: "", direction: "借", amount: "", partner_id: "", currency_code: "CNY", original_amount: "" },
        { account_code: "", summary: "", direction: "借", amount: "", partner_id: "", currency_code: "CNY", original_amount: "" },
      ]);
      setTriggerFetch(t => t + 1);
    } catch (err) {
      setError("创建凭证失败: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  const handleClosing = async () => {
    setLoading(true);
    try {
      const today = new Date();
      await apiFetch(`/api/v1/closing/profit-loss?year=${today.getFullYear()}&month=${today.getMonth() + 1}`, { method: "POST" });
      setTriggerFetch(t => t + 1);
    } catch (err) {
      setError("期末结转失败: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  // --- Filter handlers ---
  const handleSearch = () => {
    setPage(1);
    setTriggerFetch(t => t + 1);
  };

  const handleReset = () => {
    setSearch("");
    setFilterStatus("");
    setFilterStartDate("");
    setFilterEndDate("");
    setFilterMinAmount("");
    setFilterMaxAmount("");
    setPage(1);
    setTriggerFetch(t => t + 1);
  };

  const handleToggleInvoice = (id: number | null) => {
    setShowInvoiceId(showInvoiceId === id ? null : id);
  };

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="max-w-7xl mx-auto px-8 py-10 min-h-screen">
      <header className="mb-10 flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 mb-2">凭证管理</h1>
          <p className="text-slate-500">管理所有记账凭证，支持手工录入、批量导入与智能生成。</p>
          {currentLedger && (
            <p className="text-sm text-indigo-600 font-medium mt-1">{currentLedger.company_name || currentLedger.name}</p>
          )}
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleClosing}
            className="bg-white border border-slate-300 text-slate-700 px-4 py-2 rounded-lg hover:bg-slate-50 transition-colors shadow-sm text-sm font-medium flex items-center gap-2"
          >
            <svg className="w-4 h-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
            期末结转          </button>
          <button
            onClick={() => setShowCreateModal(true)}
            className="bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700 transition-colors shadow-sm text-sm font-medium flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" /></svg>
            新增凭证          </button>
        </div>
      </header>

      {error && (
        <div role="alert" className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm">
          {error}
          <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-red-600">&times;</button>
        </div>
      )}

      <VoucherFilterBar
        search={search} onSearchChange={setSearch}
        filterStartDate={filterStartDate} onFilterStartDateChange={setFilterStartDate}
        filterEndDate={filterEndDate} onFilterEndDateChange={setFilterEndDate}
        filterMinAmount={filterMinAmount} onFilterMinAmountChange={setFilterMinAmount}
        filterMaxAmount={filterMaxAmount} onFilterMaxAmountChange={setFilterMaxAmount}
        filterStatus={filterStatus} onFilterStatusChange={setFilterStatus}
        onSearch={handleSearch}
        onReset={handleReset}
      />

      {loading ? (
          <div className="bg-white rounded-xl shadow-card border border-slate-200 overflow-hidden"><table className="w-full text-left border-collapse"><thead><tr className="bg-slate-50 border-b border-slate-200 text-sm text-slate-500"><th className="py-4 px-6 font-medium w-12"></th><th className="py-4 px-6 font-medium">凭证字号</th><th className="py-4 px-6 font-medium">凭证日期</th><th className="py-4 px-6 font-medium">制单人</th><th className="py-4 px-6 font-medium text-right">借方金额</th><th className="py-4 px-6 font-medium text-right">贷方金额</th><th className="py-4 px-6 font-medium text-center">状态</th></tr></thead><tbody><TableRowSkeleton cols={7} /><TableRowSkeleton cols={7} /><TableRowSkeleton cols={7} /><TableRowSkeleton cols={7} /><TableRowSkeleton cols={7} /></tbody></table></div>
      ) : (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-sm text-slate-500">
                <th className="py-4 px-6 font-medium w-12">
                  <input
                    type="checkbox"
                    checked={vouchers.length > 0 && selectedIds.size === vouchers.length}
                    onChange={toggleSelectAll}
                    className="w-4 h-4 text-indigo-600 rounded border-slate-300 focus:ring-indigo-500"
                  />
                </th>
                <th className="py-4 px-6 font-medium">凭证字号</th>
                <th className="py-4 px-6 font-medium">凭证日期</th>
                <th className="py-4 px-6 font-medium">制单人</th>
                <th className="py-4 px-6 font-medium text-right">借方金额</th>
                <th className="py-4 px-6 font-medium text-right">贷方金额</th>
                <th className="py-4 px-6 font-medium text-center">状态</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {vouchers.map((v) => (
                <React.Fragment key={v.id}>
                  <VoucherRow
                    voucher={v}
                    isExpanded={expandedId === v.id}
                    isSelected={selectedIds.has(v.id)}
                    onToggleExpand={() => setExpandedId(expandedId === v.id ? null : v.id)}
                    onToggleSelect={makeToggleSelect(v.id)}
                  />
                  {expandedId === v.id && (
                    <VoucherRowDetail
                      voucher={v}
                      isEditing={editingId === v.id}
                      editEntries={editEntries}
                      accounts={accounts}
                      showInvoiceId={showInvoiceId}
                      onStartEditing={startEditing}
                      onCancelEditing={cancelEditing}
                      onSaveEditing={saveEditing}
                      onPostVoucher={postVoucher}
                      onUnpostVoucher={unpostVoucher}
                      onUpdateEntry={updateEntry}
                      onToggleInvoice={() => handleToggleInvoice(v.id)}
                      onReverse={reverseVoucher}
                      onDelete={deleteVoucher}
                    />
                  )}
                </React.Fragment>
              ))}
              {vouchers.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-500">
                    暂无凭证数据                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {!loading && total > pageSize && (
        <div className="flex justify-between items-center mt-4 text-sm text-slate-600">
          <div>共 {total} 条，第 {page}/{totalPages} 页</div>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(page - 1)}
              disabled={page <= 1}
              className={`px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors ${page <= 1 ? 'bg-slate-50 border-slate-200 text-slate-400 cursor-not-allowed' : 'bg-white border-slate-300 text-slate-700 hover:bg-slate-50'}`}
            >
              上一页            </button>
            <button
              onClick={() => setPage(page + 1)}
              disabled={page >= totalPages}
              className={`px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors ${page >= totalPages ? 'bg-slate-50 border-slate-200 text-slate-400 cursor-not-allowed' : 'bg-white border-slate-300 text-slate-700 hover:bg-slate-50'}`}
            >
              下一页            </button>
          </div>
        </div>
      )}

      {selectedIds.size > 0 && !loading && (
        <BatchToolbar
          selectedCount={selectedIds.size}
          onCancel={() => setSelectedIds(new Set())}
          onBatchReview={handleBatchReview}
          onBatchUnpost={handleBatchUnpost}
          onBatchPrint={handleBatchPrint}
        />
      )}

      {isBatchPrinting && (
        <BatchPrintTemplate
          vouchers={vouchers}
          selectedIds={selectedIds}
          currentLedger={currentLedger!}
        />
      )}

      <CreateVoucherModal
        show={showCreateModal}
        createDate={createDate}
        onCreateDateChange={setCreateDate}
        createEntries={createEntries}
        accounts={accounts}
        partners={partners}
        currencies={currencies}
        rates={rates}
        loading={loading}
        onClose={() => setShowCreateModal(false)}
        onAddEntry={handleAddEntry}
        onUpdateEntry={handleCreateUpdateEntry}
        onDeleteEntry={handleDeleteEntry}
        onSubmit={handleCreateVoucher}
      />
    </div>
  );
}
