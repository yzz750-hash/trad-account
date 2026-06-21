"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useLedger } from "@/context/LedgerContext";
import { getUser, clearAuth, isAuthenticated } from "@/lib/auth";

export default function TopNav() {
  const pathname = usePathname() || "";
  const router = useRouter();
  const { ledgers, currentLedgerId, setCurrentLedgerId, resetLedger } = useLedger();
  const user = getUser();
  const [authenticated, setAuthenticated] = useState(false);

  useEffect(() => {
    let cancelled = false;
    isAuthenticated().then((ok) => {
      if (!cancelled) setAuthenticated(ok);
    });
    return () => { cancelled = true; };
  }, []);

  async function handleLogout() {
    resetLedger();
    await clearAuth();
    setAuthenticated(false);
    router.replace('/login');
  }

  return (
    <nav className="print:hidden h-16 border-b border-slate-200 bg-white/80 backdrop-blur-md sticky top-0 z-10 flex items-center justify-between px-8">
      <div className="flex items-center gap-8">
        <div className="font-bold text-xl tracking-tight">TradAcc.</div>
        {authenticated && (
          <div className="flex gap-6 text-sm font-medium text-slate-500">
            <Link href="/" className={`${pathname === '/' ? 'text-slate-900' : 'hover:text-slate-900'} cursor-pointer transition-colors`}>仪表盘</Link>
            <Link href="/voucher" className={`${pathname.startsWith('/voucher') ? 'text-slate-900' : 'hover:text-slate-900'} cursor-pointer transition-colors`}>凭证</Link>
            <Link href="/ledger/subsidiary" className={`${pathname === '/ledger/subsidiary' ? 'text-slate-900' : 'hover:text-slate-900'} cursor-pointer transition-colors`}>明细账</Link>
            <Link href="/ledger/balance" className={`${pathname === '/ledger/balance' ? 'text-slate-900' : 'hover:text-slate-900'} cursor-pointer transition-colors`}>科目余额表</Link>
            <Link href="/ledger/general" className={`${pathname === '/ledger/general' ? 'text-slate-900' : 'hover:text-slate-900'} cursor-pointer transition-colors`}>总账</Link>
            <Link href="/period-end" className={`${pathname.startsWith('/period-end') ? 'text-slate-900' : 'hover:text-slate-900'} cursor-pointer transition-colors`}>期末结转</Link>
            <Link href="/reports" className={`${pathname.startsWith('/reports') ? 'text-slate-900' : 'hover:text-slate-900'} cursor-pointer transition-colors`}>报表</Link>
            <Link href="/settings/accounts" className={`${pathname.startsWith('/settings') ? 'text-slate-900' : 'hover:text-slate-900'} cursor-pointer transition-colors`}>设置</Link>
          </div>
        )}
      </div>
      {authenticated ? (
        <div className="flex items-center gap-4 text-sm font-medium">
          <select
            value={currentLedgerId || ""}
            onChange={(e) => setCurrentLedgerId(Number(e.target.value))}
            className="px-3 py-1 bg-slate-100 rounded-lg text-slate-600 border border-slate-200 outline-none focus:ring-2 focus:ring-accent/20"
          >
            {ledgers.map(l => (
              <option key={l.id} value={l.id}>{l.name}</option>
            ))}
          </select>
          <button
            onClick={() => window.dispatchEvent(new CustomEvent('open-ai-chat'))}
            className="bg-accent text-white px-4 py-2 rounded-lg hover:bg-accent-light transition-colors"
          >
            智能凭证 (OCR)
          </button>
          <div className="flex items-center gap-3 pl-4 border-l border-slate-200">
            <span className="text-slate-600">
              <span className="font-medium text-slate-800">{user?.username}</span>
              <span className="ml-1 text-xs text-slate-400">({user?.role})</span>
            </span>
            <button
              onClick={handleLogout}
              className="text-slate-400 hover:text-red-600 transition-colors cursor-pointer"
              title="Logout"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M3 3a1 1 0 00-1 1v12a1 1 0 001 1h5a1 1 0 100-2H4V5h4a1 1 0 100-2H3zm11.707 3.293a1 1 0 010 1.414L12.414 10l2.293 2.293a1 1 0 01-1.414 1.414l-3-3a1 1 0 010-1.414l3-3a1 1 0 011.414 0z" clipRule="evenodd" />
                <path fillRule="evenodd" d="M16 10a1 1 0 00-1-1H8a1 1 0 100 2h7a1 1 0 001-1z" clipRule="evenodd" />
              </svg>
            </button>
          </div>
        </div>
      ) : null}
    </nav>
  );
}
