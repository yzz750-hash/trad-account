'use client';

import { useEffect, useState, useRef } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth';

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [authError, setAuthError] = useState(false);
  const checkedRef = useRef(false);

  useEffect(() => {
    // Skip auth for login page
    if (pathname === '/login') {
      setReady(true);
      return;
    }

    // Only check once per session (unless pathname changes to login and back)
    if (checkedRef.current) {
      setReady(true);
      return;
    }

    let cancelled = false;
    checkedRef.current = true;

    isAuthenticated()
      .then((ok) => {
        if (cancelled) return;
        if (!ok) {
          router.replace('/login');
        } else {
          setReady(true);
        }
      })
      .catch(() => {
        // Auth check failed (network error, etc) — show error state, not infinite spinner
        if (!cancelled) {
          setAuthError(true);
          setReady(true);
        }
      });

    return () => { cancelled = true; };
  }, [pathname, router]);

  if (authError) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[#F8F9FA]">
        <div className="text-center p-8">
          <div className="text-red-500 text-4xl mb-4">⚠</div>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">网络连接失败</h2>
          <p className="text-slate-500 text-sm mb-4">无法连接到服务器，请检查网络后重试。</p>
          <button
            onClick={() => { checkedRef.current = false; setAuthError(false); setReady(false); }}
            className="px-4 py-2 bg-slate-900 text-white rounded-lg hover:bg-slate-800 text-sm transition-colors"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[#F8F9FA]">
        <div className="animate-spin h-8 w-8 border-2 border-slate-300 border-t-slate-600 rounded-full" />
      </div>
    );
  }

  return <>{children}</>;
}
