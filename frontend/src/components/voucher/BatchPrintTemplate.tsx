import { sum } from "@/lib/decimal";
import type { Voucher, Ledger } from "@/lib/types";

interface Props {
  vouchers: Voucher[];
  selectedIds: Set<number>;
  currentLedger: Ledger;
}

export default function BatchPrintTemplate({ vouchers, selectedIds, currentLedger }: Props) {
  return (
    <div className="hidden print:block">
      <style dangerouslySetInnerHTML={{__html: `
        @page { size: A4 portrait; margin: 15mm; }
        body { font-family: 'SimSun', 'Songti SC', serif; }
        .print-voucher {
          height: 130mm;
          page-break-inside: avoid;
          display: flex;
          flex-direction: column;
          justify-content: center;
          border-bottom: 1px dashed #ccc;
          padding-bottom: 5mm;
          margin-bottom: 5mm;
        }
        .print-voucher:nth-child(even) {
          page-break-after: always;
          border-bottom: none;
        }
      `}} />
      {vouchers.filter((v) => selectedIds.has(v.id)).map((v) => (
        <div key={v.id} className="print-voucher">
          <h1 className="text-2xl font-bold text-center mb-4 tracking-widest border-b-2 border-double border-black pb-1 mx-32">记账凭证</h1>
          <div className="flex justify-between items-center mb-4 text-sm font-bold px-2">
            <div>核算单位：{currentLedger?.company_name || currentLedger?.name || ""}</div>
            <div>日期：{v.voucher_date}</div>
            <div>凭证字号：{v.voucher_number}</div>
          </div>
          <table className="w-full border-collapse border-2 border-black text-sm mb-4">
            <thead>
              <tr>
                <th className="border border-black py-3 px-2 text-center w-1/4">摘要</th>
                <th className="border border-black py-3 px-2 text-center w-1/3">会计科目</th>
                <th className="border border-black py-3 px-2 text-center w-1/5">借方金额</th>
                <th className="border border-black py-3 px-2 text-center w-1/5">贷方金额</th>
              </tr>
            </thead>
            <tbody>
              {v.entries?.map((e, idx) => (
                <tr key={idx} className="h-8">
                  <td className="border border-black px-2 py-1">{e.summary}</td>
                  <td className="border border-black px-2 py-1">
                    {e.account?.code} {e.account?.name}
                  </td>
                  <td className="border border-black px-2 py-1 text-right font-mono">
                    {e.direction === "借" ? Number(e.amount).toFixed(2) : ""}
                  </td>
                  <td className="border border-black px-2 py-1 text-right font-mono">
                    {e.direction === "贷" ? Number(e.amount).toFixed(2) : ""}
                  </td>
                </tr>
              ))}
              {Array.from({ length: Math.max(0, 4 - (v.entries?.length || 0)) }).map((_, idx) => (
                <tr key={`empty-${idx}`} className="h-8">
                  <td className="border border-black px-2 py-1"></td>
                  <td className="border border-black px-2 py-1"></td>
                  <td className="border border-black px-2 py-1"></td>
                  <td className="border border-black px-2 py-1"></td>
                </tr>
              ))}
              <tr className="h-8">
                <td colSpan={2} className="border border-black py-1 px-2 text-right font-bold">合 计</td>
                <td className="border border-black py-1 px-2 text-right font-mono font-bold">
                  {sum(v.entries?.filter((e) => e.direction === "借").map((e) => e.amount) ?? [])}
                </td>
                <td className="border border-black py-1 px-2 text-right font-mono font-bold">
                  {sum(v.entries?.filter((e) => e.direction === "贷").map((e) => e.amount) ?? [])}
                </td>
              </tr>
            </tbody>
          </table>
          <div className="flex justify-between items-center text-sm px-2 mt-auto">
            <div>财务主管：</div>
            <div>记账：</div>
            <div>复核：</div>
            <div>制单：自动生成</div>
          </div>
        </div>
      ))}
    </div>
  );
}
