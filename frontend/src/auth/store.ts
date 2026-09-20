import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react';
import { api, configureApiAuth } from '../api/client';

/** Current authenticated user, including the role/permission snapshot from the backend. */
export interface AuthUser {
  id: string;
  username: string;
  email?: string | null;
  displayName?: string | null;
  roles: string[];
  permissions: string[];
}

/** Session payload returned by `POST /api/v1/auth/login` and `POST /api/v1/auth/register`. */
export interface AuthSession {
  accessToken: string;
  refreshToken?: string | null;
  user: AuthUser;
}

export interface AuthState {
  token: string | null;
  user: AuthUser | null;
  roles: string[];
  permissions: string[];
  /** True when the session was invalidated by the backend (HTTP 401). */
  sessionExpired: boolean;
  setSession: (session: AuthSession) => void;
  clearSession: () => void;
  logout: () => Promise<void>;
  acknowledgeSessionNotice: () => void;
  /**
   * UX-only permission check. The backend remains the authority: every route
   * re-validates the permission code server-side, so hiding a button here is a
   * convenience, never an access-control decision.
   */
  hasPermission: (code: string) => boolean;
}

const TOKEN_KEY = 'token';
const REFRESH_KEY = 'refreshToken';
const USER_KEY = 'auth.user';

const noop = (): void => undefined;

function readStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function readStoredUser(): AuthUser | null {
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AuthUser> | null;
    if (!parsed || typeof parsed.username !== 'string') return null;
    return {
      id: typeof parsed.id === 'string' ? parsed.id : '',
      username: parsed.username,
      email: parsed.email ?? null,
      displayName: parsed.displayName ?? null,
      roles: Array.isArray(parsed.roles) ? parsed.roles : [],
      permissions: Array.isArray(parsed.permissions) ? parsed.permissions : [],
    };
  } catch {
    return null;
  }
}

/** Normalise a loosely-typed `/auth/me` or login response into an {@link AuthUser}. */
function normalizeUser(source: Partial<AuthUser>): AuthUser {
  return {
    id: typeof source.id === 'string' ? source.id : '',
    username: typeof source.username === 'string' ? source.username : '',
    email: source.email ?? null,
    displayName: source.displayName ?? null,
    roles: Array.isArray(source.roles) ? source.roles : [],
    permissions: Array.isArray(source.permissions) ? source.permissions : [],
  };
}

const AuthContext = createContext<AuthState>({
  token: null,
  user: null,
  roles: [],
  permissions: [],
  sessionExpired: false,
  setSession: noop,
  clearSession: noop,
  logout: async (): Promise<void> => undefined,
  acknowledgeSessionNotice: noop,
  hasPermission: () => false,
});

export function AuthProvider({ children }: { children: ReactNode }): ReactElement {
  const [token, setTokenState] = useState<string | null>(() => readStoredToken());
  const [user, setUser] = useState<AuthUser | null>(() => readStoredUser());
  const [sessionExpired, setSessionExpired] = useState<boolean>(false);

  // Keep the latest token reachable from stable callbacks (no stale closures).
  const tokenRef = useRef<string | null>(token);
  tokenRef.current = token;

  const persist = useCallback((session: AuthSession | null): void => {
    try {
      if (session) {
        window.localStorage.setItem(TOKEN_KEY, session.accessToken);
        if (session.refreshToken) window.localStorage.setItem(REFRESH_KEY, session.refreshToken);
        window.localStorage.setItem(USER_KEY, JSON.stringify(session.user));
      } else {
        window.localStorage.removeItem(TOKEN_KEY);
        window.localStorage.removeItem(REFRESH_KEY);
        window.localStorage.removeItem(USER_KEY);
      }
    } catch {
      // Storage unavailable (private mode): keep the session in memory only.
    }
  }, []);

  const clearSession = useCallback((): void => {
    persist(null);
    setTokenState(null);
    setUser(null);
  }, [persist]);

  const setSession = useCallback((session: AuthSession): void => {
    persist(session);
    setTokenState(session.accessToken);
    setUser(session.user);
    setSessionExpired(false);
  }, [persist]);

  const acknowledgeSessionNotice = useCallback((): void => setSessionExpired(false), []);

  const logout = useCallback(async (): Promise<void> => {
    let refreshToken: string | null = null;
    try {
      refreshToken = window.localStorage.getItem(REFRESH_KEY);
    } catch {
      refreshToken = null;
    }
    if (refreshToken && tokenRef.current) {
      try {
        await api('/api/v1/auth/logout', { method: 'POST', body: JSON.stringify({ refreshToken }) });
      } catch {
        // Best effort: the local session is cleared regardless of the outcome.
      }
    }
    clearSession();
  }, [clearSession]);

  const hasPermission = useCallback(
    (code: string): boolean => Boolean(user?.permissions.includes(code)),
    [user],
  );

  // Wire the unified API client: token lookup + 401 handling.
  useEffect(() => {
    configureApiAuth({
      getToken: () => tokenRef.current,
      onUnauthorized: () => {
        if (tokenRef.current) {
          setSessionExpired(true);
          clearSession();
        }
      },
    });
  }, [clearSession]);

  // Refresh roles/permissions from the backend on load so the UI never trusts a
  // stale localStorage snapshot. A 401 here clears the session via the handler above.
  useEffect(() => {
    if (!token) return undefined;
    let cancelled = false;
    api<Partial<AuthUser>>('/api/v1/auth/me')
      .then((me) => {
        if (cancelled) return;
        const normalized = normalizeUser(me);
        setUser(normalized);
        try {
          window.localStorage.setItem(USER_KEY, JSON.stringify(normalized));
        } catch {
          // ignore persistence failure
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [token]);

  const value = useMemo<AuthState>(
    () => ({
      token,
      user,
      roles: user?.roles ?? [],
      permissions: user?.permissions ?? [],
      sessionExpired,
      setSession,
      clearSession,
      logout,
      acknowledgeSessionNotice,
      hasPermission,
    }),
    [token, user, sessionExpired, setSession, clearSession, logout, acknowledgeSessionNotice, hasPermission],
  );

  return createElement(AuthContext.Provider, { value }, children);
}

export const useAuth = (): AuthState => useContext(AuthContext);
