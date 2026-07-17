"use client";

import { useState, useEffect, useMemo } from "react";
import { apiFetch, errMsg } from "@/lib/api";
import { sum, d } from "@/lib/decimal";

interface Account {
  id: number;
  code: string;
  name: string;
  account_type: string;
  balance_direction: string;
  parent_id: number | null;
  opening_balance: number;
}

export default function AccountsSettingsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchInput, setSearchInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");

  // Debounce search input (300ms) to avoid O(n) filter on every keystroke
  useEffect(() => {
    const t = setTimeout(() => setSearchKeyword(searchInput.trim()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);
  const [trialBalanceResult, setTrialBalanceResult] = useState<{
    total_debit: number;
    total_credit: number;
    is_balanced: boolean;
    difference: number;
  } | null>(null);

  const [showAddModal, setShowAddModal] = useState(false);
  const [isTopLevel, setIsTopLevel] = useState(false);
  const [parentAccount, setParentAccount] = useState<Account | null>(null);
  const [newSubCode, setNewSubCode] = useState("01");
  const [newName, setNewName] = useState("");
  const [topLevelType, setTopLevelType] = useState("资产");
  const [topLevelDirection, setTopLevelDirection] = useState("借");
  const [addError, setAddError] = useState("");

  const [showEditModal, setShowEditModal] = useState(false);
  const [editAccount, setEditAccount] = useState<Account | null>(null);
  const [editName, setEditName] = useState("");
  const [editCode, setEditCode] = useState("");
  const [editError, setEditError] = useState("");

  const fetchAccounts = async () => {
    setLoading(true);
    try {
      const data = await apiFetch("/api/v1/accounts");
      setAccounts(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAccounts();
  }, []);

  // Step 1: Build hierarchy index only when accounts change (O(n²) once)
  const accountTree = useMemo(() => {
    const sorted = [...accounts].sort((a, b) => a.code.localeCompare(b.code));
    return sorted.map((acc) => {
      const isLeaf = !sorted.some(
        (child) => child.code.startsWith(acc.code) && child.code.length > acc.code.length
      );
      const depth = acc.code.length >= 4 ? (acc.code.length - 4) / 2 : 0;

      let computedBalance = d(acc.opening_balance).toNumber();
      if (!isLeaf) {
        const leafBalances = sorted
          .filter((child) => child.code.startsWith(acc.code) && child.code.length > acc.code.length)
          .filter((child) => !sorted.some(
            (grandchild) => grandchild.code.startsWith(child.code) && grandchild.code.length > child.code.length
          ))
          .map((leaf) => leaf.opening_balance);
        computedBalance = Number(sum(leafBalances));
      }

      return { ...acc, isLeaf, depth, computedBalance };
    });
  }, [accounts]);

  // Step 2: Keyword filter is O(n), applied to pre-built tree
  const enhancedAccounts = useMemo(() => {
    if (!searchKeyword) return accountTree;
    return accountTree.filter(
      a => a.code.includes(searchKeyword) || a.name.includes(searchKeyword)
    );
  }, [accountTree, searchKeyword]);

  const checkTrialBalance = async () => {
    try {
      const data = await apiFetch("/api/v1/accounts/trial-balance");
      setTrialBalanceResult(data);
    } catch (err) {
      console.error(err);
    }
  };

  const handleUpdateOpeningBalance = async (id: number, val: string) => {
    try {
      const numVal = parseFloat(val) || 0;
      await apiFetch(`/api/v1/accounts/${id}`, {
        method: "PUT",
        body: JSON.stringify({ opening_balance: numVal }),
      });
      await fetchAccounts();
    } catch (err: unknown) {
      console.error(err);
      alert(errMsg(err) || "更新期初余额失败");
    }
  };

  const openAddModal = (parent: Account) => {
    setParentAccount(parent);
    setIsTopLevel(false);
    const children = accounts.filter(a => a.code.startsWith(parent.code) && a.code.length === parent.code.length + 2);
    if (children.length > 0) {
      const maxCode = Math.max(...children.map(c => parseInt(c.code.slice(-2))));
      setNewSubCode((maxCode + 1).toString().padStart(2, '0'));
    } else {
      setNewSubCode("01");
    }
    setNewName("");
    setAddError("");
    setShowAddModal(true);
  };

  const openAddTopLevelModal = () => {
    setParentAccount(null);
    setIsTopLevel(true);
    setNewSubCode("");
    setNewName("");
    setTopLevelType("资产");
    setTopLevelDirection("借");
    setAddError("");
    setShowAddModal(true);
  };

  const submitAddAccount = async () => {
    if (!newSubCode || !newName) return;
    setAddError("");

    const payload: Record<string, unknown> = {
      code: isTopLevel ? newSubCode : parentAccount!.code + newSubCode,
      name: newName,
      opening_balance: 0.0
    };

    if (isTopLevel) {
      if (newSubCode.length !== 4) {
        setAddError("一级科目代码必须为4位数字");
        return;
      }
      payload.account_type = topLevelType;
      payload.balance_direction = topLevelDirection;
    } else {
      payload.parent_id = parentAccount!.id;
    }

    try {
      await apiFetch("/api/v1/accounts", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      setShowAddModal(false);
      await fetchAccounts();
    } catch (err: unknown) {
      setAddError(errMsg(err) || "创建失败");
    }
  };

  const openEditModal = (acc: Account) => {
    setEditAccount(acc);
    setEditName(acc.name);
    setEditCode(acc.code);
    setEditError("");
    setShowEditModal(true);
  };

  const submitEditAccount = async () => {
    if (!editAccount || !editName) return;
    setEditError("");
    const isSub = editAccount.parent_id != null;
    if (isSub && editCode && editCode.length < 6) {
      setEditError("二级/三级科目编码至少6位");
      return;
    }
    try {
      const body: Record<string, unknown> = { name: editName };
      if (isSub && editCode !== editAccount.code) {
        body.code = editCode;
      }
      await apiFetch(`/api/v1/accounts/${editAccount.id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      setShowEditModal(false);
      await fetchAccounts();
    } catch (err: unknown) {
      setEditError(errMsg(err) || "修改失败");
    }
  };

  const handleDeleteAccount = async (acc: Account) => {
    if (!window.confirm(`确认要删除科目【${acc.code} ${acc.name}】？\n提示：删除操作不可撤销。`)) return;
    try {
      await apiFetch(`/api/v1/accounts/${acc.id}`, {
        method: "DELETE"
      });
      await fetchAccounts();
    } catch (err: unknown) {
      alert(errMsg(err) || "删除失败");
    }
  };

  if (loading) return <div className="p-8 text-slate-500">正在加载科目...</div>;

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">科目与期初余额</h1>
          <p className="text-slate-500 mt-1">管理系统科目表并设置期初余额</p>
        </div>
        <div className="flex gap-4">
          <button
            onClick={openAddTopLevelModal}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors font-medium flex items-center gap-2 shadow-sm"
          >
            + 新增一级科目
          </button>
          <button
            onClick={checkTrialBalance}
            className="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent-light transition-colors font-medium flex items-center gap-2"
          >
            期初试算平衡
          </button>
        </div>
      </div>

      {trialBalanceResult && (
        <div className={`p-4 mb-6 rounded-lg border ${trialBalanceResult.is_balanced ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-red-50 border-red-200 text-red-800'}`}>
          <div className="font-bold flex items-center gap-2">
            {trialBalanceResult.is_balanced ? '✓ 试算平衡' : '✗ 试算不平衡'}
          </div>
          <div className="mt-2 text-sm flex gap-6">
            <span>借方合计: {trialBalanceResult.total_debit.toLocaleString('zh-CN', {style:'currency', currency:'CNY'})}</span>
            <span>贷方合计: {trialBalanceResult.total_credit.toLocaleString('zh-CN', {style:'currency', currency:'CNY'})}</span>
            {!trialBalanceResult.is_balanced && (
              <span className="font-bold">差额: {trialBalanceResult.difference.toLocaleString('zh-CN', {style:'currency', currency:'CNY'})}</span>
            )}
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
        <div className="p-4 border-b border-slate-100">
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索科目编码或名称..."
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 w-72"
          />
        </div>
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 font-medium">
            <tr>
              <th className="px-6 py-4 w-40">科目编码</th>
              <th className="px-6 py-4">科目名称</th>
              <th className="px-6 py-4 w-24 text-center">类型</th>
              <th className="px-6 py-4 w-24 text-center">方向</th>
              <th className="px-6 py-4 text-right w-48">期初余额</th>
              <th className="px-6 py-4 text-center w-56">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {enhancedAccounts.map((acc) => (
              <tr key={acc.id} className="hover:bg-slate-50 group">
                <td className="px-6 py-4 font-mono text-slate-600">
                  <div style={{ paddingLeft: `${acc.depth * 1.5}rem` }} className="flex items-center">
                    {acc.depth > 0 && <span className="text-slate-300 mr-2">├─</span>}
                    {acc.code}
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span className={acc.depth === 0 ? "font-bold text-slate-900" : "font-medium text-slate-700"}>
                    {acc.name}
                  </span>
                </td>
                <td className="px-6 py-4 text-center text-slate-500">{acc.account_type}</td>
                <td className="px-6 py-4 text-center">
                  <span className={`px-2 py-1 rounded text-xs font-medium ${acc.balance_direction === '借' ? 'bg-blue-50 text-blue-700' : 'bg-amber-50 text-amber-700'}`}>
                    {acc.balance_direction}
                  </span>
                </td>
                <td className="px-6 py-4 text-right">
                  {acc.isLeaf ? (
                    <input
                      type="number"
                      className="w-32 text-right border border-slate-300 rounded px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-slate-900 bg-white"
                      defaultValue={acc.computedBalance}
                      onBlur={(e) => handleUpdateOpeningBalance(acc.id, e.target.value)}
                    />
                  ) : (
                    <div className="w-32 text-right inline-block px-2 py-1.5 text-slate-500 bg-slate-50 border border-transparent cursor-not-allowed">
                      {acc.computedBalance.toFixed(2)}
                    </div>
                  )}
                </td>
                <td className="px-6 py-4 text-center">
                  <div className="flex justify-center gap-2">
                    <button
                      onClick={() => openEditModal(acc)}
                      className="text-slate-500 hover:text-slate-800 text-xs font-medium px-2 py-1 rounded hover:bg-slate-100 transition-colors"
                    >
                      编辑
                    </button>
                    <button
                      onClick={() => openAddModal(acc)}
                      className="text-indigo-600 hover:text-indigo-800 text-xs font-medium px-2 py-1 rounded hover:bg-indigo-50 transition-colors"
                    >
                      新增下级
                    </button>
                    <button
                      onClick={() => handleDeleteAccount(acc)}
                      className="text-red-500 hover:text-red-700 text-xs font-medium px-2 py-1 rounded hover:bg-red-50 transition-colors"
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50">
              <h2 className="text-lg font-bold text-slate-800">{isTopLevel ? '新增一级科目' : '新增下级科目'}</h2>
              <button onClick={() => setShowAddModal(false)} className="text-slate-400 hover:text-slate-600">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>

            <div className="p-6">
              {addError && <div className="mb-4 p-3 bg-red-50 text-red-700 text-sm rounded-lg">{addError}</div>}

              {isTopLevel ? (
                <>
                  <div className="mb-4">
                    <label className="block text-sm font-medium text-slate-700 mb-1">科目编码 (4位数字)</label>
                    <input
                      type="text"
                      maxLength={4}
                      value={newSubCode}
                      onChange={e => setNewSubCode(e.target.value.replace(/\D/g, ''))}
                      className="w-full border border-slate-300 rounded-lg px-3 py-2 font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      placeholder="e.g. 1001"
                    />
                  </div>
                  <div className="flex gap-4 mb-4">
                    <div className="flex-1">
                      <label className="block text-sm font-medium text-slate-700 mb-1">科目类型</label>
                      <select
                        value={topLevelType}
                        onChange={e => setTopLevelType(e.target.value)}
                        className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
                      >
                        <option value="资产">资产</option>
                        <option value="负债">负债</option>
                        <option value="所有者权益">所有者权益</option>
                        <option value="成本">成本</option>
                        <option value="收入">收入</option>
                      </select>
                    </div>
                    <div className="flex-1">
                      <label className="block text-sm font-medium text-slate-700 mb-1">余额方向</label>
                      <select
                        value={topLevelDirection}
                        onChange={e => setTopLevelDirection(e.target.value)}
                        className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
                      >
                        <option value="借">借 (Debit)</option>
                        <option value="贷">贷 (Credit)</option>
                      </select>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className="mb-4">
                    <label className="block text-sm font-medium text-slate-700 mb-1">上级科目</label>
                    <div className="px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-600 font-mono">
                      {parentAccount?.code} {parentAccount?.name}
                    </div>
                  </div>

                  <div className="mb-4">
                    <label className="block text-sm font-medium text-slate-700 mb-1">下级科目编号 (2位数字)</label>
                    <div className="flex items-center gap-2">
                      <span className="text-slate-500 font-mono bg-slate-50 px-3 py-2 border border-slate-200 rounded-lg">{parentAccount?.code}</span>
                      <span className="text-slate-400">-</span>
                      <input
                        type="text"
                        maxLength={2}
                        value={newSubCode}
                        onChange={e => setNewSubCode(e.target.value.replace(/\D/g, ''))}
                        className="flex-1 border border-slate-300 rounded-lg px-3 py-2 font-mono focus:outline-none focus:ring-2 focus:ring-slate-900"
                        placeholder="e.g. 01"
                      />
                    </div>
                  </div>
                </>
              )}

              <div className="mb-6">
                <label className="block text-sm font-medium text-slate-700 mb-1">科目名称</label>
                <input
                  type="text"
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  placeholder={isTopLevel ? "如：一级科目名称" : "下级科目名称"}
                />
              </div>

              <div className="flex gap-3 justify-end">
                <button onClick={() => setShowAddModal(false)} className="px-4 py-2 border border-slate-300 bg-white text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors">
                  取消
                </button>
                <button
                  onClick={submitAddAccount}
                  disabled={!newSubCode || !newName}
                  className="px-4 py-2 bg-accent text-white rounded-lg text-sm font-medium hover:bg-accent-light transition-colors disabled:opacity-50"
                >
                  确认创建
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showEditModal && editAccount && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50">
              <h2 className="text-lg font-bold text-slate-800">编辑科目</h2>
              <button onClick={() => setShowEditModal(false)} className="text-slate-400 hover:text-slate-600">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>

            <div className="p-6">
              {editError && <div className="mb-4 p-3 bg-red-50 text-red-700 text-sm rounded-lg">{editError}</div>}

              <div className="mb-4">
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  科目编码{editAccount.parent_id != null ? "" : " (一级科目不可修改)"}
                </label>
                {editAccount.parent_id != null ? (
                  <input
                    type="text"
                    value={editCode}
                    onChange={e => setEditCode(e.target.value.replace(/\D/g, ''))}
                    className="w-full border border-slate-300 rounded-lg px-3 py-2 font-mono focus:outline-none focus:ring-2 focus:ring-slate-900"
                  />
                ) : (
                  <div className="px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-600 font-mono">
                    {editAccount.code}
                  </div>
                )}
              </div>

              <div className="mb-6">
                <label className="block text-sm font-medium text-slate-700 mb-1">科目名称</label>
                <input
                  type="text"
                  value={editName}
                  onChange={e => setEditName(e.target.value)}
                  className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-900"
                  placeholder="新的科目名称"
                />
              </div>

              <div className="flex gap-3 justify-end">
                <button onClick={() => setShowEditModal(false)} className="px-4 py-2 border border-slate-300 bg-white text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors">
                  取消
                </button>
                <button
                  onClick={submitEditAccount}
                  disabled={!editName || (editName === editAccount.name && editCode === editAccount.code)}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50"
                >
                  保存修改
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
