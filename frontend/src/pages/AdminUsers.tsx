import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from '../api/client';
import { Button, ErrorNotice, Loading, StatusBadge, Empty } from '../components/ui';
import { useAuth } from '../auth/store';

interface UserItem {
  id: string; username: string; email: string | null;
  displayName: string | null; isActive: boolean; roles: string[];
}

const ROLES = ['viewer', 'provider', 'admin'] as const;
const ROLE_LABELS: Record<string, string> = {
  viewer: '查看者', provider: '数据提供者', admin: '管理员',
};

type LoadState = 'loading' | 'ready' | 'error';

export default function AdminUsers(): JSX.Element {
  const { permissions } = useAuth();
  const [users, setUsers] = useState<UserItem[]>([]);
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [roleLoading, setRoleLoading] = useState<Record<string, boolean>>({});

  const canManage = permissions.includes('user:manage');

  const load = useCallback(async () => {
    setState('loading'); setError('');
    try {
      const data = await api<{ items: UserItem[] }>('/api/v1/users');
      setUsers(data.items ?? []);
      setState('ready');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '用户列表加载失败');
      setState('error');
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const toggleActive = async (userId: string, isActive: boolean) => {
    setActionError('');
    try {
      await api(`/api/v1/users/${userId}`, {
        method: 'PATCH',
        body: JSON.stringify({ isActive: !isActive }),
      });
      setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, isActive: !isActive } : u));
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : '操作失败');
    }
  };

  const assignRole = async (userId: string, roleCode: string) => {
    const key = `${userId}_+${roleCode}`;
    setRoleLoading((prev) => ({ ...prev, [key]: true })); setActionError('');
    try {
      await api(`/api/v1/users/${userId}/roles`, {
        method: 'POST',
        body: JSON.stringify({ roleCode }),
      });
      setUsers((prev) => prev.map((u) =>
        u.id === userId ? { ...u, roles: [...u.roles, roleCode] } : u,
      ));
    } catch (e) {
      if (e instanceof ApiError && e.code === 'CONFLICT') return;
      setActionError(e instanceof ApiError ? e.message : '角色分配失败');
    } finally {
      setRoleLoading((prev) => ({ ...prev, [key]: false }));
    }
  };

  const removeRole = async (userId: string, roleCode: string) => {
    const key = `${userId}_-${roleCode}`;
    setRoleLoading((prev) => ({ ...prev, [key]: true })); setActionError('');
    try {
      await api(`/api/v1/users/${userId}/roles/${roleCode}`, { method: 'DELETE' });
      setUsers((prev) => prev.map((u) =>
        u.id === userId ? { ...u, roles: u.roles.filter((r) => r !== roleCode) } : u,
      ));
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : '移除角色失败');
    } finally {
      setRoleLoading((prev) => ({ ...prev, [key]: false }));
    }
  };

  const isLoadingRole = (userId: string, roleCode: string, action: '+'|'-') =>
    roleLoading[`${userId}_${action}${roleCode}`] ?? false;

  if (!canManage) return <main className="stack"><ErrorNotice message="权限不足，需要 user:manage 权限。" /></main>;
  if (state === 'loading') return <main className="stack"><Loading label="正在加载用户列表…" /></main>;
  if (state === 'error') return (
    <main className="stack">
      <div className="page-heading"><div><h1>用户管理</h1><p>管理平台用户与角色权限。</p></div><Button variant="secondary" onClick={() => { void load(); }}>重试</Button></div>
      <ErrorNotice message={error} />
    </main>
  );

  return (
    <main className="stack">
      <div className="page-heading">
        <div><h1>用户管理</h1><p>管理平台用户与角色权限，共 {users.length} 人。</p></div>
        <Button variant="secondary" onClick={() => { void load(); }}>刷新</Button>
      </div>
      {actionError && <ErrorNotice message={actionError} />}
      {users.length === 0 ? (
        <Empty title="暂无用户" />
      ) : (
        <div className="card">
          <table className="data-table">
            <thead>
              <tr>
                <th>用户名</th>
                <th>邮箱</th>
                <th>角色</th>
                <th style={{ textAlign: 'right' }}>状态</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const missing = ROLES.filter((r) => !u.roles.includes(r));
                return (
                  <tr key={u.id}>
                    <td data-label="用户名">
                      <strong>{u.username}</strong>
                      {u.displayName && <span className="muted" style={{ marginLeft: 8 }}>{u.displayName}</span>}
                    </td>
                    <td data-label="邮箱">{u.email || '—'}</td>
                    <td data-label="角色" className="role-cell">
                      {u.roles.map((r) => (
                        <span className="role-tag" key={r}>
                          <StatusBadge value={r} />
                          <button
                            className="role-remove"
                            disabled={isLoadingRole(u.id, r, '-')}
                            title={`移除${ROLE_LABELS[r]}角色`}
                            aria-label={`移除${ROLE_LABELS[r]}角色`}
                            onClick={() => { void removeRole(u.id, r); }}
                          >
                            ×
                          </button>
                        </span>
                      ))}
                      {missing.map((r) => (
                        <button
                          className="role-add"
                          key={r}
                          disabled={isLoadingRole(u.id, r, '+')}
                          title={`添加${ROLE_LABELS[r]}角色`}
                          aria-label={`添加${ROLE_LABELS[r]}角色`}
                          onClick={() => { void assignRole(u.id, r); }}
                        >
                          +{ROLE_LABELS[r]}
                        </button>
                      ))}
                    </td>
                    <td data-label="状态" style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                      <StatusBadge value={u.isActive ? 'active' : 'inactive'} />
                      <Button
                        variant="ghost"
                        onClick={() => { void toggleActive(u.id, u.isActive); }}
                        style={{ marginLeft: 8 }}
                      >
                        {u.isActive ? '禁用' : '启用'}
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}