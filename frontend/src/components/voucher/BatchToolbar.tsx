interface Props {
  selectedCount: number;
  onCancel: () => void;
  onBatchReview: () => void;
  onBatchUnpost: () => void;
  onBatchPrint: () => void;
}

export default function BatchToolbar({ selectedCount, onCancel, onBatchReview, onBatchUnpost, onBatchPrint }: Props) {
  return (
    <div className="fixed bottom-8 left-1/2 -translate-x-1/2 bg-slate-900 text-white px-6 py-4 rounded-full shadow-2xl flex items-center gap-6 z-40 print:hidden animate-fade-in-up">
      <div className="text-sm font-medium">已选择 {selectedCount} 张凭证</div>
      <div className="h-4 w-px bg-slate-700"></div>
      <div className="flex gap-3">
        <button
          onClick={onCancel}
          className="text-slate-300 hover:text-white text-sm transition-colors"
        >
          取消选择
        </button>
        <button
          onClick={onBatchReview}
          className="bg-emerald-500 text-white px-4 py-1.5 rounded-full text-sm font-bold hover:bg-emerald-400 transition-colors flex items-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
          批量复核
        </button>
        <button
          onClick={onBatchUnpost}
          className="bg-amber-500 text-white px-4 py-1.5 rounded-full text-sm font-bold hover:bg-amber-400 transition-colors flex items-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2M3 12l6.343 6.343A8 8 0 0015.657 6.343a8 8 0 00-12.014 0L3 12z" /></svg>
          批量反审核退回
        </button>
        <button
          onClick={onBatchPrint}
          className="bg-white text-slate-900 px-4 py-1.5 rounded-full text-sm font-bold hover:bg-slate-100 transition-colors flex items-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" /></svg>
          批量打印
        </button>
      </div>
    </div>
  );
}
