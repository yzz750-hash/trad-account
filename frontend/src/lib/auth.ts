'use client';

import { baseFetch } from './http-base';

const USER_KEY = 'auth_user';

export interface AuthUser {
  id: number;
  username: string;
  role: string;
}

export function getToken(): string | null {
  return null; // token is now httpOnly cookie, not accessible from JS
}

export function setAuth(user: AuthUser): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export async function clearAuth(): Promise<void> {
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem('currentLedgerId');
  try {
    await baseFetch('/api/v1/auth/logout', { method: 'POST' });
  } catch {
    // best-effort logout
  }
}

export function getUser(): AuthUser | null {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function isAuthenticated(): Promise<boolean> {
  // 8s timeout: a dead backend should fail fast instead of making the user
  // stare at a spinner for the browser's default ~30s timeout.
  // Throws on network/timeout errors so the caller can distinguish "not logged
  // in" (returns false) from "server unreachable" (throws).
  const res = await baseFetch('/api/v1/auth/me', {}, 8000);
  if (res.ok) {
    const user = await res.json();
    setAuth(user);
    return true;
  }
  return false;
}
