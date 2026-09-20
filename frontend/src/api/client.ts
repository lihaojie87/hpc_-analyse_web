/**
 * Unified API client for the HPC Performance Platform frontend (UI-T02).
 *
 * Single source of truth for:
 *  - bearer-token injection (no page injects `Authorization` by hand any more);
 *  - translation of the backend error envelope into readable, *coded* errors so
 *    each caller can react to `error.code` instead of string matching;
 *  - notifying the auth layer whenever the backend reports an invalid session
 *    (HTTP 401) so the stale session is cleared and the user is sent back to /login.
 *
 * Backend envelope: `{ "error": { "code": string, "message": string, "requestId": string } }`
 * (see `backend/app/core/errors.py`).
 */

/** Error envelope returned by the FastAPI backend. */
export interface ApiErrorBody {
  code?: string;
  message?: string;
  requestId?: string;
}

/** Readable copy for every backend error code the UI may surface. */
const ERROR_MESSAGES: Record<string, string> = {
  VALIDATION_ERROR: '提交内容不符合要求，请检查后重试。',
  AUTH_REQUIRED: '登录状态已失效，请重新登录。',
  AUTH_INVALID_CREDENTIALS: '用户名或密码错误。',
  AUTH_TOKEN_EXPIRED: '登录状态已失效，请重新登录。',
  AUTH_TOKEN_INVALID: '登录凭证无效，请重新登录。',
  AUTH_TOKEN_REVOKED: '登录凭证已失效，请重新登录。',
  ACCOUNT_LOCKED: '账户已被锁定，请稍后再试或联系管理员。',
  RATE_LIMITED: '请求过于频繁，请稍后再试。',
  FORBIDDEN: '权限不足，无法执行该操作。',
  NOT_FOUND: '请求的资源不存在。',
  CONFLICT: '数据存在冲突，请刷新后重试。',
  USER_EXISTS: '用户名或邮箱已被注册。',
  WEAK_PASSWORD: '密码强度不足：至少 8 位，且需同时包含字母和数字。',
  PRECONDITION_REQUIRED: '缺少必要的版本标识，无法执行该操作。',
  PRECONDITION_FAILED: '记录已被其他用户修改，请重载最新数据后再保存。',
  INTERNAL_ERROR: '服务器内部错误，请稍后重试。',
  NETWORK_ERROR: '网络异常，无法连接到服务器，请检查网络后重试。',
  INVALID_RESPONSE: '服务器返回了无法解析的数据。',
};

/** Structured error thrown by {@link api}. Callers should branch on `code`. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;

  constructor(status: number, code: string, message: string, requestId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

/** Fallback token lookup: localStorage is where the auth layer persists the token. */
function readStoredToken(): string | null {
  try {
    return window.localStorage.getItem('token');
  } catch {
    return null;
  }
}

/**
 * Default token provider reads localStorage directly so that a request fired
 * before `AuthProvider` wires its handlers (child effects run before the parent
 * effect) still carries the persisted token.
 */
let tokenProvider: () => string | null = readStoredToken;
let unauthorizedHandler: () => void = () => undefined;

/** Wire the auth layer into the client (token lookup + 401 callback). */
export function configureApiAuth(handlers: {
  getToken?: () => string | null;
  onUnauthorized?: () => void;
}): void {
  if (handlers.getToken) tokenProvider = handlers.getToken;
  if (handlers.onUnauthorized) unauthorizedHandler = handlers.onUnauthorized;
}

/** Parse an error body defensively; never throw while parsing. */
async function parseErrorBody(response: Response): Promise<ApiErrorBody> {
  try {
    const data = (await response.json()) as { error?: ApiErrorBody } & ApiErrorBody;
    if (data && typeof data === 'object' && data.error && typeof data.error === 'object') {
      return data.error;
    }
    return data ?? {};
  } catch {
    return {};
  }
}

/** Known code → readable copy, else the server message, else a generic fallback. */
function readableMessage(code: string, fallback?: string): string {
  const known = ERROR_MESSAGES[code];
  if (known) return known;
  const trimmed = fallback?.trim();
  return trimmed ? trimmed : `请求失败（${code}）。`;
}

/**
 * Perform an authenticated JSON request against the platform API.
 *
 * @throws {ApiError} for any non-2xx response and for transport failures.
 */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const isFormData = typeof FormData !== 'undefined' && init.body instanceof FormData;
  if (init.body !== undefined && !isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const token = tokenProvider();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', readableMessage('NETWORK_ERROR'));
  }

  if (response.status === 401) {
    // Clear the invalid session first so any protected route immediately
    // redirects to /login; the caller still receives a readable ApiError.
    unauthorizedHandler();
  }

  if (!response.ok) {
    const body = await parseErrorBody(response);
    const code = body.code ?? `HTTP_${response.status}`;
    throw new ApiError(response.status, code, readableMessage(code, body.message), body.requestId);
  }

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(response.status, 'INVALID_RESPONSE', readableMessage('INVALID_RESPONSE'));
  }
}
