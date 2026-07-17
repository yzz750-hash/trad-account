"use client";

import { useState, useEffect } from "react";
import { apiFetch, errMsg } from "@/lib/api";

interface Partner {
  id: number;
  code: string;
  name: string;
  partner_type: string;
}

export default function PartnersSettingsPage() {
  const [partners, setPartners] = useState<Partner[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchKeyword, setSearchKeyword] = useState("");

  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("CUSTOMER");

  const fetchPartners = async () => {
    setLoading(true);
    try {
      const data = await apiFetch("/api/v1/partners");
      setPartners(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPartners();
  }, []);

  const handleAddPartner = async () => {
    if (!newCode || !newName) return;
    try {
      await apiFetch("/api/v1/partners", {
        method: "POST",
        body: JSON.stringify({ code: newCode, name: newName, partner_type: newType }),
      });
      setNewCode("");
      setNewName("");
      await fetchPartners();
    } catch (err: unknown) {
      console.error(err);
      alert(errMsg(err) || "添加客商失败");
    }
  };

  if (loading) return <div className="p-8">Loading...</div>;

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-900">客商档案管理 (CRM/SRM)</h1>
        <p className="text-slate-500 mt-1">管理客户、供应商与员工档案，用于凭证的辅助核算</p>
      </div>

      <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200 mb-8 flex gap-4 items-end">
        <div className="flex-1">
          <label className="block text-sm font-medium text-slate-700 mb-1">客商编码</label>
          <input type="text" value={newCode} onChange={(e)=>setNewCode(e.target.value)} className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-900" placeholder="e.g. C001" />
        </div>
        <div className="flex-1">
          <label className="block text-sm font-medium text-slate-700 mb-1">客商名称</label>
          <input type="text" value={newName} onChange={(e)=>setNewName(e.target.value)} className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-900" placeholder="e.g. 某某科技公司" />
        </div>
        <div className="flex-1">
          <label className="block text-sm font-medium text-slate-700 mb-1">类型</label>
          <select value={newType} onChange={(e)=>setNewType(e.target.value)} className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-900">
            <option value="CUSTOMER">客户 (CUSTOMER)</option>
            <option value="VENDOR">供应商 (VENDOR)</option>
            <option value="BOTH">客户/供应商 (BOTH)</option>
          </select>
        </div>
        <button onClick={handleAddPartner} className="px-6 py-2 bg-slate-900 text-white rounded-lg hover:bg-slate-800 font-medium whitespace-nowrap transition-colors">
          新增档案
        </button>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
        <div className="p-4 border-b border-slate-100">
          <input
            type="text"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            placeholder="搜索客商编码或名称..."
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 w-72"
          />
        </div>
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 font-medium">
            <tr>
              <th className="px-6 py-4">客商编码</th>
              <th className="px-6 py-4">客商名称</th>
              <th className="px-6 py-4">类型</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {partners.filter(p => !searchKeyword || p.code.includes(searchKeyword) || p.name.includes(searchKeyword)).map((p) => (
              <tr key={p.id} className="hover:bg-slate-50">
                <td className="px-6 py-4 font-mono text-slate-600">{p.code}</td>
                <td className="px-6 py-4 font-medium text-slate-900">{p.name}</td>
                <td className="px-6 py-4">
                  <span className={`px-2 py-1 rounded text-xs font-medium ${
                    p.partner_type === 'CUSTOMER' ? 'bg-blue-50 text-blue-700' :
                    p.partner_type === 'VENDOR' ? 'bg-purple-50 text-purple-700' : 'bg-slate-100 text-slate-700'
                  }`}>
                    {p.partner_type}
                  </span>
                </td>
              </tr>
            ))}
            {partners.length === 0 && (
              <tr>
                <td colSpan={3} className="px-6 py-8 text-center text-slate-500">暂无客商数据</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
