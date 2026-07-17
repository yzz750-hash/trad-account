'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
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
    if (typeof window !== 'undefined' && window.location.pathname === '/login') return;
    refreshLedgers();
  }, [refreshLedgers]);

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
