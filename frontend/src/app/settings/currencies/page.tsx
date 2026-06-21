"use client";

import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";

interface Currency {
  id: number;
  code: string;
  name: string;
  is_base: boolean;
}

interface ExchangeRate {
  currency_code: string;
  rate: number;
}

export default function CurrenciesSettingsPage() {
  const [currencies, setCurrencies] = useState<Currency[]>([]);
  const [rates, setRates] = useState<ExchangeRate[]>([]);
  const [year, setYear] = useState<number>(new Date().getFullYear());
  const [month, setMonth] = useState<number>(new Date().getMonth() + 1);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [currData, ratesData] = await Promise.all([
        apiFetch<Currency[]>("/api/v1/system/currencies"),
        apiFetch<ExchangeRate[]>(`/api/v1/system/rates?year=${year}&month=${month}`),
      ]);
      setCurrencies(currData);
      setRates(ratesData);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [year, month]);

  const handleUpdateRate = async (currencyCode: string, newRate: string) => {
    const rateVal = parseFloat(newRate);
    if (isNaN(rateVal) || rateVal <= 0) return;
    try {
      await apiFetch(`/api/v1/system/rates?year=${year}&month=${month}`, {
        method: "POST",
        body: JSON.stringify({ currency_code: currencyCode, rate: rateVal }),
      });
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  const getRateForCurrency = (code: string) => {
    const r = rates.find(x => x.currency_code === code);
    return r ? r.rate : 1.0;
  };

  if (loading) return <div className="p-8">Loading...</div>;

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <div className="flex justify-between items-end mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">汇率管理台</h1>
          <p className="text-slate-500 mt-1">管理各币种对应本位币(CNY)的记账汇率，用于多币种凭证及期末调汇</p>
        </div>
        <div className="flex gap-4">
          <select value={year} onChange={e => setYear(parseInt(e.target.value))} className="border border-slate-300 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-slate-900">
            {[2023, 2024, 2025, 2026].map(y => <option key={y} value={y}>{y}年</option>)}
          </select>
          <select value={month} onChange={e => setMonth(parseInt(e.target.value))} className="border border-slate-300 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-slate-900">
            {Array.from({length: 12}, (_, i) => i + 1).map(m => <option key={m} value={m}>{m}月</option>)}
          </select>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 font-medium">
            <tr>
              <th className="px-6 py-4">币种编码</th>
              <th className="px-6 py-4">名称</th>
              <th className="px-6 py-4">是否本位币</th>
              <th className="px-6 py-4 text-right">当期记账汇率 (兑本位币)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {currencies.map((c) => (
              <tr key={c.id} className="hover:bg-slate-50">
                <td className="px-6 py-4 font-mono font-medium text-slate-900">{c.code}</td>
                <td className="px-6 py-4 text-slate-600">{c.name}</td>
                <td className="px-6 py-4">
                  {c.is_base ? <span className="px-2 py-1 rounded text-xs font-medium bg-emerald-50 text-emerald-700">是</span> : <span className="text-slate-400">-</span>}
                </td>
                <td className="px-6 py-4 text-right">
                  {c.is_base ? (
                    <span className="text-slate-400">1.0000</span>
                  ) : (
                    <input 
                      type="number"
                      step="0.0001"
                      className="w-32 text-right border border-slate-300 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-slate-900"
                      defaultValue={getRateForCurrency(c.code)}
                      onBlur={(e) => handleUpdateRate(c.code, e.target.value)}
                    />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
