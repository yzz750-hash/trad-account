"use client";

interface Props {
  search: string; onSearchChange: (v: string) => void;
  filterStartDate: string; onFilterStartDateChange: (v: string) => void;
  filterEndDate: string; onFilterEndDateChange: (v: string) => void;
  filterMinAmount: string; onFilterMinAmountChange: (v: string) => void;
  filterMaxAmount: string; onFilterMaxAmountChange: (v: string) => void;
  filterStatus: string; onFilterStatusChange: (v: string) => void;
  onSearch: () => void;
  onReset: () => void;
}

export default function VoucherFilterBar({
  search, onSearchChange,
  filterStartDate, onFilterStartDateChange,
  filterEndDate, onFilterEndDateChange,
  filterMinAmount, onFilterMinAmountChange,
  filterMaxAmount, onFilterMaxAmountChange,
  filterStatus, onFilterStatusChange,
  onSearch, onReset,
}: Props) {
  return (
    <div className="bg-white p-4 rounded-xl shadow-sm border border-slate-200 mb-6 flex flex-wrap gap-3 items-end">
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-slate-600">关键词</label>
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="凭证字号 / 摘要..."
          className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 w-48"
          onKeyDown={(e) => { if (e.key === 'Enter') onSearch(); }}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-slate-600">开始日期</label>
        <input type="date" value={filterStartDate} onChange={(e) => onFilterStartDateChange(e.target.value)} className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20" />
      </div>
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-slate-600">结束日期</label>
        <input type="date" value={filterEndDate} onChange={(e) => onFilterEndDateChange(e.target.value)} className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20" />
      </div>
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-slate-600">最小金额</label>
        <input type="number" value={filterMinAmount} onChange={(e) => onFilterMinAmountChange(e.target.value)} placeholder="0.00" className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 w-28" />
      </div>
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-slate-600">最大金额</label>
        <input type="number" value={filterMaxAmount} onChange={(e) => onFilterMaxAmountChange(e.target.value)} placeholder="0.00" className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 w-28" />
      </div>
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-slate-600">状态</label>
        <select value={filterStatus} onChange={(e) => onFilterStatusChange(e.target.value)} className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20">
          <option value="">全部</option>
          <option value="DRAFT">草稿 (未审核)</option>
          <option value="POSTED">已过账</option>
        </select>
      </div>
      <div className="flex gap-2">
        <button
          onClick={onSearch}
          className="bg-accent text-white px-5 py-2 rounded-lg hover:bg-accent-light transition-colors shadow-sm text-sm font-medium h-[38px]"
        >
          查询
        </button>
        <button
          onClick={onReset}
          className="bg-white border border-slate-300 text-slate-600 px-3 py-2 rounded-lg hover:bg-slate-50 transition-colors text-sm font-medium h-[38px]"
        >
          重置
        </button>
      </div>
    </div>
  );
}
