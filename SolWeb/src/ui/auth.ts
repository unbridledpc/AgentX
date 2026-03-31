import { config } from "../config";

const AUTH_KEY = "solweb.auth.v1";

export type AuthState = { user: string; token: string; expiresAt: number; ts: number };

function isAuthState(value: unknown): value is AuthState {
  if (!value || typeof value !== "object") return false;
  const obj = value as Record<string, unknown>;
  return typeof obj.user === "string" && typeof obj.token === "string" && typeof obj.expiresAt === "number" && typeof obj.ts === "number";
}

function saveAuth(state: AuthState): void {
  localStorage.setItem(AUTH_KEY, JSON.stringify(state));
}

export function loadAuth(): AuthState | null {
  try {
    const raw = localStorage.getItem(AUTH_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!isAuthState(parsed)) return null;
    if (!parsed.user.trim() || !parsed.token.trim()) return null;
    if (parsed.expiresAt <= Date.now() / 1000) {
      localStorage.removeItem(AUTH_KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function clearAuth(): void {
  try {
    localStorage.removeItem(AUTH_KEY);
  } catch {
    // ignore
  }
}

export async function tryLogin(user: string, password: string): Promise<AuthState | null> {
  const res = await fetch(`${config.apiBase}/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: user, password }),
  });
  if (res.status === 401) return null;
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `HTTP ${res.status}`);
  }
  const payload = (await res.json()) as { user?: string; token?: string; expires_at?: number; ts?: number };
  const next: AuthState = {
    user: String(payload.user || "").trim(),
    token: String(payload.token || "").trim(),
    expiresAt: Number(payload.expires_at || 0),
    ts: Number(payload.ts || Date.now()),
  };
  if (!next.user || !next.token || !Number.isFinite(next.expiresAt) || next.expiresAt <= 0) {
    throw new Error("Authentication response was invalid.");
  }
  saveAuth(next);
  return next;
}

export async function logout(state?: AuthState | null): Promise<void> {
  const token = state?.token?.trim();
  clearAuth();
  if (!token) return;
  try {
    await fetch(`${config.apiBase}/v1/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    // ignore logout transport failures; local token is already gone
  }
}
