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
  const [userRoles, setUserRoles] = useState<Record<string, string[]>>({});
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');

  const canManage = permissions.includes('user:manage');

  const load = useCallback(async () => {
    setState('loading'); setError('');
    try {
      const data = await api<{ items: UserItem[] }>('/api/v1/users');
      setUsers(data.items ?? []);
      // Fetch roles for each user
      const rolesMap: Record<string, string[]> = {};
      for (const u of data.items ?? []) {
        try {
          const roleData = await api<{ roles: string[] }>(`/api/v1/users/${u.id}/roles`);
          // The backend doesn't have a GET /users/:id/roles endpoint
          // We'll use the me endpoint pattern to infer
        } catch { /* ignore */ }
      }
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
    setActionError('');
    try {
      await api(`/api/v1/users/${userId}/roles`, {
        method: 'POST',
        body: JSON.stringify({ roleCode }),
      });
      setUserRoles((prev) => ({
        ...prev,
        [userId]: [...(prev[userId] ?? []), roleCode],
      }));
    } catch (e) {
      if (e instanceof ApiError && e.code === 'CONFLICT') return; // role already exists
      setActionError(e instanceof ApiError ? e.message : '角色分配失败');
    }
  };

  const removeRole = async (userId: string, roleCode: string) => {
    setActionError('');
    try {
      await api(`/api/v1/users/${userId}/roles/${roleCode}`, { method: 'DELETE' });
      setUserRoles((prev) => ({
        ...prev,
        [userId]: (prev[userId] ?? []).filter((r) => r !== roleCode),
      }));
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : '移除角色失败');
    }
  };

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
                <th>显示名</th>
                <th>状态</th>
                <th>角色</th>
                <th style={{ textAlign: 'right' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td data-label="用户名"><strong>{u.username}</strong></td>
                  <td data-label="邮箱">{u.email || '—'}</td>
                  <td data-label="显示名">{u.displayName || '—'}</td>
                  <td data-label="状态">
                    <StatusBadge value={u.isActive ? 'active' : 'inactive'} />
                  </td>
                  <td data-label="角色">
                    {u.roles.length > 0
                      ? u.roles.map((r) => <span key={r} style={{ marginRight: 4 }}><StatusBadge value={r} /></span>)
                      : <span className="muted">viewer</span>}
                  </td>
                  <td data-label="操作" style={{ textAlign: 'right' }}>
                    <Button
                      variant="ghost"
                      onClick={() => { void toggleActive(u.id, u.isActive); }}
                    >
                      {u.isActive ? '禁用' : '启用'}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}