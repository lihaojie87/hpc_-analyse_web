import { FormEvent, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import AuthLayout from '../components/AuthLayout';
import { Button, ErrorNotice, Input } from '../components/ui';

interface RegisterFieldErrors {
  username?: string;
  email?: string;
  password?: string;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function Register(): JSX.Element {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<RegisterFieldErrors>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  // Synchronous re-entrancy guard (same class of fix as Login's P2-1): a ref is
  // written/read within the same tick, so same-tick duplicate submits collapse
  // into a single request instead of relying on the async `busy` state.
  const submittingRef = useRef(false);

  /** Client-side validation mirroring `RegisterIn` and the WEAK_PASSWORD rule. */
  function validate(): boolean {
    const next: RegisterFieldErrors = {};
    const trimmedUsername = username.trim();
    if (!trimmedUsername) next.username = '请输入用户名';
    else if (trimmedUsername.length < 3) next.username = '用户名至少 3 个字符';
    else if (trimmedUsername.length > 64) next.username = '用户名不能超过 64 个字符';

    const trimmedEmail = email.trim();
    if (trimmedEmail && !EMAIL_PATTERN.test(trimmedEmail)) next.email = '请输入有效的邮箱地址';

    if (!password) next.password = '请输入密码';
    else if (password.length < 8 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) {
      next.password = '密码至少 8 位，且需同时包含字母和数字';
    }

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
      await api('/api/v1/auth/register', {
        method: 'POST',
        body: JSON.stringify({ username: username.trim(), password, email: email.trim() || undefined }),
      });
      // 明确反馈 + 进入登录流程：跳转到登录页并携带成功提示与预填用户名。
      navigate('/login', { replace: true, state: { registered: true, username: username.trim() } });
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        // Convergence (P3-1): render each backend error in exactly ONE place.
        // Field-scoped errors go to the field only; everything else to the top notice.
        if (requestError.code === 'WEAK_PASSWORD') {
          setFieldErrors((prev) => ({ ...prev, password: requestError.message }));
        } else if (requestError.code === 'USER_EXISTS') {
          setFieldErrors((prev) => ({ ...prev, username: requestError.message }));
        } else {
          setError(requestError.message);
        }
      } else {
        setError('注册失败，请稍后重试。');
      }
    } finally {
      submittingRef.current = false;
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="创建账户">
      <p className="auth-card-subtitle">建立你的 HPC 性能数据工作空间。</p>
      <form className="stack" onSubmit={submit} noValidate>
        {error && <ErrorNotice message={error} />}
        <Input
          label="用户名"
          required
          minLength={3}
          value={username}
          onChange={(event) => {
            setUsername(event.target.value);
            if (fieldErrors.username) setFieldErrors((prev) => ({ ...prev, username: undefined }));
          }}
          error={fieldErrors.username}
          autoComplete="username"
          placeholder="至少 3 个字符"
          autoFocus
        />
        <Input
          label="邮箱（可选）"
          type="email"
          value={email}
          onChange={(event) => {
            setEmail(event.target.value);
            if (fieldErrors.email) setFieldErrors((prev) => ({ ...prev, email: undefined }));
          }}
          error={fieldErrors.email}
          autoComplete="email"
          placeholder="name@company.com"
        />
        <Input
          label="密码"
          required
          minLength={8}
          type="password"
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
            if (fieldErrors.password) setFieldErrors((prev) => ({ ...prev, password: undefined }));
          }}
          error={fieldErrors.password}
          autoComplete="new-password"
          hint="至少 8 位，包含字母和数字"
          placeholder="设置登录密码"
        />
        <Button type="submit" disabled={busy} aria-busy={busy}>
          {busy ? '创建中…' : '创建账户'}
        </Button>
      </form>
      <p className="auth-switch">
        已有账户？ <Link to="/login">返回登录</Link>
      </p>
    </AuthLayout>
  );
}
