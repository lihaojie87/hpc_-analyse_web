import { FormEvent, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import { useAuth, type AuthUser } from '../auth/store';
import AuthLayout from '../components/AuthLayout';
import { Button, ErrorNotice, InfoNotice, Input, SuccessNotice } from '../components/ui';

interface LoginResponse {
  accessToken: string;
  refreshToken?: string | null;
  user: AuthUser;
}

/** State handed over by the register page after a successful sign-up. */
interface LoginLocationState {
  registered?: boolean;
  username?: string;
}

interface LoginFieldErrors {
  username?: string;
  password?: string;
}

export default function Login(): JSX.Element {
  const location = useLocation();
  const navigate = useNavigate();
  const { setSession, sessionExpired } = useAuth();

  const handoff = (location.state as LoginLocationState | null) ?? null;
  const [username, setUsername] = useState(handoff?.username ?? '');
  const [password, setPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<LoginFieldErrors>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [success] = useState(handoff?.registered ? '注册成功，请使用新账户登录。' : '');
  // P2-1 fix: synchronous re-entrancy guard. `busy` is React state, so three
  // `requestSubmit()` calls in the SAME tick all observe `busy === false` and
  // each fire a request. A ref is written/read within the same tick, so only the
  // first call proceeds and the duplicate submissions collapse into one request.
  const submittingRef = useRef(false);

  /** Client-side validation; mirrors the fields the backend requires. */
  function validate(): boolean {
    const next: LoginFieldErrors = {};
    if (!username.trim()) next.username = '请输入用户名';
    if (!password) next.password = '请输入密码';
    setFieldErrors(next);
    return Object.keys(next).length === 0;
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submittingRef.current) return; // 同一 tick 内仅放行首次提交（同步判重）
    if (!validate()) return;
    submittingRef.current = true;
    setError('');
    setBusy(true);
    try {
      const data = await api<LoginResponse>('/api/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username: username.trim(), password }),
      });
      setSession({ accessToken: data.accessToken, refreshToken: data.refreshToken, user: data.user });
      navigate('/records', { replace: true });
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : '登录失败，请稍后重试。');
    } finally {
      submittingRef.current = false;
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="欢迎回来">
      <p className="auth-card-subtitle">登录后继续管理你的性能数据。</p>
      <form className="stack" onSubmit={submit} noValidate>
        {success && <SuccessNotice message={success} />}
        {!success && sessionExpired && <InfoNotice message="登录状态已失效，请重新登录。" />}
        {error && <ErrorNotice message={error} />}
        <Input
          label="用户名"
          required
          value={username}
          onChange={(event) => {
            setUsername(event.target.value);
            if (fieldErrors.username) setFieldErrors((prev) => ({ ...prev, username: undefined }));
          }}
          error={fieldErrors.username}
          autoComplete="username"
          placeholder="输入用户名"
          autoFocus
        />
        <Input
          label="密码"
          required
          type="password"
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
            if (fieldErrors.password) setFieldErrors((prev) => ({ ...prev, password: undefined }));
          }}
          error={fieldErrors.password}
          autoComplete="current-password"
          placeholder="输入密码"
        />
        <Button type="submit" disabled={busy} aria-busy={busy}>
          {busy ? '登录中…' : '登录'}
        </Button>
      </form>
      <p className="auth-switch">
        还没有账户？ <Link to="/register">创建账户</Link>
      </p>
    </AuthLayout>
  );
}
