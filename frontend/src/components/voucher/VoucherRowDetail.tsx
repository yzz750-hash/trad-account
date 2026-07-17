"use client";

import { useRouter } from "next/navigation";
import type { Voucher, VoucherEntry, AccountInfo } from "@/lib/types";
import AccountSelect from "@/components/AccountSelect";

interface Props {
  voucher: Voucher;
  isEditing: boolean;
  editEntries: VoucherEntry[];
  accounts: AccountInfo[];
  showInvoiceId: number | null;
  onStartEditing: (v: Voucher) => void;
  onCancelEditing: () => void;
  onSaveEditing: (id: number) => void;
  onPostVoucher: (id: number) => void;
  onUnpostVoucher: (id: number) => void;
  onUpdateEntry: (index: number, field: string, value: string | number) => void;
  onToggleInvoice: () => void;
  onReverse: (id: number) => void;
  onDelete: (id: number) => void;
}

export default function VoucherRowDetail({
  voucher: v, isEditing, editEntries, accounts, showInvoiceId,
  onStartEditing, onCancelEditing, onSaveEditing, onPostVoucher, onUnpostVoucher,
  onUpdateEntry, onToggleInvoice, onReverse, onDelete,
}: Props) {
  const router = useRouter();

  return (
    <tr className="bg-slate-50/50 border-b border-slate-200">
      <td colSpan={7} className="p-0">
        <div className="px-12 py-6">
          <div className="flex justify-between items-center mb-3">
            <div className="text-xs font-medium text-slate-500 uppercase tracking-wider">凭证明细 (Voucher Entries)</div>
            <div className="flex gap-2">
              {v.status === "DRAFT" && !isEditing && (
                <>
                  <button onClick={() => onStartEditing(v)} className="px-3 py-1 bg-white border border-slate-300 text-slate-700 rounded-lg text-xs font-medium hover:bg-slate-50 transition-colors">编辑凭证</button>
                  <button onClick={() => onPostVoucher(v.id)} className="px-3 py-1 bg-emerald-600 text-white rounded-lg text-xs font-medium hover:bg-emerald-700 transition-colors">审核并过账</button>
                  <button onClick={() => onDelete(v.id)} className="px-3 py-1 bg-white border border-red-300 text-red-600 rounded-lg text-xs font-medium hover:bg-red-50 transition-colors">删除</button>
                </>
              )}
              {isEditing && (
                <>
                  <button onClick={onCancelEditing} className="px-3 py-1 bg-white border border-slate-300 text-slate-700 rounded-lg text-xs font-medium hover:bg-slate-50 transition-colors">取消</button>
                  <button onClick={() => onSaveEditing(v.id)} className="px-3 py-1 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 transition-colors">保存修改</button>
                </>
              )}
              {v.status === "POSTED" && (
                <button onClick={() => onUnpostVoucher(v.id)} className="px-3 py-1 bg-white border border-amber-300 text-amber-700 rounded-lg text-xs font-medium hover:bg-amber-50 transition-colors">反审核退回到草稿</button>
              )}
              <button onClick={() => router.push(`/voucher/print?id=${v.id}`)} className="px-3 py-1 bg-white border border-slate-300 text-slate-700 rounded-lg text-xs font-medium hover:bg-slate-50 transition-colors flex items-center gap-1">
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" /></svg>
                打印预览
              </button>
              {(v.attachments_count ?? 0) > 0 && (
                <button onClick={onToggleInvoice} className="px-3 py-1 bg-sky-50 border border-sky-200 text-sky-700 rounded-lg text-xs font-medium hover:bg-sky-100 transition-colors flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                  {showInvoiceId ? "隐藏原始发票" : "查看原始发票"}
                </button>
              )}
            </div>
          </div>
          <div className={`flex gap-6 ${showInvoiceId ? "items-start" : ""}`}>
            <div className={`${showInvoiceId ? "w-1/2" : "w-full"} transition-all duration-300`}>
              <table className="w-full bg-white rounded-lg shadow-sm border border-slate-200 text-sm overflow-hidden">
                <thead className="bg-slate-50 border-b border-slate-200 text-slate-500">
                  <tr>
                    <th className="py-2 px-4 font-medium font-mono text-left">科目编码</th>
                    <th className="py-2 px-4 font-medium text-left">科目名称</th>
                    <th className="py-2 px-4 font-medium text-left">摘要</th>
                    <th className="py-2 px-4 font-medium text-center">方向</th>
                    <th className="py-2 px-4 font-medium text-right">金额</th>
                  </tr>
                </thead>
                <tbody>
                  {(isEditing ? editEntries : v.entries)?.map((entry, index) => (
                    <tr key={entry.id || index} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                      <td className="py-2 px-4 font-mono text-slate-600">
                        {isEditing ? (
                          <AccountSelect
                            accounts={accounts}
                            className="w-48 border border-slate-300 rounded px-2 py-1 text-sm"
                            value={entry.account?.code || ""}
                            onChange={(val) => onUpdateEntry(index, "account_code", val)}
                          />
                        ) : (entry.account?.code || "-")}
                      </td>
                      <td className="py-2 px-4 text-slate-700">{entry.account?.name || "-"}</td>
                      <td className="py-2 px-4 text-slate-600">
                        {isEditing ? (
                          <input type="text" className="w-full border border-slate-300 rounded px-2 py-1 text-sm" value={entry.summary} onChange={(e) => onUpdateEntry(index, "summary", e.target.value)} />
                        ) : entry.summary}
                      </td>
                      <td className={`py-2 px-4 text-center font-medium ${entry.direction === "借" ? "text-indigo-600" : "text-orange-600"}`}>
                        {isEditing ? (
                          <select className="border border-slate-300 rounded px-2 py-1 text-sm" value={entry.direction} onChange={(e) => onUpdateEntry(index, "direction", e.target.value)}>
                            <option value="借">借</option>
                            <option value="贷">贷</option>
                          </select>
                        ) : entry.direction}
                      </td>
                      <td className="py-2 px-4 text-right font-mono text-slate-700">
                        {isEditing ? (
                          <input type="number" className="w-24 text-right border border-slate-300 rounded px-2 py-1 text-sm font-mono" value={entry.amount} onChange={(e) => onUpdateEntry(index, "amount", e.target.value)} />
                        ) : Number(entry.amount).toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {showInvoiceId && (
              <div className="w-1/2 bg-slate-100 rounded-lg border border-slate-200 overflow-hidden flex flex-col h-[400px]">
                <div className="px-4 py-2 bg-slate-200 border-b border-slate-300 text-xs font-bold text-slate-600 flex justify-between">
                  <span>电子发票原件</span>
                  <span>凭证字号: {v.voucher_number}</span>
                </div>
                <div className="flex-1 p-4 overflow-y-auto flex items-center justify-center">
                  <img
                    src="https://images.unsplash.com/photo-1554224155-8d04cb21cd6c?w=600&q=80"
                    alt="Invoice"
                    className="max-w-full rounded shadow-sm border border-slate-300"
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      </td>
    </tr>
  );
}
