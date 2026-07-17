'use client';

// Empty string = relative paths. In dev, Next.js rewrites proxy /api/* to the
// FastAPI backend (see next.config.ts), so the browser issues same-origin
// requests and avoids CSP/CORS issues. Set NEXT_PUBLIC_API_URL only when you
// need to point at a different backend (e.g. deployed production).
export const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

/** Low-level fetch with credentials. No auth headers, no 401 handling.
 *  Used by both auth.ts and api.ts to avoid circular dependencies.
 *
 *  Pass `timeoutMs` to abort the request after N milliseconds (useful for the
 *  auth check so a dead backend doesn't leave the user staring at a spinner).
 */
export async function baseFetch(
  path: string,
  options: RequestInit = {},
  timeoutMs?: number,
): Promise<Response> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  if (timeoutMs && timeoutMs > 0) {
    timer = setTimeout(() => controller.abort(), timeoutMs);
  }
  try {
    return await fetch(`${API_BASE}${path}`, {
      ...options,
      credentials: 'include',
      signal: timeoutMs ? controller.signal : undefined,
    });
  } finally {
    if (timer) clearTimeout(timer);
  }
}
