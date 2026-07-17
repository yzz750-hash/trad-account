'use client';

import { useEffect, useState, useRef } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth';
import { API_BASE } from '@/lib/http-base';

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [authError, setAuthError] = useState(false);
  const [errorDetail, setErrorDetail] = useState<string>('');
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
      .catch((err) => {
        // Auth check failed (network error, etc) — show error state with details
        if (!cancelled) {
          setErrorDetail(`${err?.message || String(err)} | API_BASE=${API_BASE}`);
          setAuthError(true);
          setReady(true);
        }
      });

    return () => { cancelled = true; };
  }, [pathname, router]);

  if (authError) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[#F8F9FA]">
        <div className="text-center p-8 max-w-md">
          <div className="text-red-500 text-4xl mb-4">⚠</div>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">网络连接失败</h2>
          <p className="text-slate-500 text-sm mb-2">无法连接到服务器，请检查网络后重试。</p>
          <p className="text-red-400 text-xs mb-4 break-all font-mono">{errorDetail}</p>
          <button
            onClick={() => { checkedRef.current = false; setAuthError(false); setErrorDetail(''); setReady(false); }}
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
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-2 border-slate-300 border-t-slate-600 rounded-full mx-auto mb-4" />
          <p className="text-slate-500 text-sm">正在连接服务器…</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
