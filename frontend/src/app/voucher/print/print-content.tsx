"use client";

import { useEffect, useState } from "react";
import { apiFetch, errMsg } from "@/lib/api";
import { sum } from "@/lib/decimal";

const PRINT_SIZES = {
  "CUSTOM": { label: "专用尺寸 (24x14cm)", width: "24cm", height: "14cm" },
  "A4": { label: "标准 A4 (21x29.7cm)", width: "21cm", height: "29.7cm" },
  "A5": { label: "标准 A5 (21x14.8cm)", width: "21cm", height: "14.8cm" },
};

type PrintSizeType = keyof typeof PRINT_SIZES;

interface PrintEntry {
  account_code: string;
  account_name: string;
  summary: string;
  direction: string;
  amount: number;
}

interface PrintData {
  voucher_number: string;
  voucher_date: string;
  attachments_count: number;
  entries: PrintEntry[];
  ledger_name: string;
  company_name: string;
}

/** Convert a number to Chinese financial uppercase (e.g. 12450 -> 壹万贰仟肆佰伍拾元整) */
function toChineseUppercase(n: number): string {
  if (n === 0) return "零元整";

  const digits = "零壹贰叁肆伍陆柒捌玖";
  const radices = ["", "拾", "佰", "仟"];
  const bigRadices = ["", "万", "亿", "兆"];

  const yuan = Math.floor(n);
  const decimals = Math.round((n - yuan) * 100);
  const jiao = Math.floor(decimals / 10);
  const fen = decimals % 10;

  let result = "";

  if (yuan === 0) {
    // No integer part; handle decimals only
  } else {
    let zeroCount = 0;
    const yuanStr = yuan.toString();

    for (let i = 0; i < yuanStr.length; i++) {
      const p = yuanStr.length - 1 - i; // position from right (0-indexed)
      const d = parseInt(yuanStr[i]);
      const quotient = Math.floor(p / 4);
      const modulus = p % 4;

      if (d === 0) {
        zeroCount++;
      } else {
        if (zeroCount > 0) {
          result += "零";
          zeroCount = 0;
        }
        result += digits[d] + radices[modulus];
      }

      if (modulus === 0 && zeroCount < 4) {
        result += bigRadices[quotient];
        zeroCount = 0;
      }
    }
    result += "元";
  }

  if (jiao === 0 && fen === 0) {
    result += "整";
  } else {
    if (jiao > 0) {
      result += digits[jiao] + "角";
    }
    if (fen > 0) {
      result += digits[fen] + "分";
    }
  }

  return result;
}

interface PrintContentProps {
  voucherId: string | undefined;
}

export default function PrintContent({ voucherId }: PrintContentProps) {
  const [printSize, setPrintSize] = useState<PrintSizeType>("CUSTOM");
  const [data, setData] = useState<PrintData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!voucherId) {
      setError("缺少凭证编号参数");
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const result = await apiFetch<PrintData>(
          `/api/v1/vouchers/${voucherId}/print`
        );
        if (!cancelled) {
          setData(result);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(errMsg(err) || "加载凭证数据失败");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [voucherId]);

  const currentSize = PRINT_SIZES[printSize];

  // Compute totals from real entries
  const debitEntries = data?.entries.filter((e) => e.direction === "借") ?? [];
  const creditEntries =
    data?.entries.filter((e) => e.direction === "贷") ?? [];
  const totalDebit = sum(debitEntries.map((e) => e.amount));
  const totalCredit = sum(creditEntries.map((e) => e.amount));

  // Offset entries for two-column layout: show all debits first, then all credits
  const totalEntryCount = debitEntries.length + creditEntries.length;
  const minRows = Math.max(totalEntryCount, 3); // at least 3 rows including padding

  return (
    <div className="min-h-screen bg-slate-100 flex flex-col items-center justify-center p-8 print:p-0 print:bg-white">
      {/* Print settings toolbar (hidden when printing) */}
      <div className="print:hidden mb-6 flex gap-4 items-center bg-white p-4 rounded-xl shadow-sm border border-slate-200">
        <label className="text-sm font-semibold text-slate-700">
          选择打印规则:
        </label>
        <select
          value={printSize}
          onChange={(e) => setPrintSize(e.target.value as PrintSizeType)}
          className="bg-slate-50 border border-slate-300 text-slate-900 text-sm rounded-lg focus:ring-slate-500 focus:border-slate-500 block p-2"
        >
          {Object.entries(PRINT_SIZES).map(([key, config]) => (
            <option key={key} value={key}>
              {config.label}
            </option>
          ))}
        </select>
        <button
          onClick={() => window.print()}
          className="bg-slate-900 text-white px-5 py-2 rounded-lg hover:bg-slate-800 transition-all flex items-center gap-2 text-sm ml-4"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z"
            />
          </svg>
          立即打印
        </button>
      </div>

      {/* Dynamic Page Size Injection */}
      <style
        dangerouslySetInnerHTML={{
          __html: `
        @media print {
          @page {
            size: ${currentSize.width} ${currentSize.height};
            margin: 0;
          }
          body {
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
          }
        }
      `,
        }}
      />

      {/* Printable Area */}
      <div
        className="bg-white shadow-2xl print:shadow-none mx-auto relative overflow-hidden print:overflow-visible transition-all duration-300"
        style={{ width: currentSize.width, minHeight: currentSize.height }}
      >
        {loading ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-slate-900 mx-auto mb-3"></div>
              <p className="text-slate-500 text-sm">加载凭证数据...</p>
            </div>
          </div>
        ) : error ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center text-red-500">
              <svg
                className="w-10 h-10 mx-auto mb-3"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z"
                />
              </svg>
              <p className="text-sm">{error}</p>
            </div>
          </div>
        ) : data ? (
          <div className="p-8 min-h-full flex flex-col border border-slate-200 print:border-none">
            {/* Header */}
            <div className="text-center mb-6 relative">
              <h1 className="text-2xl font-bold tracking-widest text-slate-900">
                记账凭证
              </h1>
              <div className="absolute right-0 top-2 flex flex-col items-end text-xs text-slate-500 font-mono">
                {data.company_name && (
                  <span className="mb-0.5">单位: {data.company_name}</span>
                )}
                <span>凭证字号: {data.voucher_number}</span>
                <span>日期: {data.voucher_date}</span>
                <span>附件数: {data.attachments_count} 张</span>
              </div>
              <div className="w-1/3 mx-auto h-[1px] bg-slate-900 mt-2"></div>
              <div className="w-1/3 mx-auto h-[1px] bg-slate-900 mt-[2px]"></div>
            </div>

            {/* Table */}
            <table className="w-full text-sm border-collapse border border-slate-900 flex-1">
              <thead>
                <tr className="bg-slate-50">
                  <th className="border border-slate-900 py-2 px-3 text-center w-1/3">
                    摘要
                  </th>
                  <th className="border border-slate-900 py-2 px-3 text-center w-1/3">
                    会计科目
                  </th>
                  <th className="border border-slate-900 py-2 px-3 text-center w-1/6">
                    借方金额
                  </th>
                  <th className="border border-slate-900 py-2 px-3 text-center w-1/6">
                    贷方金额
                  </th>
                </tr>
              </thead>
              <tbody>
                {/* Debit entries - shown first */}
                {debitEntries.map((debit, i) => (
                  <tr key={`debit-${i}`}>
                    <td className="border border-slate-900 py-3 px-3">
                      {debit.summary}
                    </td>
                    <td className="border border-slate-900 py-3 px-3">
                      {debit.account_code} {debit.account_name}
                    </td>
                    <td className="border border-slate-900 py-3 px-3 text-right font-mono">
                      {Number(debit.amount).toFixed(2)}
                    </td>
                    <td className="border border-slate-900 py-3 px-3 text-right font-mono"></td>
                  </tr>
                ))}
                {/* Credit entries - shown second */}
                {creditEntries.map((credit, i) => (
                  <tr key={`credit-${i}`}>
                    <td className="border border-slate-900 py-3 px-3">
                      {credit.summary}
                    </td>
                    <td className="border border-slate-900 py-3 px-3">
                      {credit.account_code} {credit.account_name}
                    </td>
                    <td className="border border-slate-900 py-3 px-3 text-right font-mono"></td>
                    <td className="border border-slate-900 py-3 px-3 text-right font-mono">
                      {Number(credit.amount).toFixed(2)}
                    </td>
                  </tr>
                ))}
                {/* Padding rows to fill space */}
                {Array.from({
                  length: Math.max(0, minRows - totalEntryCount),
                }).map((_, i) => (
                  <tr key={`empty-${i}`} className="h-full">
                    <td className="border border-slate-900 py-3 px-3"></td>
                    <td className="border border-slate-900 py-3 px-3"></td>
                    <td className="border border-slate-900 py-3 px-3"></td>
                    <td className="border border-slate-900 py-3 px-3"></td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td
                    colSpan={2}
                    className="border border-slate-900 py-2 px-3"
                  >
                    <span className="font-semibold tracking-widest">合计: </span>
                    <span>
                      {toChineseUppercase(
                        Number(totalDebit) || Number(totalCredit)
                      )}
                    </span>
                  </td>
                  <td className="border border-slate-900 py-2 px-3 text-right font-mono font-bold">
                    {totalDebit}
                  </td>
                  <td className="border border-slate-900 py-2 px-3 text-right font-mono font-bold">
                    {totalCredit}
                  </td>
                </tr>
              </tfoot>
            </table>

            {/* Footer Signatures */}
            <div className="mt-4 flex justify-between text-xs text-slate-700">
              <span>
                财务主管:{" "}
                <span className="underline decoration-slate-300 underline-offset-4">
                  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
                </span>
              </span>
              <span>
                复核:{" "}
                <span className="underline decoration-slate-300 underline-offset-4">
                  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
                </span>
              </span>
              <span>
                制单:{" "}
                <span className="underline decoration-slate-300 underline-offset-4">
                  AI-系统自动
                </span>
              </span>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
