import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import { Button, Empty, ErrorNotice, Input, Loading } from '../components/ui';
import type { PortalRecord } from './Dashboard';

type LoadState = 'loading' | 'ready' | 'error';
interface RecordList { items?: PortalRecord[]; total?: number; dataVersionId?: string | null; versionNo?: number | null }
function safeName(value: string | null | undefined): string { return value?.trim() || '未分类'; }

export default function Profiles(): JSX.Element {
  const { softwareId } = useParams<{ softwareId?: string }>();
  const selected = softwareId ? decodeURIComponent(softwareId) : '';
  const [records, setRecords] = useState<PortalRecord[]>([]);
  const [search, setSearch] = useState('');
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState('');
  const load = useCallback(async (): Promise<void> => {
    setState('loading'); setError('');
    try { const response = await api<RecordList>('/api/v1/records'); setRecords(Array.isArray(response?.items) ? response.items : []); setState('ready'); }
    catch (requestError: unknown) { setError(requestError instanceof ApiError ? requestError.message : '软件画像加载失败，请稍后重试。'); setState('error'); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const softwareNames = useMemo(() => Array.from(new Set(records.map((record) => record.softwareId).filter((value): value is string => Boolean(value)))).sort(), [records]);
  const visible = useMemo(() => records.filter((record) => (!selected || record.softwareId === selected) && (!search.trim() || `${record.stableKey} ${record.profileId ?? ''}`.toLowerCase().includes(search.trim().toLowerCase()))), [records, selected, search]);
  if (state === 'loading') return <main className="stack"><Loading label="正在加载软件画像…" /></main>;
  if (state === 'error') return <main className="stack"><div className="page-heading"><div><h1>软件画像</h1><p>按软件查看可见算例。</p></div><Button variant="secondary" onClick={() => { void load(); }}>重试</Button></div><ErrorNotice message={error} /></main>;
  if (records.length === 0) return <main className="stack"><div className="page-heading"><div><h1>软件画像</h1><p>按软件查看可见算例。</p></div></div><Empty title="暂无软件画像数据" /></main>;
  return <main className="stack">
    <div className="page-heading"><div><h1>{selected ? `${selected} 软件画像` : '软件画像'}</h1><p>选择软件后查看其算例与性能记录，缺失字段保持为空。</p></div><Link className="button button-secondary" to="/dashboard">返回总览</Link></div>
    <div className="toolbar"><Input label="搜索算例" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="按 Stable Key / 画像搜索" /><label className="field"><span className="field-label">切换软件</span><select className="input" value={selected} onChange={(event) => { window.location.href = event.target.value ? `/profiles/${encodeURIComponent(event.target.value)}` : '/profiles'; }}><option value="">全部软件</option>{softwareNames.map((name) => <option key={name} value={name}>{name}</option>)}</select></label></div>
    {visible.length === 0 ? <Empty title="当前筛选暂无算例" action={<Button variant="secondary" onClick={() => setSearch('')}>清除筛选</Button>} /> : <div className="profile-grid">{visible.map((record) => <Link className="profile-card card" key={record.id} to={`/cases/${encodeURIComponent(record.id)}`}><div className="profile-card-head"><strong>{safeName(record.softwareId)}</strong><span className="role-badge">{safeName(record.profileId)}</span></div><h2>{record.stableKey}</h2><p className="muted">算例详情 · revision {record.revision ?? '—'}</p><span className="table-action">查看详情 →</span></Link>)}</div>}
  </main>;
}
