import { sum, format } from "@/lib/decimal";
import type { Voucher, VoucherEntry } from "@/lib/types";

interface Props {
  voucher: Voucher;
  isExpanded: boolean;
  isSelected: boolean;
  onToggleExpand: () => void;
  onToggleSelect: () => void;
}

export default function VoucherRow({ voucher: v, isExpanded, isSelected, onToggleExpand, onToggleSelect }: Props) {
  const summary = v.entries?.length > 0 ? v.entries[0].summary : "无摘要";
  const totalDebit = sum(v.entries?.filter((e: VoucherEntry) => e.direction === "借").map((e: VoucherEntry) => e.amount) ?? []);
  const totalCredit = sum(v.entries?.filter((e: VoucherEntry) => e.direction === "贷").map((e: VoucherEntry) => e.amount) ?? []);

  return (
    <tr
      className="border-b border-slate-100 hover:bg-slate-50 transition-colors group cursor-pointer"
      onClick={onToggleExpand}
    >
      <td className="py-4 px-6" onClick={(e) => e.stopPropagation()}>
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onToggleSelect}
          className="w-4 h-4 text-indigo-600 rounded border-slate-300 focus:ring-indigo-500"
        />
      </td>
      <td className="py-4 px-6 text-slate-600">
        <div className="flex items-center gap-2">
          <svg className={`w-4 h-4 transition-transform ${isExpanded ? "rotate-90 text-indigo-500" : "text-slate-400"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          {v.voucher_date}
        </div>
      </td>
      <td className="py-4 px-6 font-medium text-indigo-600">{v.voucher_number}</td>
      <td className="py-4 px-6 text-slate-700">{summary}</td>
      <td className="py-4 px-6 text-right font-mono text-slate-700">{totalDebit}</td>
      <td className="py-4 px-6 text-right font-mono text-slate-700">{totalCredit}</td>
      <td className="py-4 px-6 text-center">
        <span className={`px-2 py-1 rounded-lg text-xs font-medium ${v.status === "DRAFT" ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700"}`}>
          {v.status === "DRAFT" ? "草稿 (未审核)" : v.status === "POSTED" ? "已过账" : v.status}
        </span>
      </td>
    </tr>
  );
}
