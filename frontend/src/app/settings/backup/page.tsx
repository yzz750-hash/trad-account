"use client";

import { useState, useEffect, useRef } from "react";
import { apiFetch, errMsg } from "@/lib/api";

interface BackupInfo {
  id: string;
  filename: string;
  size_bytes: number;
  created_at: string;
  db_checksum: string;
}

function fmtSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fmtTime(iso: string) {
  try {
    return new Date(iso).toLocaleString("zh-CN");
  } catch {
    return iso;
  }
}

export default function BackupSettingsPage() {
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [restoring, setRestoring] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchBackups = async () => {
    setLoading(true);
    try {
      const data = await apiFetch<{ backups: BackupInfo[] }>("/api/v1/system/backups");
      setBackups(data.backups);
    } catch (err: unknown) {
      setMsg({ type: "err", text: errMsg(err) || "获取备份列表失败" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchBackups(); }, []);

  const showMsg = (type: "ok" | "err", text: string) => {
    setMsg({ type, text });
    setTimeout(() => setMsg(null), 5000);
  };

  const handleCreate = async () => {
    setCreating(true);
    try {
      await apiFetch("/api/v1/system/backups", { method: "POST" });
      showMsg("ok", "备份创建成功");
      await fetchBackups();
    } catch (err: unknown) {
      showMsg("err", errMsg(err) || "备份创建失败");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (b: BackupInfo) => {
    if (!confirm(`确定删除备份「${b.filename}」？此操作不可撤销。`)) return;
    try {
      await apiFetch(`/api/v1/system/backups/${b.id}`, { method: "DELETE" });
      showMsg("ok", "备份已删除");
      await fetchBackups();
    } catch (err: unknown) {
      showMsg("err", errMsg(err) || "删除失败");
    }
  };

  const handleDownload = (b: BackupInfo) => {
    window.open(`/api/v1/system/backups/${b.id}/download`, "_blank");
  };

  const handleRestore = async (b: BackupInfo) => {
    if (!confirm(`⚠️ 确定要恢复备份「${b.filename}」？\n当前数据将被替换，此操作不可撤销！`)) return;
    setRestoring(b.id);
    try {
      await apiFetch(`/api/v1/system/backups/${b.id}/restore`, {
        method: "POST",
        headers: { "X-Confirm-Restore": "I understand this will overwrite all current data" },
      });
      showMsg("ok", "备份恢复成功，请重新登录。");
      setTimeout(() => window.location.href = "/login", 2000);
    } catch (err: unknown) {
      showMsg("err", errMsg(err) || "恢复失败");
    } finally {
      setRestoring(null);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const formData = new FormData();
      formData.append("file", file);
      await apiFetch("/api/v1/system/backups/upload", {
        method: "POST",
        body: formData,
      });
      showMsg("ok", "备份文件已上传");
      await fetchBackups();
    } catch (err: unknown) {
      showMsg("err", errMsg(err) || "上传备份失败");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">数据备份与恢复</h1>
          <p className="text-slate-500 mt-1">管理系统数据库备份文件，支持创建、下载、上传和恢复</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => fileInputRef.current?.click()}
            className="px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors"
          >
            上传备份
          </button>
          <input ref={fileInputRef} type="file" accept=".zip" onChange={handleUpload} className="hidden" />
          <button
            onClick={handleCreate}
            disabled={creating}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50"
          >
            {creating ? "创建中..." : "+ 创建备份"}
          </button>
        </div>
      </div>

      {msg && (
        <div className={`mb-6 p-4 rounded-lg border text-sm ${msg.type === "ok" ? "bg-emerald-50 border-emerald-200 text-emerald-800" : "bg-red-50 border-red-200 text-red-700"}`}>
          {msg.text}
        </div>
      )}

      {loading ? (
        <div className="text-slate-500 text-center py-12">加载中...</div>
      ) : backups.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center text-slate-400">
          暂无备份文件，点击"创建备份"生成第一个数据库备份。
        </div>
      ) : (
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
          <table className="w-full text-sm text-left">
            <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 font-medium">
              <tr>
                <th className="px-6 py-4">备份文件</th>
                <th className="px-6 py-4 w-28">大小</th>
                <th className="px-6 py-4 w-48">创建时间</th>
                <th className="px-6 py-4 w-64">校验值</th>
                <th className="px-6 py-4 text-center w-72">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {backups.map((b) => (
                <tr key={b.id} className="hover:bg-slate-50">
                  <td className="px-6 py-4 font-mono text-slate-700">{b.filename}</td>
                  <td className="px-6 py-4 text-slate-500">{fmtSize(b.size_bytes)}</td>
                  <td className="px-6 py-4 text-slate-500">{fmtTime(b.created_at)}</td>
                  <td className="px-6 py-4 font-mono text-xs text-slate-400 truncate max-w-[16rem]" title={b.db_checksum}>
                    {b.db_checksum.slice(0, 16)}...
                  </td>
                  <td className="px-6 py-4 text-center">
                    <div className="flex justify-center gap-2">
                      <button
                        onClick={() => handleDownload(b)}
                        className="text-indigo-600 hover:text-indigo-800 text-xs font-medium px-2 py-1 rounded hover:bg-indigo-50 transition-colors"
                      >
                        下载
                      </button>
                      <button
                        onClick={() => handleRestore(b)}
                        disabled={restoring === b.id}
                        className="text-amber-600 hover:text-amber-800 text-xs font-medium px-2 py-1 rounded hover:bg-amber-50 transition-colors disabled:opacity-50"
                      >
                        {restoring === b.id ? "恢复中..." : "恢复"}
                      </button>
                      <button
                        onClick={() => handleDelete(b)}
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
      )}
    </div>
  );
}
