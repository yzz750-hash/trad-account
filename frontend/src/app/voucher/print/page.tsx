import { Suspense } from "react";
import PrintContent from "./print-content";

export default async function VoucherPrintPage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string }>;
}) {
  const { id } = await searchParams;

  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-slate-100 flex items-center justify-center">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-slate-900 mx-auto mb-3"></div>
            <p className="text-slate-500 text-sm">加载打印页面...</p>
          </div>
        </div>
      }
    >
      <PrintContent voucherId={id} />
    </Suspense>
  );
}
