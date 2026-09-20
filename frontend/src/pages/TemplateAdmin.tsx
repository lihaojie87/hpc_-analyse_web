import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from '../api/client';
import { useAuth } from '../auth/store';
import { Button, ErrorNotice, Loading, StatusBadge, Empty, Input, InfoNotice, SuccessNotice } from '../components/ui';

interface TemplateItem {
  id: string; code: string; name: string; status: string; revision: number;
}
interface VersionItem {
  id: string; versionNo: number; status: string; revision: number;
}
interface TemplateList { items: TemplateItem[]; }

type LoadState = 'loading' | 'ready' | 'error';

export default function TemplateAdmin(): JSX.Element {
  const { permissions } = useAuth();
  const canManage = permissions.includes('template:manage');
  const canRead = canManage || permissions.includes('template:read');

  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState('');
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [loading, setLoading] = useState<string | null>(null);

  // create form
  const [showCreate, setShowCreate] = useState(false);
  const [newCode, setNewCode] = useState('');
  const [newName, setNewName] = useState('');

  // expanded template → versions
  const [expanded, setExpanded] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, VersionItem[]>>({});

  const load = useCallback(async () => {
    setState('loading'); setError('');
    try {
      const data = await api<TemplateList>('/api/v1/templates');
      setTemplates(data.items ?? []);
      setState('ready');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '加载失败');
      setState('error');
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const loadVersions = async (templateId: string) => {
    try {
      const data = await api<VersionItem[]>(`/api/v1/templates/${templateId}/versions`);
      setVersions((prev) => ({ ...prev, [templateId]: data }));
    } catch (e) {
      setMessage({ tone: 'error', text: e instanceof ApiError ? e.message : '加载版本失败' });
    }
  };

  const toggleExpand = (id: string) => {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    if (!versions[id]) void loadVersions(id);
  };

  const createTemplate = async () => {
    if (!newCode.trim() || !newName.trim()) { setMessage({ tone: 'error', text: '代码和名称不能为空' }); return; }
    setLoading('create'); setMessage(null);
    try {
      await api('/api/v1/templates', { method: 'POST', body: JSON.stringify({ code: newCode.trim(), name: newName.trim() }) });
      setNewCode(''); setNewName(''); setShowCreate(false);
      setMessage({ tone: 'ok', text: `模板 "${newName.trim()}" 已创建` });
      await load();
    } catch (e) { setMessage({ tone: 'error', text: e instanceof ApiError ? e.message : '创建失败' }); }
    finally { setLoading(null); }
  };

  const createVersion = async (templateId: string) => {
    const label = window.prompt('版本标签（如 v2、v3）:');
    if (!label?.trim()) return;
    setLoading(`ver-${templateId}`); setMessage(null);
    try { await api(`/api/v1/templates/${templateId}/versions`, { method: 'POST', body: JSON.stringify({ versionLabel: label.trim() }) });
      setMessage({ tone: 'ok', text: `版本 ${label.trim()} 已创建` });
      void loadVersions(templateId);
    } catch (e) { setMessage({ tone: 'error', text: e instanceof ApiError ? e.message : '创建版本失败' }); }
    finally { setLoading(null); }
  };

  const publishVersion = async (versionId: string, label: string) => {
    if (!window.confirm(`确认发布版本 ${label}？发布后不可撤销。`)) return;
    setLoading(`pub-${versionId}`); setMessage(null);
    try { await api(`/api/v1/templates/versions/${versionId}/publish`, { method: 'POST' });
      setMessage({ tone: 'ok', text: `版本 ${label} 已发布` });
      await load();
      const tid = Object.keys(versions).find((k) => versions[k].some((v) => v.id === versionId));
      if (tid) void loadVersions(tid);
    } catch (e) { setMessage({ tone: 'error', text: e instanceof ApiError ? e.message : '发布失败' }); }
    finally { setLoading(null); }
  };

  if (!canRead) return <main className="stack"><ErrorNotice message="权限不足，需要 template:read 或 template:manage 权限。" /></main>;
  if (state === 'loading') return <main className="stack"><Loading label="正在加载模板列表…" /></main>;
  if (state === 'error') return (
    <main className="stack">
      <div className="page-heading"><div><h1>模板管理</h1><p>管理数据模板与版本发布。</p></div><Button variant="secondary" onClick={() => { void load(); }}>重试</Button></div>
      <ErrorNotice message={error} />
    </main>
  );

  return (
    <main className="stack">
      <div className="page-heading">
        <div><h1>模板管理</h1><p>管理数据模板与版本发布，共 {templates.length} 个模板。</p></div>
        <div className="heading-actions">
          {canManage && <Button variant="primary" onClick={() => setShowCreate((v) => !v)}>{showCreate ? '取消' : '新建模板'}</Button>}
          <Button variant="secondary" onClick={() => { void load(); }}>刷新</Button>
        </div>
      </div>

      {message?.tone === 'ok' && <SuccessNotice message={message.text} />}
      {message?.tone === 'error' && <ErrorNotice message={message.text} />}

      {canManage && showCreate && (
        <div className="card" style={{ display: 'grid', gap: 12 }}>
          <h2 className="card-title">新建模板</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 10, alignItems: 'end' }}>
            <Input label="代码（唯一标识）" value={newCode} onChange={(e) => setNewCode(e.target.value)} placeholder="hpc-perf-v2" />
            <Input label="名称" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="HPC 性能记录模板 v2" />
            <Button variant="primary" onClick={() => { void createTemplate(); }} disabled={loading === 'create'}>{loading === 'create' ? '创建中…' : '创建'}</Button>
          </div>
        </div>
      )}

      {templates.length === 0 ? <Empty title="暂无模板" /> : (
        <div className="card">
          <table className="data-table">
            <thead><tr><th>代码</th><th>名称</th><th>状态</th><th>版本</th><th>操作</th></tr></thead>
            <tbody>
              {templates.map((t) => {
                const isOpen = expanded === t.id;
                const verList = versions[t.id] ?? [];
                return (
                  <>
                    <tr key={t.id} onClick={() => toggleExpand(t.id)} style={{ cursor: 'pointer' }}>
                      <td data-label="代码"><span className="mono">{t.code}</span></td>
                      <td data-label="名称">{t.name}</td>
                      <td data-label="状态"><StatusBadge value={t.status} /></td>
                      <td data-label="版本">rev.{t.revision} {isOpen ? '▲' : '▼'}</td>
                      <td data-label="操作" onClick={(e) => e.stopPropagation()}>
                        {canManage && <Button variant="ghost" onClick={() => { void createVersion(t.id); }} disabled={loading === `ver-${t.id}`}>+版本</Button>}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr key={`${t.id}-versions`}>
                        <td colSpan={5} style={{ background: 'var(--color-surface-muted)', padding: '12px 20px' }}>
                          {!verList.length ? <InfoNotice message="暂无版本" /> : (
                            <table className="data-table" style={{ margin: 0 }}>
                              <thead><tr><th>版本号</th><th>状态</th><th>REV</th><th>操作</th></tr></thead>
                              <tbody>
                                {verList.map((v) => (
                                  <tr key={v.id}>
                                    <td data-label="版本号">v{v.versionNo}</td>
                                    <td data-label="状态"><StatusBadge value={v.status} /></td>
                                    <td data-label="REV">{v.revision}</td>
                                    <td data-label="操作">
                                      {canManage && v.status !== 'published' && (
                                        <Button variant="ghost" onClick={() => { void publishVersion(v.id, `v${v.versionNo}`); }} disabled={loading === `pub-${v.id}`}>
                                          {loading === `pub-${v.id}` ? '发布中…' : '发布'}
                                        </Button>
                                      )}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}