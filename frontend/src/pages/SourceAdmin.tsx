import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from '../api/client';
import { useAuth } from '../auth/store';
import { Button, ErrorNotice, Loading, StatusBadge, Empty, Input, SuccessNotice } from '../components/ui';

interface SourceItem { id: string; code: string; provider: string; status: string; revision: number; config: Record<string, unknown>; createdAt: string; updatedAt: string; }
type LoadState = 'loading' | 'ready' | 'error';

export default function SourceAdmin(): JSX.Element {
  const { permissions } = useAuth();
  const canManage = permissions.includes('source:manage');
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState('');
  const [msg, setMsg] = useState<{ t: 'ok' | 'err'; text: string } | null>(null);
  const [loading, setLoading] = useState(false);

  const [showForm, setShowForm] = useState(false);
  const [scCode, setScCode] = useState(''); const [scWbToken, setScWbToken] = useState(''); const [scRef, setScRef] = useState('feishu-default');
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setState('loading'); setError('');
    try { setSources((await api<{ items: SourceItem[] }>('/api/v1/sources')).items ?? []); setState('ready'); }
    catch (e) { setError(e instanceof ApiError ? e.message : '加载失败'); setState('error'); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const createSource = async () => {
    if (!scCode.trim() || !scWbToken.trim()) return;
    setLoading(true); setMsg(null);
    try { await api('/api/v1/sources', { method: 'POST', body: JSON.stringify({ code: scCode.trim(), workbookToken: scWbToken.trim(), credentialRef: scRef.trim() || 'default' }) });
      setScCode(''); setScWbToken(''); setShowForm(false); setMsg({ t: 'ok', text: `${scCode.trim()} 已创建` }); await load();
    } catch (e) { setMsg({ t: 'err', text: e instanceof ApiError ? e.message : '创建失败' }); } finally { setLoading(false); }
  };

  if (!canManage) return <main className="stack"><ErrorNotice message="权限不足，需要 source:manage 权限。" /></main>;
  if (state === 'loading') return <main className="stack"><Loading label="加载中…" /></main>;
  if (state === 'error') return <main className="stack"><div className="page-heading"><div><h1>数据源管理</h1></div><Button variant="secondary" onClick={() => { void load(); }}>重试</Button></div><ErrorNotice message={error} /></main>;

  return (
    <main className="stack">
      <div className="page-heading">
        <div><h1>数据源管理</h1><p>管理飞书表格等外部数据源连接，共 {sources.length} 个数据源。</p></div>
        <div className="heading-actions">
          <Button variant="primary" onClick={() => setShowForm((v) => !v)}>{showForm ? '取消' : '新建数据源'}</Button>
          <Button variant="secondary" onClick={() => { void load(); }}>刷新</Button>
        </div>
      </div>
      {msg?.t === 'ok' && <SuccessNotice message={msg.text} />}
      {msg?.t === 'err' && <ErrorNotice message={msg.text} />}
      {showForm && (
        <div className="card" style={{ display: 'grid', gap: 12 }}>
          <h2 className="card-title">新建数据源</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto', gap: 10, alignItems: 'end' }}>
            <Input label="编码" value={scCode} onChange={(e) => setScCode(e.target.value)} placeholder="feishu-lammps" />
            <Input label="Workbook Token" value={scWbToken} onChange={(e) => setScWbToken(e.target.value)} placeholder="E8bpbNtGJaEzFlsfe4xcNEbanHd" />
            <Input label="凭据引用" value={scRef} onChange={(e) => setScRef(e.target.value)} placeholder="feishu-default" />
            <Button variant="primary" onClick={() => { void createSource(); }} disabled={loading}>{loading ? '创建中…' : '创建'}</Button>
          </div>
        </div>
      )}
      {sources.length === 0 ? <Empty title="暂无数据源" /> : (
        <div className="card">
          <table className="data-table">
            <thead><tr><th>编码</th><th>类型</th><th>状态</th><th>REV</th><th>详情</th></tr></thead>
            <tbody>
              {sources.map((s) => (
                <>
                  <tr key={s.id} onClick={() => setExpanded(expanded === s.id ? null : s.id)} style={{ cursor: 'pointer' }}>
                    <td data-label="编码"><span className="mono">{s.code}</span></td>
                    <td data-label="类型">{s.provider}</td>
                    <td data-label="状态"><StatusBadge value={s.status} /></td>
                    <td data-label="REV">{s.revision} {expanded === s.id ? '▲' : '▼'}</td>
                    <td data-label="详情">{s.updatedAt ? new Date(s.updatedAt).toLocaleDateString() : '—'}</td>
                  </tr>
                  {expanded === s.id && (
                    <tr key={`${s.id}-detail`}>
                      <td colSpan={5} style={{ background: 'var(--color-surface-muted)', padding: '12px 20px' }}>
                        <dl className="meta-list" style={{ margin: 0 }}>
                          <div className="meta-item"><dt>ID</dt><dd className="mono">{s.id}</dd></div>
                          <div className="meta-item"><dt>创建</dt><dd>{s.createdAt ? new Date(s.createdAt).toLocaleString() : '—'}</dd></div>
                          <div className="meta-item"><dt>更新</dt><dd>{s.updatedAt ? new Date(s.updatedAt).toLocaleString() : '—'}</dd></div>
                          <div className="meta-item"><dt>配置</dt><dd><pre className="mono" style={{ fontSize: 11, margin: 0 }}>{JSON.stringify(s.config, null, 2)}</pre></dd></div>
                        </dl>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}