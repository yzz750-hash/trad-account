"use client";

import React, { useState } from "react";
import { useLedger } from "@/context/LedgerContext";
import { apiFetch, errMsg } from "@/lib/api";
import type { Ledger } from "@/lib/types";

export default function LedgersPage() {
  const { ledgers, refreshLedgers, currentLedgerId, setCurrentLedgerId } = useLedger();
  const [showModal, setShowModal] = useState(false);
  const [editingLedgerId, setEditingLedgerId] = useState<number | null>(null);
  const [formData, setFormData] = useState({
    name: "",
    company_name: "",
    base_currency: "CNY",
    start_year: new Date().getFullYear(),
    start_month: new Date().getMonth() + 1
  });

  const openCreateModal = () => {
    setEditingLedgerId(null);
    setFormData({
      name: "",
      company_name: "",
      base_currency: "CNY",
      start_year: new Date().getFullYear(),
      start_month: new Date().getMonth() + 1
    });
    setShowModal(true);
  };

  const openEditModal = (ledger: Ledger) => {
    setEditingLedgerId(ledger.id);
    setFormData({
      name: ledger.name,
      company_name: ledger.company_name || "",
      base_currency: ledger.base_currency,
      start_year: ledger.start_year,
      start_month: ledger.start_month
    });
    setShowModal(true);
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm("确定要删除此账套吗？删除后数据不可恢复！")) return;
    try {
      await apiFetch(`/api/v1/ledgers/${id}`, { method: "DELETE" });
      if (currentLedgerId === id) {
        setCurrentLedgerId(0);
      } else {
        await refreshLedgers();
      }
    } catch (err: unknown) {
      console.error(err);
      alert(`删除失败: ${errMsg(err)}`);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const isEditing = editingLedgerId !== null;
      const url = isEditing
        ? `/api/v1/ledgers/${editingLedgerId}`
        : "/api/v1/ledgers";

      const data = await apiFetch(url, {
        method: isEditing ? "PUT" : "POST",
        body: JSON.stringify(formData)
      });
      await refreshLedgers();
      setShowModal(false);
      setCurrentLedgerId(data.id);
    } catch (err: unknown) {
      console.error(err);
      alert(errMsg(err) || "网络错误");
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 min-h-full">
      <div className="flex justify-between items-center p-6 border-b border-slate-100">
        <div>
          <h1 className="text-xl font-bold text-slate-800">账套管理 (Ledger Management)</h1>
          <p className="text-sm text-slate-500 mt-1">创建和切换不同的会计账套，数据完全隔离</p>
        </div>
        <button 
          onClick={openCreateModal}
          className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg transition-colors font-medium text-sm"
        >
          新建账套
        </button>
      </div>

      <div className="p-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {ledgers.map(l => (
            <div 
              key={l.id} 
              className={`p-6 rounded-xl border-2 transition-all ${currentLedgerId === l.id ? 'border-indigo-600 bg-indigo-50/50' : 'border-slate-200 hover:border-indigo-300'}`}
            >
              <div className="flex justify-between items-start mb-4">
                <h3 className="font-bold text-lg text-slate-800">{l.name}</h3>
                {currentLedgerId === l.id && <span className="bg-indigo-100 text-indigo-700 text-xs px-2 py-1 rounded-full font-medium">当前</span>}
              </div>
              <div className="space-y-2 text-sm text-slate-600">
                <p>公司名称: {l.company_name || '未设置'}</p>
                <p>本位币: {l.base_currency}</p>
                <p>建账时间: {l.start_year}年{l.start_month}月</p>
              </div>
              <div className="mt-6 flex flex-col gap-2">
                {currentLedgerId !== l.id && (
                  <button 
                    onClick={() => setCurrentLedgerId(l.id)}
                    className="w-full py-2 bg-white border border-slate-200 hover:bg-slate-50 hover:text-indigo-600 rounded-lg text-sm font-medium transition-colors"
                  >
                    切换至此账套
                  </button>
                )}
                <div className="flex gap-2">
                  <button 
                    onClick={() => openEditModal(l)}
                    className="flex-1 py-2 bg-slate-50 text-slate-600 hover:bg-slate-100 rounded-lg text-sm font-medium transition-colors"
                  >
                    修改
                  </button>
                  <button 
                    onClick={() => handleDelete(l.id)}
                    className="flex-1 py-2 bg-red-50 text-red-600 hover:bg-red-100 rounded-lg text-sm font-medium transition-colors"
                  >
                    删除
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center">
          <div className="bg-white rounded-2xl w-full max-w-md shadow-xl overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
              <h2 className="font-bold text-lg">{editingLedgerId ? '修改账套' : '新建账套'}</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-slate-600 text-xl">&times;</button>
            </div>
            <form onSubmit={handleCreate} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">账套名称</label>
                <input required type="text" className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500" placeholder="例如：2026年深圳分公司账套" value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">公司全称</label>
                <input type="text" className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500" placeholder="用于打印凭证或报表抬头" value={formData.company_name} onChange={e => setFormData({...formData, company_name: e.target.value})} />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">本位币</label>
                <select disabled={editingLedgerId !== null} className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-slate-100 disabled:text-slate-400" value={formData.base_currency} onChange={e => setFormData({...formData, base_currency: e.target.value})}>
                  <option value="CNY">人民币 (CNY)</option>
                  <option value="USD">美元 (USD)</option>
                  <option value="EUR">欧元 (EUR)</option>
                  <option value="HKD">港币 (HKD)</option>
                </select>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">启用年份</label>
                  <input required disabled={editingLedgerId !== null} type="number" min="2000" max="2100" className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-slate-100 disabled:text-slate-400" value={formData.start_year} onChange={e => setFormData({...formData, start_year: Number(e.target.value)})} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">启用月份</label>
                  <input required disabled={editingLedgerId !== null} type="number" min="1" max="12" className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-slate-100 disabled:text-slate-400" value={formData.start_month} onChange={e => setFormData({...formData, start_month: Number(e.target.value)})} />
                </div>
              </div>
              <div className="pt-4 flex justify-end gap-3">
                <button type="button" onClick={() => setShowModal(false)} className="px-4 py-2 text-slate-600 hover:bg-slate-100 rounded-lg transition-colors">取消</button>
                <button type="submit" className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors">
                  {editingLedgerId ? '保存修改' : '立即创建'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
