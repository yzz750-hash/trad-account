"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { useLedger } from "@/context/LedgerContext";
import { d } from "@/lib/decimal";
import type { ChatActionPayload, ProcessedInvoice, ProcessedStatement, ReconcileMatch, InvoiceItem, BankTransaction, SuggestedVoucherEntry } from "@/lib/types";

// Empty string = relative paths. In dev, Next.js rewrites proxy /api/* to the
// FastAPI backend (see next.config.ts), so the browser issues same-origin
// requests and avoids CSP/CORS issues.
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

interface Message {
  id: string;
  text: string;
  sender: "user" | "ai";
  actionType?: string;
  actionPayload?: ChatActionPayload;
  isStreaming?: boolean;
  error?: string;
}

function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? match[1] : null;
}

function buildHeaders(currentLedgerId: number | null): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (currentLedgerId) headers["X-Ledger-Id"] = currentLedgerId.toString();
  const csrf = getCsrfToken();
  if (csrf) headers["X-CSRF-Token"] = csrf;
  return headers;
}

function generateId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

const CONV_ID_KEY = "ai_chat_conv_id";

export default function AIChat() {
  const { currentLedgerId } = useLedger();
  const [conversationId, setConversationId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      text: "你好！我是智能外贸财务助手 👋\n\n我可以帮你：\n📎 上传发票(PDF)或银行流水(CSV/Excel) — 自动识别并生成凭证\n💬 回答账务问题 — 如\"本月收入\"、\"科目余额\"\n🔍 核对银行流水与发票 — 自动匹配生成对账结果",
      sender: "ai",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<"ok" | "retrying" | "unavailable">("ok");
  const [selectedDocIds, setSelectedDocIds] = useState<Set<number>>(new Set());
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // -- Initialize conversation_id from localStorage --
  // Only the conversation_id (an opaque UUID) is persisted; chat messages
  // themselves are NOT, because they routinely contain financial data
  // (amounts, account codes, vendor names, voucher summaries) that would
  // linger in localStorage indefinitely and be readable by any script
  // running on the page (XSS) or anyone with disk access.
  useEffect(() => {
    const stored = localStorage.getItem(CONV_ID_KEY);
    const convId = stored || generateId();
    if (!stored) localStorage.setItem(CONV_ID_KEY, convId);
    setConversationId(convId);
  }, []);

  // NOTE: previous versions loaded and saved chat messages to localStorage
  // under `ai_chat_${conversationId}`. That code was removed because it
  // persisted financial data client-side. If conversation history is needed,
  // it should be fetched from a server-side endpoint with proper auth and
  // audit logging, not stored in the browser.

  // -- Auto-scroll --
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // -- Listen for open-ai-chat event from TopNav --
  useEffect(() => {
    const handler = () => setIsMinimized(false);
    window.addEventListener('open-ai-chat', handler);
    return () => window.removeEventListener('open-ai-chat', handler);
  }, []);

  const newConversation = useCallback(() => {
    abortRef.current?.abort();
    const newId = generateId();
    localStorage.setItem(CONV_ID_KEY, newId);
    setConversationId(newId);
    setMessages([
      {
        id: "welcome",
        text: "你好！我是智能外贸财务助手 👋\n\n我可以帮你：\n📎 上传发票(PDF)或银行流水(CSV/Excel) — 自动识别并生成凭证\n💬 回答账务问题 — 如\"本月收入\"、\"科目余额\"\n🔍 核对银行流水与发票 — 自动匹配生成对账结果",
        sender: "ai",
      },
    ]);
    setLoading(false);
    setConnectionStatus("ok");
  }, []);

  // -- SSE fetch with retry --
  const streamChat = useCallback(async (
    body: Record<string, unknown>,
    onToken: (text: string) => void,
    onMeta: (actionType: string, actionPayload: ChatActionPayload, text: string) => void,
    onError: (msg: string) => void,
    onDone: () => void,
  ) => {
    const controller = new AbortController();
    abortRef.current = controller;
    setConnectionStatus("ok");

    let retries = 0;
    const maxRetries = 2;

    while (retries <= maxRetries) {
      try {
        const res = await fetch(`${API_BASE}/api/v1/ai/chat`, {
          method: "POST",
          headers: buildHeaders(currentLedgerId),
          body: JSON.stringify(body),
          credentials: "include",
          signal: controller.signal,
        });

        if (!res.ok) {
          if (res.status === 401) {
            onError("认证已过期，请重新登录后再试。");
            return;
          }
          const errData = await res.json().catch(() => ({ detail: res.statusText }));
          onError(errData.detail || `HTTP ${res.status}`);
          return;
        }

        const reader = res.body?.getReader();
        if (!reader) { onError("无法读取响应流，请重试。"); return; }

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith("data: ")) continue;
            const data = trimmed.slice(6);
            if (data === "[DONE]") { onDone(); return; }

            try {
              const parsed = JSON.parse(data);
              if (parsed.type === "token") {
                onToken(parsed.text);
              } else if (parsed.type === "meta") {
                onMeta(parsed.action_type, parsed.action_payload, parsed.text || "");
              } else if (parsed.type === "error") {
                onError(parsed.text);
              }
            } catch { /* skip malformed JSON lines */ }
          }
        }
        // If we got through the loop without [DONE], consider it done
        onDone();
        return;
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") {
          onDone();
          return;
        }
        if (retries < maxRetries) {
          retries++;
          setConnectionStatus("retrying");
          await new Promise(r => setTimeout(r, 1000 * Math.pow(2, retries)));
          continue;
        }
        setConnectionStatus("unavailable");
        onError("网络连接失败，请检查网络后重试。如持续失败请联系管理员。");
        return;
      }
    }
  }, [currentLedgerId]);

  const handleSend = useCallback(async () => {
    if (!input.trim() || loading) return;

    const userMsg: Message = { id: generateId(), text: input, sender: "user" };
    const aiMsgId = generateId();
    const aiMsg: Message = { id: aiMsgId, text: "", sender: "ai", isStreaming: true };
    setMessages(prev => [...prev, userMsg, aiMsg]);
    setInput("");
    setLoading(true);

    const history = messages
      .filter(m => (m.sender === "user" || m.sender === "ai") && !m.isStreaming)
      .slice(-20)
      .map(m => ({ role: m.sender === "user" ? "user" : "assistant", content: m.text }));

    const body = {
      message: userMsg.text,
      conversation_id: conversationId,
      history,
    };

    await streamChat(
      body,
      // onToken
      (text) => {
        setMessages(prev => prev.map(m =>
          m.id === aiMsgId ? { ...m, text: m.text + text } : m
        ));
      },
      // onMeta
      (actionType, actionPayload, text) => {
        setMessages(prev => prev.map(m =>
          m.id === aiMsgId ? { ...m, isStreaming: false, text: text || m.text, actionType, actionPayload } : m
        ));
      },
      // onError
      (msg) => {
        setMessages(prev => prev.map(m =>
          m.id === aiMsgId ? { ...m, isStreaming: false, error: msg, text: msg } : m
        ));
      },
      // onDone
      () => {
        setMessages(prev => prev.map(m =>
          m.id === aiMsgId ? { ...m, isStreaming: false } : m
        ));
        setLoading(false);
        abortRef.current = null;
      },
    );
  }, [input, loading, messages, conversationId, streamChat, currentLedgerId]);

  const stopGeneration = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
    setMessages(prev => prev.map(m =>
      m.isStreaming ? { ...m, isStreaming: false } : m
    ));
  }, []);

  const retryLastMessage = useCallback(() => {
    setMessages(prev => {
      const lastUserIdx = [...prev].reverse().findIndex(m => m.sender === "user");
      if (lastUserIdx === -1) return prev;
      const actualIdx = prev.length - 1 - lastUserIdx;
      const lastUser = prev[actualIdx];
      // Remove last user + failed AI messages and resend
      const clean = prev.slice(0, actualIdx);
      setInput(lastUser.text);
      return clean;
    });
    setConnectionStatus("ok");
  }, []);

  // -- File upload --
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const files = Array.from(e.target.files);
    const filenames = files.map((f) => f.name).join(", ");
    setMessages((prev) => [...prev, { id: generateId(), text: `正在上传并识别文件：${filenames}`, sender: "user" }]);
    setLoading(true);

    const fname = files[0].name.toLowerCase();
    const isStatement = fname.endsWith(".csv") || fname.endsWith(".xlsx") || fname.endsWith(".xls") || fname.endsWith(".txt");
    const endpoint = isStatement ? "/api/v1/vouchers/upload-statements" : "/api/v1/vouchers/upload-invoices";

    try {
      const formData = new FormData();
      files.forEach((file) => formData.append("files", file));

      const headers: Record<string, string> = {};
      if (currentLedgerId) headers["X-Ledger-Id"] = currentLedgerId.toString();
      const csrf = getCsrfToken();
      if (csrf) headers["X-CSRF-Token"] = csrf;

      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers,
        credentials: "include",
        body: formData,
      });

      if (res.status === 401) {
        setMessages((prev) => [...prev, { id: generateId(), text: "认证已过期，请重新登录后再试。", sender: "ai" }]);
        return;
      }

      const data = await res.json();
      if (data.status === "success") {
        data.processed_files.forEach((pf: ProcessedInvoice | ProcessedStatement, index: number) => {
          if (pf.status === "success") {
            setMessages((prev) => [
              ...prev,
              {
                id: generateId(),
                text: isStatement ? "银行流水识别完成，请查看结果" : "发票识别完成，请查看结果",
                sender: "ai",
                actionType: isStatement ? "STATEMENT_RESULT" : "INVOICE_RESULT",
                actionPayload: pf,
              },
            ]);
          } else {
            setMessages((prev) => [
              ...prev,
              { id: generateId(), text: `文件 ${pf.filename} 处理失败：${pf.message}`, sender: "ai" },
            ]);
          }
        });
      } else {
        setMessages((prev) => [...prev, { id: generateId(), text: "文件上传处理失败，请重试", sender: "ai" }]);
      }
    } catch {
      setMessages((prev) => [...prev, { id: generateId(), text: "网络连接失败，请检查网络后重试", sender: "ai" }]);
    } finally {
      setLoading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleCreateSuggestedAccount = async (payload: ChatActionPayload) => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/accounts/`, {
        method: "POST",
        headers: buildHeaders(currentLedgerId),
        credentials: "include",
        body: JSON.stringify({
          code: payload.proposed_code,
          name: payload.new_account_name,
          parent_id: payload.parent_id,
          opening_balance: 0.0,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "未知错误" }));
        throw new Error(err.detail || "创建科目失败");
      }
      const data = await res.json();
      setMessages((prev) => [...prev, { id: generateId(), text: `✅ 已成功创建科目【${data.code} ${data.name}】。您现在可以在凭证录入时选择该科目，或继续让我帮您生成凭证。`, sender: "ai" }]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "未知错误";
      setMessages((prev) => [...prev, { id: generateId(), text: `科目创建失败：${msg}`, sender: "ai" }]);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateSuggestedVoucher = async (payload: ChatActionPayload) => {
    if (!payload.voucher_date || !payload.entries || payload.entries.length === 0) return;
    setLoading(true);
    try {
      const body = {
        voucher_date: payload.voucher_date,
        voucher_number: "AUTO",
        attachments_count: 0,
        entries: payload.entries.map((e) => ({
          account_code: e.account_code,
          summary: e.summary,
          direction: e.direction,
          amount: e.amount,
          currency_code: e.currency_code || "CNY",
        })),
      };
      const res = await fetch(`${API_BASE}/api/v1/vouchers`, {
        method: "POST",
        headers: buildHeaders(currentLedgerId),
        credentials: "include",
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "未知错误" }));
        throw new Error(err.detail || "创建凭证失败");
      }
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        { id: generateId(), text: `✅ 凭证已创建成功！凭证号：${data.voucher_number}`, sender: "ai" },
      ]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "未知错误";
      setMessages((prev) => [
        ...prev,
        { id: generateId(), text: `创建凭证失败：${msg}`, sender: "ai" },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateVoucher = async (docId: number, isStatement = false) => {
    setLoading(true);
    try {
      const endpoint = isStatement
        ? `/api/v1/vouchers/generate-from-statement/${docId}`
        : `/api/v1/vouchers/generate-from-doc/${docId}`;

      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: buildHeaders(currentLedgerId),
        credentials: "include",
      });
      if (!res.ok) throw new Error("凭证生成失败");
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        { id: generateId(), text: `✅ 凭证已生成！\n凭证字号：${data.voucher_number}\n分录数量：${data.entries?.length || 0} 条`, sender: "ai" },
      ]);
    } catch {
      setMessages((prev) => [...prev, { id: generateId(), text: "凭证生成失败，请确认科目设置完整且银行流水/发票数据无误后重试。", sender: "ai" }]);
    } finally {
      setLoading(false);
    }
  };

  const toggleDocSelection = (docId: number) => {
    setSelectedDocIds(prev => {
      const next = new Set(prev);
      if (next.has(docId)) { next.delete(docId); } else { next.add(docId); }
      return next;
    });
  };

  const clearDocSelection = () => setSelectedDocIds(new Set());

  const handleBatchGenerate = async () => {
    if (selectedDocIds.size === 0) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/vouchers/generate-from-docs`, {
        method: "POST",
        headers: buildHeaders(currentLedgerId),
        credentials: "include",
        body: JSON.stringify({ doc_ids: Array.from(selectedDocIds) }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "批量生成失败" }));
        throw new Error(err.detail || "批量生成失败");
      }
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        { id: generateId(), text: `批量凭证生成完成\n凭证字号：${data.voucher_number}\n分录数量：${data.entries?.length || 0} 条\n共处理了 ${selectedDocIds.size} 个单据`, sender: "ai" },
      ]);
      clearDocSelection();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "未知错误";
      setMessages((prev) => [...prev, { id: generateId(), text: `批量生成凭证失败：${msg}`, sender: "ai" }]);
    } finally {
      setLoading(false);
    }
  };

  const handleReconcile = async (match: ReconcileMatch) => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/vouchers/execute-reconciliation`, {
        method: "POST",
        headers: buildHeaders(currentLedgerId),
        credentials: "include",
        body: JSON.stringify(match),
      });
      if (!res.ok) throw new Error("对账执行失败");
      setMessages((prev) => [
        ...prev,
        { id: generateId(), text: "✅ 对账完成，系统已自动生成对应的银行收款/付款凭证，请查看。", sender: "ai" },
      ]);
    } catch {
      setMessages((prev) => [...prev, { id: generateId(), text: "对账执行失败，请确认数据完整后重试。", sender: "ai" }]);
    } finally {
      setLoading(false);
    }
  };

  const statusDot = connectionStatus === "ok"
    ? "bg-emerald-400"
    : connectionStatus === "retrying"
    ? "bg-amber-400 animate-pulse"
    : "bg-red-400";

  return (
    <div className={`print:hidden fixed bottom-6 right-6 w-96 flex flex-col ${isMinimized ? "h-auto" : "h-[500px]"} rounded-xl overflow-hidden shadow-elevated border border-slate-200 bg-white`}>
      {/* Header */}
      <div
        className="bg-gradient-to-r from-slate-900 to-slate-800 p-4 text-white flex justify-between items-center cursor-pointer select-none"
        onClick={() => setIsMinimized(!isMinimized)}
      >
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${statusDot}`}></div>
          <span className="font-semibold tracking-wide text-sm">智能 AI 财务助手</span>
        </div>
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            onClick={newConversation}
            className="text-white/50 hover:text-white hover:bg-white/10 transition-colors text-xs px-2 py-1 rounded mr-1"
            title="新建会话"
          >
            +新建会话
          </button>
          <button
            onClick={() => setIsMinimized(!isMinimized)}
            className="text-white/60 hover:text-white transition-colors"
            title={isMinimized ? "展开" : "收起"}
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              {isMinimized ? (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              )}
            </svg>
          </button>
        </div>
      </div>

      {!isMinimized && (
        <>
          {/* Chat History */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {selectedDocIds.size > 0 && (
              <div className="sticky top-0 z-10 bg-slate-900 text-white rounded-xl px-4 py-3 flex items-center justify-between shadow-lg mb-2">
                <span className="text-sm font-medium">已选择 {selectedDocIds.size} 个单据</span>
                <div className="flex gap-2">
                  <button
                    onClick={handleBatchGenerate}
                    disabled={loading}
                    className="bg-indigo-500 hover:bg-indigo-600 disabled:opacity-50 text-white text-sm font-medium px-4 py-1.5 rounded-lg transition-colors"
                  >
                    批量生成凭证
                  </button>
                  <button
                    onClick={clearDocSelection}
                    className="bg-white/10 hover:bg-white/20 text-white text-sm px-3 py-1.5 rounded-lg transition-colors"
                  >
                    取消全选
                  </button>
                </div>
              </div>
            )}
            {messages.map((msg) => (
              <div key={msg.id} className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm ${
                    msg.sender === "user"
                      ? "bg-slate-900 text-white rounded-br-sm"
                      : "bg-slate-50 text-slate-800 rounded-bl-sm border border-slate-200"
                  }`}
                >
                  {msg.text || (msg.isStreaming && <span className="inline-block w-2 h-4 bg-slate-400 animate-pulse rounded-sm align-middle"></span>)}

                  {msg.error && (
                    <div className="mt-2 flex gap-2">
                      <button onClick={retryLastMessage} className="text-xs bg-accent text-white px-3 py-1 rounded-lg hover:bg-accent-light transition-colors">重试</button>
                      <button onClick={newConversation} className="text-xs bg-white border border-slate-300 text-slate-600 px-3 py-1 rounded-lg hover:bg-slate-50 transition-colors">新建会话</button>
                    </div>
                  )}

                  {/* SUGGEST_ACCOUNT card */}
                  {msg.actionType === "SUGGEST_ACCOUNT" && msg.actionPayload && (
                    <div className="mt-3 p-3 bg-slate-50 rounded-xl border border-slate-200">
                      <div className="text-xs text-slate-500 mb-1">建议新增科目</div>
                      <div className="font-mono text-sm font-semibold text-slate-900">
                        {msg.actionPayload.proposed_code} - {msg.actionPayload.new_account_name}
                      </div>
                      <div className="text-xs text-slate-500 mt-1">上级科目：{msg.actionPayload.parent_name}</div>
                      <div className="mt-3 flex gap-2">
                        <button onClick={() => handleCreateSuggestedAccount(msg.actionPayload!)} className="flex-1 bg-accent text-white text-xs py-2 rounded-lg hover:bg-accent-light transition-colors">一键创建科目</button>
                        <button onClick={() => setInput("请帮我修改科目编码并创建")} className="flex-1 bg-white text-slate-600 text-xs py-2 rounded-lg border border-slate-200 hover:bg-slate-50 transition-colors">修改后创建</button>
                      </div>
                    </div>
                  )}

                  {/* SUGGEST_VOUCHER card */}
                  {msg.actionType === "SUGGEST_VOUCHER" && msg.actionPayload && (
                    <div className="mt-3 p-3 bg-emerald-50 rounded-xl border border-emerald-100">
                      <div className="text-xs text-emerald-600 mb-2 font-medium flex justify-between items-center">
                        <span>AI 生成的凭证建议</span>
                        <span className="bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded text-[10px]">待确认</span>
                      </div>
                      {/* 日期 */}
                      <div className="text-xs text-slate-500 mb-2">日期：{msg.actionPayload.voucher_date}</div>
                      {/* 分录表格 */}
                      <div className="bg-white rounded-lg overflow-hidden border border-slate-100">
                        <table className="w-full text-xs">
                          <thead className="bg-slate-50 text-slate-500">
                            <tr>
                              <th className="text-left px-2 py-1">科目</th>
                              <th className="text-left px-2 py-1">摘要</th>
                              <th className="text-right px-2 py-1">借方</th>
                              <th className="text-right px-2 py-1">贷方</th>
                            </tr>
                          </thead>
                          <tbody>
                            {msg.actionPayload.entries?.map((entry: SuggestedVoucherEntry, idx: number) => (
                              <tr key={idx} className="border-t border-slate-50">
                                <td className="px-2 py-1 font-mono">{entry.account_code}</td>
                                <td className="px-2 py-1">{entry.summary}</td>
                                <td className="px-2 py-1 text-right font-mono text-emerald-600">
                                  {entry.direction === "借" ? entry.amount : ""}
                                </td>
                                <td className="px-2 py-1 text-right font-mono text-red-500">
                                  {entry.direction === "贷" ? entry.amount : ""}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      {/* 确认按钮 */}
                      <div className="mt-3 flex gap-2">
                        <button
                          onClick={() => handleCreateSuggestedVoucher(msg.actionPayload!)}
                          disabled={loading}
                          className="flex-1 bg-accent text-white text-xs py-2 rounded-lg hover:bg-accent-light transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          {loading ? "创建中..." : "确认创建凭证"}
                        </button>
                        <button
                          onClick={() => setInput("请帮我修改凭证")}
                          className="flex-1 bg-white text-slate-600 text-xs py-2 rounded-lg border border-slate-200 hover:bg-slate-50 transition-colors"
                        >
                          修改
                        </button>
                      </div>
                    </div>
                  )}

                  {/* INVOICE_RESULT card */}
                  {msg.actionType === "INVOICE_RESULT" && msg.actionPayload && (
                    <div className={`mt-3 p-3 rounded-xl border transition-colors ${selectedDocIds.has(msg.actionPayload.doc_id!) ? 'bg-indigo-100 border-indigo-400 ring-2 ring-indigo-400/30' : 'bg-indigo-50 border-indigo-100'}`}>
                      <div className="text-xs text-indigo-500 mb-2 font-medium flex justify-between items-center">
                        <label className="flex items-center gap-2 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={selectedDocIds.has(msg.actionPayload!.doc_id!)}
                            onChange={() => toggleDocSelection(msg.actionPayload!.doc_id!)}
                            className="w-3.5 h-3.5 rounded border-indigo-300 text-indigo-600 focus:ring-indigo-500"
                          />
                          <span>勾选此发票用于批量生成凭证</span>
                        </label>
                        <span className="bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded text-[10px]">已识别</span>
                      </div>
                      <div className="text-xs text-slate-700 mb-2 font-medium border-b border-indigo-100 pb-1">供应商：{msg.actionPayload.vendor_name}</div>
                      {msg.actionPayload.doc_id && (
                        <button onClick={() => handleGenerateVoucher(msg.actionPayload!.doc_id!)} className="w-full mb-3 bg-indigo-600 text-white text-sm font-medium py-2.5 rounded-lg hover:bg-indigo-700 transition-colors shadow-md">
                          🎫 为此发票生成会计凭证
                        </button>
                      )}
                      <div className="space-y-2 mt-2">
                        {msg.actionPayload.items?.map((item: InvoiceItem, idx: number) => (
                          <div key={idx} className="bg-white p-2 rounded-lg text-xs shadow-sm border border-indigo-50">
                            <div className="font-semibold text-slate-800">{item.item_name}</div>
                            <div className="flex justify-between text-slate-500 mt-1">
                              <span>{item.specification || "默认规格"} x {item.quantity}</span>
                              <span className="font-mono text-indigo-600 font-semibold">¥{item.amount}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                      {msg.actionPayload.doc_id && (
                        <button onClick={() => handleGenerateVoucher(msg.actionPayload!.doc_id!)} className="w-full mt-3 bg-indigo-600 text-white text-xs py-2 rounded-lg hover:bg-indigo-700 transition-colors shadow-sm">🎫 为此发票生成会计凭证</button>
                      )}
                    </div>
                  )}

                  {/* STATEMENT_RESULT card */}
                  {msg.actionType === "STATEMENT_RESULT" && msg.actionPayload && (
                    <div className={`mt-3 p-3 rounded-xl border transition-colors ${selectedDocIds.has(msg.actionPayload.doc_id!) ? 'bg-emerald-100 border-emerald-400 ring-2 ring-emerald-400/30' : 'bg-emerald-50 border-emerald-100'}`}>
                      <div className="text-xs text-emerald-600 mb-2 font-medium flex justify-between items-center">
                        <label className="flex items-center gap-2 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={selectedDocIds.has(msg.actionPayload!.doc_id!)}
                            onChange={() => toggleDocSelection(msg.actionPayload!.doc_id!)}
                            className="w-3.5 h-3.5 rounded border-emerald-300 text-emerald-600 focus:ring-emerald-500"
                          />
                          <span>勾选此银行流水用于生成凭证</span>
                        </label>
                        <span className="bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded text-[10px]">已识别</span>
                      </div>
                      <div className="text-xs text-slate-700 mb-2 font-medium border-b border-emerald-100 pb-1">银行名称：{msg.actionPayload.bank_name || "未知银行"}</div>
                      {msg.actionPayload.doc_id && (
                        <button onClick={() => handleGenerateVoucher(msg.actionPayload!.doc_id!, true)} className="w-full mb-3 bg-emerald-600 text-white text-sm font-medium py-2.5 rounded-lg hover:bg-emerald-700 transition-colors shadow-md">
                          🎫 为此流水生成会计凭证
                        </button>
                      )}
                      <div className="space-y-2 mt-2 max-h-40 overflow-y-auto pr-1">
                        {msg.actionPayload.transactions?.map((txn: BankTransaction, idx: number) => (
                          <div key={idx} className="bg-white p-2 rounded-lg text-xs shadow-sm border border-emerald-50">
                            <div className="font-semibold text-slate-800">{txn.counterpart_name || "未知交易方"}</div>
                            <div className="flex justify-between text-slate-500 mt-1">
                              <span>{txn.transaction_date} | {txn.remarks}</span>
                              <span className={`font-mono font-semibold ${d(txn.amount).gt(0) ? "text-emerald-600" : "text-red-500"}`}>{d(txn.amount).gt(0) ? "+" : ""}{txn.amount}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                      {msg.actionPayload.doc_id && (
                        <button onClick={() => handleGenerateVoucher(msg.actionPayload!.doc_id!, true)} className="w-full mt-3 bg-emerald-600 text-white text-xs py-2 rounded-lg hover:bg-emerald-700 transition-colors shadow-sm">🎫 为此流水生成会计凭证</button>
                      )}
                    </div>
                  )}

                  {/* RECONCILE_SUGGESTIONS card */}
                  {msg.actionType === "RECONCILE_SUGGESTIONS" && msg.actionPayload && (
                    <div className="mt-3 p-3 bg-amber-50 rounded-xl border border-amber-100">
                      <div className="text-xs text-amber-600 mb-2 font-medium flex justify-between items-center">
                        <span>银行流水与发票对账匹配建议</span>
                        <span className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded text-[10px]">对账匹配</span>
                      </div>
                      <div className="space-y-3 mt-2 max-h-60 overflow-y-auto pr-1">
                        {msg.actionPayload.matches?.map((match: ReconcileMatch, idx: number) => (
                          <div key={idx} className="bg-white p-2 rounded-lg text-xs shadow-sm border border-amber-50">
                            <div className="flex gap-2">
                              <div className="flex-1 bg-slate-50 p-2 rounded border border-slate-100">
                                <div className="text-[10px] text-slate-400 mb-1">银行流水明细</div>
                                <div className="font-semibold text-emerald-600">ID: {match.statement_item_id}</div>
                              </div>
                              <div className="flex flex-col justify-center text-slate-400">
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" /></svg>
                              </div>
                              <div className="flex-1 bg-slate-50 p-2 rounded border border-slate-100">
                                <div className="text-[10px] text-slate-400 mb-1">发票进项明细</div>
                                <div className="font-semibold text-indigo-600">ID: {match.invoice_item_id}</div>
                              </div>
                            </div>
                            <div className="mt-2 text-[10px] text-slate-500 bg-amber-50/50 p-1.5 rounded"><span className="font-semibold">匹配依据：</span>{match.reason}</div>
                            {match.discrepancy_amount !== 0 && (
                              <div className="mt-1 flex justify-between items-center text-[10px] text-red-500 font-medium"><span>差额金额（{match.discrepancy_type === "bank_fee" ? "银行手续费" : "其他差异"}）：</span><span>¥{match.discrepancy_amount}</span></div>
                            )}
                            <button onClick={() => handleReconcile(match)} className="w-full mt-2 bg-accent text-white text-xs py-1.5 rounded hover:bg-accent-light transition-colors">🎫 为此匹配生成对账凭证</button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {loading && !messages.some(m => m.isStreaming) && (
              <div className="flex justify-start">
                <div className="bg-slate-50 rounded-2xl rounded-bl-sm px-4 py-3 text-sm shadow-sm border border-slate-200 flex gap-1">
                  <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce"></div>
                  <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "0.2s" }}></div>
                  <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "0.4s" }}></div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Area */}
          <div className="p-3 bg-white border-t border-slate-200">
            <div className="relative flex items-center gap-2">
              <input
                type="file" multiple accept="application/pdf,.csv,.xlsx,.xls,.txt"
                className="hidden" ref={fileInputRef} onChange={handleFileUpload}
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
                title="上传发票(PDF)或银行流水(CSV/Excel/TXT)"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
              </button>
              <div className="relative flex-1">
                <input
                  type="text" value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSend()}
                  placeholder="输入您的问题，如：帮我分析本月收入..."
                  className="w-full bg-white border border-slate-200 rounded-xl pl-4 pr-12 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/10 transition-shadow placeholder-slate-400"
                />
                {loading ? (
                  <button
                    onClick={stopGeneration}
                    className="absolute right-2 top-2 p-1.5 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors"
                    title="停止生成"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                  </button>
                ) : (
                  <button
                    onClick={handleSend} disabled={!input.trim()}
                    className="absolute right-2 top-2 p-1.5 bg-accent text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-800 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M12 5l7 7-7 7" /></svg>
                  </button>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
