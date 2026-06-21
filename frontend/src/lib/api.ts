'use client';

import { clearAuth } from './auth';
import { baseFetch } from './http-base';

let currentLedgerId: number | null = null;

export function setApiLedgerId(id: number | null) {
  currentLedgerId = id;
}

export function getApiLedgerId(): number | null {
  return currentLedgerId;
}

export function resetApiState(): void {
  currentLedgerId = null;
}

const DEFAULT_TIMEOUT_MS = 30_000; // 30 seconds
const CSRF_HEADER = 'X-CSRF-Token';

function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  // Parse all cookies and pick the csrf_token with the most specific (longest) path.
  // document.cookie returns cookies in order from most-specific-path to least-specific.
  const raw = document.cookie;
  let best: string | null = null;
  let idx = raw.indexOf('csrf_token=');
  while (idx !== -1) {
    const start = idx + 11; // 'csrf_token='.length
    const end = raw.indexOf(';', start);
    const value = end === -1 ? raw.slice(start) : raw.slice(start, end);
    if (value) {
      try { best = decodeURIComponent(value); } catch { best = value; }
      break; // First match is the most specific path ? good enough
    }
    idx = raw.indexOf('csrf_token=', idx + 1);
  }
  return best;
}

/** ponytail: tiny helper so every catch block doesn't repeat `instanceof Error` */
export function errMsg(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export async function apiFetch<T = any>(
  path: string,
  options: RequestInit & { timeout?: number } = {}
): Promise<T> {
  const headers: Record<string, string> = {};
  if (options.headers) {
    for (const [key, value] of Object.entries(options.headers)) {
      if (typeof value === 'string') headers[key] = value;
    }
  }
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  }

  if (currentLedgerId) {
    headers['X-Ledger-Id'] = currentLedgerId.toString();
  }

  const csrf = getCsrfToken();
  if (csrf) {
    headers[CSRF_HEADER] = csrf;
  }

  const timeout = options.timeout ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  try {
    const res = await baseFetch(path, {
      ...options,
      headers,
      signal: controller.signal,
    });

    if (res.status === 401) {
      clearAuth();
      if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
      throw new Error('Session expired. Please log in again.');
    }

    if (!res.ok) {
      const reqId = res.headers.get('X-Request-Id') || '';
      const errBody = await res.json().catch(() => ({ detail: res.statusText }));
      const msg = reqId
        ? `${errBody.detail || `HTTP ${res.status}`} [req: ${reqId}]`
        : (errBody.detail || `HTTP ${res.status}`);
      throw new Error(msg);
    }
    return res.json();
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeout}ms: ${path}`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** Download a file via GET with auth headers, returning a Blob. */
export async function apiDownload(path: string, timeout: number = 60_000): Promise<Blob> {
  const headers: Record<string, string> = {};
  if (currentLedgerId) {
    headers['X-Ledger-Id'] = currentLedgerId.toString();
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  try {
    const res = await baseFetch(path, {
      headers,
      signal: controller.signal,
    });

    if (res.status === 401) {
      clearAuth();
      if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
      throw new Error('Session expired. Please log in again.');
    }

    if (!res.ok) {
      const errBody = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(errBody.detail || `HTTP ${res.status}`);
    }
    return res.blob();
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error(`Download timed out after ${timeout}ms: ${path}`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
