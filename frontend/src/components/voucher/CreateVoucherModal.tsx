"use client";

import type { AccountInfo, VoucherEntryDraft, Partner, Currency } from "@/lib/types";
import AccountSelect from "@/components/AccountSelect";
import { sum, d } from "@/lib/decimal";

interface Props {
  show: boolean;
  createDate: string; onCreateDateChange: (v: string) => void;
  createEntries: VoucherEntryDraft[];
  accounts: AccountInfo[];
  partners: Partner[];
  currencies: Currency[];
  rates: Record<string, number>;
  loading: boolean;
  onClose: () => void;
  onAddEntry: () => void;
  onUpdateEntry: (index: number, field: string, value: string) => void;
  onDeleteEntry: (index: number) => void;
  onSubmit: () => void;
}

export default function CreateVoucherModal({
  show, createDate, onCreateDateChange, createEntries, accounts, partners, currencies, rates,
  loading, onClose, onAddEntry, onUpdateEntry, onDeleteEntry, onSubmit,
}: Props) {
  if (!show) return null;

  const debit = sum(createEntries.filter((e) => e.direction === "借").map((e) => e.amount));
  const credit = sum(createEntries.filter((e) => e.direction === "贷").map((e) => e.amount));
  const isBalanced = d(debit).eq(d(credit)) && d(debit).gt(0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50 rounded-t-2xl">
          <h2 className="text-lg font-bold text-slate-800">新增记账凭证</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>

        <div className="p-6 overflow-y-auto flex-1">
          <div className="mb-6 flex gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">凭证日期</label>
              <input type="date" value={createDate} onChange={(e) => onCreateDateChange(e.target.value)} className="border border-slate-300 rounded-lg px-3 py-2 text-sm" />
            </div>
          </div>

          <table className="w-full text-left border-collapse border border-slate-200 rounded-lg overflow-hidden">
            <thead className="bg-slate-50 border-b border-slate-200 text-sm text-slate-500">
              <tr>
                <th className="py-3 px-4 font-medium w-1/4">摘要</th>
                <th className="py-3 px-4 font-medium w-1/4">科目与辅助核算</th>
                <th className="py-3 px-4 font-medium w-24 text-center">借贷方向</th>
                <th className="py-3 px-4 font-medium w-48 text-right">币种/本位币金额</th>
                <th className="py-3 px-4 font-medium w-16 text-center">操作</th>
              </tr>
            </thead>
            <tbody>
              {createEntries.map((entry, index) => (
                <tr key={index} className="border-b border-slate-100">
                  <td className="p-2"><input type="text" value={entry.summary} onChange={(e) => onUpdateEntry(index, "summary", e.target.value)} className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm" placeholder="输入摘要" /></td>
                  <td className="p-2">
                    <AccountSelect
                      accounts={accounts}
                      className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm mb-1"
                      value={entry.account_code}
                      onChange={(val) => onUpdateEntry(index, "account_code", val)}
                    />
                    {(entry.account_code && (entry.account_code.startsWith("1122") || entry.account_code.startsWith("2202") || entry.account_code.startsWith("1123") || entry.account_code.startsWith("2203"))) && (
                      <select
                        value={entry.partner_id || ""}
                        onChange={(e) => onUpdateEntry(index, "partner_id", e.target.value)}
                        className="w-full border border-orange-300 bg-orange-50 text-orange-700 rounded px-2 py-1 text-xs"
                      >
                        <option value="">-- 选择往来单位(可选) --</option>
                        {partners.map((p) => (
                          <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                      </select>
                    )}
                  </td>
                  <td className="p-2 text-center">
                    <select value={entry.direction} onChange={(e) => onUpdateEntry(index, "direction", e.target.value)} className="border border-slate-300 rounded px-2 py-1.5 text-sm">
                      <option value="借">借</option>
                      <option value="贷">贷</option>
                    </select>
                  </td>
                  <td className="p-2 text-right flex gap-1 justify-end">
                    <div className="flex flex-col gap-1 w-24">
                      <select
                        value={entry.currency_code || "CNY"}
                        onChange={(e) => onUpdateEntry(index, "currency_code", e.target.value)}
                        className="w-full border border-slate-300 rounded px-1 py-1 text-xs"
                      >
                        {currencies.map((c) => (
                          <option key={c.code} value={c.code}>{c.code}</option>
                        ))}
                      </select>
                      {entry.currency_code !== "CNY" && (
                        <div className="flex gap-1">
                          <input type="number" value={entry.original_amount || ""} onChange={(e) => onUpdateEntry(index, "original_amount", e.target.value)} className="w-1/2 border border-indigo-200 bg-indigo-50 rounded px-2 py-1 text-xs font-mono text-right" placeholder="原币" />
                          <input type="number" value={entry.exchange_rate || ""} onChange={(e) => onUpdateEntry(index, "exchange_rate", e.target.value)} className="w-1/2 border border-indigo-200 bg-indigo-50 rounded px-2 py-1 text-xs font-mono text-right" placeholder="汇率" />
                        </div>
                      )}
                    </div>
                    <div className="flex flex-col justify-end w-24">
                      <input type="number" value={entry.amount} onChange={(e) => onUpdateEntry(index, "amount", e.target.value)} className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm font-mono text-right" placeholder="本位币金额" />
                    </div>
                  </td>
                  <td className="p-2 text-center">
                    <button onClick={() => onDeleteEntry(index)} className="text-red-400 hover:text-red-600 p-1">删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <button onClick={onAddEntry} className="mt-3 text-indigo-600 text-sm font-medium hover:text-indigo-800 flex items-center gap-1">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" /></svg>
            添加分录
          </button>
        </div>

        <div className="px-6 py-4 border-t border-slate-100 bg-slate-50 flex justify-between items-center rounded-b-2xl">
          <div className="flex gap-6 text-sm">
            <div>借方合计: <span className="font-mono font-medium text-slate-800">{debit}</span></div>
            <div>贷方合计: <span className="font-mono font-medium text-slate-800">{credit}</span></div>
            <div className={`font-medium ${isBalanced ? "text-emerald-600" : "text-red-500"}`}>
              {isBalanced ? "✓ 借贷平衡" : "✗ 借贷不平衡"}
            </div>
          </div>
          <div className="flex gap-3">
            <button onClick={onClose} className="px-4 py-2 border border-slate-300 bg-white text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50">取消</button>
            <button
              onClick={onSubmit}
              disabled={!isBalanced || loading}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${isBalanced && !loading ? "bg-indigo-600 text-white hover:bg-indigo-700" : "bg-slate-200 text-slate-400 cursor-not-allowed"}`}
            >
              保存为草稿
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
