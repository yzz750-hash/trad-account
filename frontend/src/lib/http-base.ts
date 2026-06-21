'use client';

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/** Low-level fetch with credentials. No auth headers, no 401 handling.
 *  Used by both auth.ts and api.ts to avoid circular dependencies. */
export async function baseFetch(path: string, options: RequestInit = {}): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: 'include',
  });
}
