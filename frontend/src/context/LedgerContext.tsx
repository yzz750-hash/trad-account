'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { usePathname } from 'next/navigation';
import { apiFetch, setApiLedgerId, resetApiState } from '@/lib/api';
import type { Ledger } from '@/lib/types';

type LedgerContextType = {
  currentLedgerId: number | null;
  setCurrentLedgerId: (id: number) => void;
  currentLedger: Ledger | null;
  ledgers: Ledger[];
  ledgersLoaded: boolean;
  refreshLedgers: () => void;
  resetLedger: () => void;
};

const LedgerContext = createContext<LedgerContextType | undefined>(undefined);

export function LedgerProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [currentLedgerId, setCurrentLedgerIdState] = useState<number | null>(null);
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [ledgersLoaded, setLedgersLoaded] = useState(false);

  const refreshLedgers = useCallback(async () => {
    try {
      const data = await apiFetch('/api/v1/ledgers');
      setLedgers(data);
      if (data.length > 0) {
        const stored = localStorage.getItem('currentLedgerId');
        if (stored && data.find((l: Ledger) => l.id === parseInt(stored))) {
          setCurrentLedgerIdState(parseInt(stored));
          setApiLedgerId(parseInt(stored));
        } else {
          setCurrentLedgerIdState(data[0].id);
          setApiLedgerId(data[0].id);
          localStorage.setItem('currentLedgerId', data[0].id.toString());
        }
      }
    } catch (err) {
      console.error('Failed to fetch ledgers:', err);
    } finally {
      setLedgersLoaded(true);
    }
  }, []);

  useEffect(() => {
    // Skip on login page to avoid 401 → redirect loop
    if (typeof window !== 'undefined' && pathname === '/login') return;
    refreshLedgers();
  }, [refreshLedgers, pathname]);

  const handleSetLedgerId = useCallback((id: number) => {
    setCurrentLedgerIdState(id);
    setApiLedgerId(id);
    localStorage.setItem('currentLedgerId', id.toString());
  }, []);

  const resetLedger = useCallback(() => {
    setCurrentLedgerIdState(null);
    setLedgers([]);
    setLedgersLoaded(false);
    resetApiState();
  }, []);

  const currentLedger = useMemo(
    () => (currentLedgerId ? ledgers.find((l: Ledger) => l.id === currentLedgerId) ?? null : null),
    [currentLedgerId, ledgers]
  );

  // Sync initial ledger ID on mount
  useEffect(() => {
    if (currentLedgerId) {
      setApiLedgerId(currentLedgerId);
    }
  }, [currentLedgerId]);

  const value = useMemo<LedgerContextType>(() => ({
    currentLedgerId,
    setCurrentLedgerId: handleSetLedgerId,
    currentLedger,
    ledgers,
    ledgersLoaded,
    refreshLedgers,
    resetLedger,
  }), [currentLedgerId, handleSetLedgerId, currentLedger, ledgers, ledgersLoaded, refreshLedgers, resetLedger]);

  // Gate rendering on non-login pages until ledgers are loaded and a ledger is
  // selected. Without this, child pages fire apiFetch() in their mount effects
  // before setApiLedgerId() has run → requests go out without X-Ledger-Id →
  // backend rejects with 400 "X-Ledger-Id header is required".
  // Login page is exempt (no auth, no ledger needed).
  const isLogin = pathname === '/login';
  if (!isLogin && !ledgersLoaded) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[#F8F9FA]">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-2 border-slate-300 border-t-slate-600 rounded-full mx-auto mb-4" />
          <p className="text-slate-500 text-sm">正在加载账套…</p>
        </div>
      </div>
    );
  }
  // Ledgers loaded but none selected yet (e.g. user has no ledgers) — still render
  // so the dashboard can show the "create a ledger" prompt. Pages that require a
  // ledger should guard on currentLedgerId themselves.

  return (
    <LedgerContext.Provider value={value}>
      {children}
    </LedgerContext.Provider>
  );
}

export function useLedger() {
  const context = useContext(LedgerContext);
  if (context === undefined) {
    throw new Error('useLedger must be used within a LedgerProvider');
  }
  return context;
}
