import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from '../api/client';
import { useAuth } from '../auth/store';
import { Button, ErrorNotice, Loading, StatusBadge, Empty, Input, SuccessNotice } from '../components/ui';

interface SoftwareItem { id: string; code: string; name: string; version: string | null; status: string; }
interface ProfileItem { id: string; code: string; name: string; softwareId: string; status: string; }
type LoadState = 'loading' | 'ready' | 'error';

export default function SoftwareAdmin(): JSX.Element {
  const { permissions } = useAuth();
  const canManage = permissions.includes('user:manage');

  const [software, setSoftware] = useState<SoftwareItem[]>([]);
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState('');
  const [msg, setMsg] = useState<{ t: 'ok' | 'err'; text: string } | null>(null);
  const [loading, setLoading] = useState(false);

  // create software form
  const [showSwForm, setShowSwForm] = useState(false);
  const [swCode, setSwCode] = useState(''); const [swName, setSwName] = useState(''); const [swVer, setSwVer] = useState('');

  // create profile form
  const [showPfForm, setShowPfForm] = useState(''); // softwareId
  const [pfCode, setPfCode] = useState(''); const [pfName, setPfName] = useState('');

  // expanded software → profiles
  const [expanded, setExpanded] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<Record<string, ProfileItem[]>>({});

  const load = useCallback(async () => {
    setState('loading'); setError('');
    try { setSoftware((await api<{ items: SoftwareItem[] }>('/api/v1/admin/software')).items ?? []); setState('ready'); }
    catch (e) { setError(e instanceof ApiError ? e.message : '加载失败'); setState('error'); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const loadProfiles = async (swId: string) => {
    try {
      const data = await api<{ items: ProfileItem[] }>(`/api/v1/admin/profiles?software=${swId}`);
      setProfiles((p) => ({ ...p, [swId]: data.items ?? [] }));
    } catch (e) { setMsg({ t: 'err', text: e instanceof ApiError ? e.message : '加载画像失败' }); }
  };
  const toggle = (id: string) => {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id); if (!profiles[id]) void loadProfiles(id);
  };

  const createSw = async () => {
    if (!swCode.trim() || !swName.trim()) return;
    setLoading(true); setMsg(null);
    try { await api('/api/v1/admin/software', { method: 'POST', body: JSON.stringify({ code: swCode.trim(), name: swName.trim(), version: swVer.trim() || null }) });
      setSwCode(''); setSwName(''); setSwVer(''); setShowSwForm(false); setMsg({ t: 'ok', text: `${swName.trim()} 已创建` }); await load();
    } catch (e) { setMsg({ t: 'err', text: e instanceof ApiError ? e.message : '创建失败' }); } finally { setLoading(false); }
  };

  const createPf = async (swId: string) => {
    if (!pfCode.trim() || !pfName.trim()) return;
    setLoading(true); setMsg(null);
    try { await api('/api/v1/admin/profiles', { method: 'POST', body: JSON.stringify({ code: pfCode.trim(), name: pfName.trim(), softwareId: swId }) });
      setPfCode(''); setPfName(''); setShowPfForm(''); setMsg({ t: 'ok', text: `${pfName.trim()} 已创建` });
      void loadProfiles(swId);
    } catch (e) { setMsg({ t: 'err', text: e instanceof ApiError ? e.message : '创建失败' }); } finally { setLoading(false); }
  };

  if (!canManage) return <main className="stack"><ErrorNotice message="权限不足。" /></main>;
  if (state === 'loading') return <main className="stack"><Loading label="加载中…" /></main>;
  if (state === 'error') return <main className="stack"><div className="page-heading"><div><h1>软件与画像管理</h1></div><Button variant="secondary" onClick={() => { void load(); }}>重试</Button></div><ErrorNotice message={error} /></main>;

  return (
    <main className="stack">
      <div className="page-heading">
        <div><h1>软件与画像管理</h1><p>管理 HPC 软件与性能测试画像，共 {software.length} 个软件。</p></div>
        <div className="heading-actions">
          <Button variant="primary" onClick={() => setShowSwForm((v) => !v)}>{showSwForm ? '取消' : '新建软件'}</Button>
          <Button variant="secondary" onClick={() => { void load(); }}>刷新</Button>
        </div>
      </div>

      {msg?.t === 'ok' && <SuccessNotice message={msg.text} />}
      {msg?.t === 'err' && <ErrorNotice message={msg.text} />}

      {showSwForm && (
        <div className="card" style={{ display: 'grid', gap: 12 }}>
          <h2 className="card-title">新建软件</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto', gap: 10, alignItems: 'end' }}>
            <Input label="代码" value={swCode} onChange={(e) => setSwCode(e.target.value)} placeholder="vasp" />
            <Input label="名称" value={swName} onChange={(e) => setSwName(e.target.value)} placeholder="VASP" />
            <Input label="版本（可选）" value={swVer} onChange={(e) => setSwVer(e.target.value)} placeholder="6.4.3" />
            <Button variant="primary" onClick={() => { void createSw(); }} disabled={loading}>{loading ? '创建中…' : '创建'}</Button>
          </div>
        </div>
      )}

      {software.length === 0 ? <Empty title="暂无软件" /> : (
        <div className="card">
          <table className="data-table">
            <thead><tr><th>代码</th><th>名称</th><th>版本</th><th>画像</th><th>操作</th></tr></thead>
            <tbody>
              {software.map((s) => {
                const isOpen = expanded === s.id;
                const pfs = profiles[s.id] ?? [];
                return (
                  <>
                    <tr key={s.id} onClick={() => toggle(s.id)} style={{ cursor: 'pointer' }}>
                      <td data-label="代码"><span className="mono">{s.code}</span></td>
                      <td data-label="名称"><strong>{s.name}</strong></td>
                      <td data-label="版本">{s.version || '—'}</td>
                      <td data-label="画像">
                        <StatusBadge value={s.status} />
                        <span className="muted" style={{ marginLeft: 8 }}>{pfs.length} 个画像 {isOpen ? '▲' : '▼'}</span>
                      </td>
                      <td data-label="操作" onClick={(e) => e.stopPropagation()}>
                        <Button variant="ghost" onClick={() => { setShowPfForm(s.id); setPfCode(''); setPfName(''); }}>+画像</Button>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr key={`${s.id}-pfs`}>
                        <td colSpan={5} style={{ background: 'var(--color-surface-muted)', padding: '12px 20px' }}>
                          {showPfForm === s.id && (
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 8, marginBottom: 10 }}>
                              <Input label="画像代码" value={pfCode} onChange={(e) => setPfCode(e.target.value)} placeholder={`${s.code}-standard`} />
                              <Input label="画像名称" value={pfName} onChange={(e) => setPfName(e.target.value)} placeholder={`${s.name} 标准基准`} />
                              <div style={{ display: 'flex', gap: 6, alignItems: 'end' }}>
                                <Button variant="primary" onClick={() => { void createPf(s.id); }} disabled={loading}>{loading ? '…' : '创建'}</Button>
                                <Button variant="ghost" onClick={() => setShowPfForm('')}>取消</Button>
                              </div>
                            </div>
                          )}
                          {pfs.length === 0 ? <span className="muted">暂无画像</span> : (
                            <table className="data-table" style={{ margin: 0 }}>
                              <thead><tr><th>代码</th><th>名称</th><th>状态</th></tr></thead>
                              <tbody>{pfs.map((p) => (<tr key={p.id}><td data-label="代码"><span className="mono">{p.code}</span></td><td data-label="名称">{p.name}</td><td data-label="状态"><StatusBadge value={p.status} /></td></tr>))}</tbody>
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