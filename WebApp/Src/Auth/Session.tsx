import { PageStateProvider } from "./PageState";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { requestJson } from "../Api/Client";
import type { LoginResponse, Principal } from "../Api/Types";

const SESSION_KEY = "finsight.session.v1";
interface SavedSession { token: string; expiresAt: number }
function readSession(): SavedSession | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(SESSION_KEY) ?? "null") as SavedSession | null;
    if (value && typeof value.token === "string" && value.token.length > 0
      && Number.isFinite(value.expiresAt) && value.expiresAt > Date.now()) return value;
    sessionStorage.removeItem(SESSION_KEY);
  } catch { /* Invalid or unavailable tab storage means a fresh login. */ }
  return null;
}
function saveSession(value: SavedSession | null) {
  try {
    if (value) sessionStorage.setItem(SESSION_KEY, JSON.stringify(value));
    else sessionStorage.removeItem(SESSION_KEY);
  } catch { /* Login can still work with memory when browser storage is disabled. */ }
}
interface SessionValue {
  principal: Principal | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  request: <T>(path: `/api/${string}`, method: "GET" | "POST", body?: unknown,
    signal?: AbortSignal, onRequestId?: (requestId: string | null) => void) => Promise<T>;
}
const SessionContext = createContext<SessionValue | null>(null);
export function SessionProvider({ children }: { children: ReactNode }) {
  const [saved, setSaved] = useState(readSession);
  const [restoring, setRestoring] = useState(() => saved !== null);
  const [token, setToken] = useState<string | null>(null);
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const epoch = useRef(0);
  const logout = useCallback(() => {
    epoch.current += 1;
    saveSession(null); setSaved(null); setToken(null); setPrincipal(null); setRestoring(false);
  }, []);
  useEffect(() => {
    if (!saved) return;
    let cancelled = false;
    const startedEpoch = epoch.current;
    const controller = new AbortController();
    requestJson<Principal>("/api/v1/auth/me", "GET", { token: saved.token, signal: controller.signal })
      .then(resolved => {
        if (cancelled || epoch.current !== startedEpoch) return;
        if (!resolved.active || saved.expiresAt <= Date.now()) { logout(); return; }
        setToken(saved.token); setPrincipal(resolved);
      }).catch(() => { if (!cancelled && epoch.current === startedEpoch) logout(); })
      .finally(() => { if (!cancelled && epoch.current === startedEpoch) setRestoring(false); });
    return () => { cancelled = true; controller.abort(); };
    // Restore only the session present at application startup.
  }, []);
  useEffect(() => {
    if (!saved || !token) return;
    const timer = window.setTimeout(logout, Math.min(Math.max(0, saved.expiresAt - Date.now()), 2147483647));
    return () => window.clearTimeout(timer);
  }, [saved, token, logout]);
  const login = useCallback(async (email: string, password: string) => {
    const startedEpoch = ++epoch.current;
    const issued = await requestJson<LoginResponse>("/api/v1/auth/login", "POST", { body: { email, password } });
    const resolved = await requestJson<Principal>("/api/v1/auth/me", "GET", { token: issued.access_token });
    if (!resolved.active) throw new Error("账号不可用。");
    if (epoch.current !== startedEpoch) return;
    const record = { token: issued.access_token, expiresAt: Date.now() + issued.expires_in_seconds * 1000 };
    saveSession(record); setSaved(record); setToken(issued.access_token); setPrincipal(resolved);
  }, []);
  const request = useCallback(async <T,>(path: `/api/${string}`, method: "GET" | "POST",
    body?: unknown, signal?: AbortSignal, onRequestId?: (requestId: string | null) => void): Promise<T> => {
    if (!token) throw new Error("请先登录。");
    return requestJson<T>(path, method, { token, body, signal, onUnauthorized: logout, onRequestId });
  }, [token, logout]);
  return <SessionContext.Provider value={{ principal, token, login, logout, request }}>
    {restoring ? <p role="status">正在恢复登录状态…</p>
      : <PageStateProvider key={token ?? "anonymous"}>{children}</PageStateProvider>}
  </SessionContext.Provider>;
}
export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("SessionProvider 未挂载");
  return value;
}
