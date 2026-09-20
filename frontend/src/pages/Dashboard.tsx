import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import { Button, Empty, ErrorNotice, Loading, StatusBadge } from '../components/ui';

export interface PortalRecord {
  id: string;
  stableKey: string;
  softwareId?: string | null;
  profileId?: string | null;
  templateVersionId?: string | null;
  lifecycleStatus?: string | null;
  revision?: number | null;
  payload?: Record<string, unknown> | null;
}
export interface CurrentCatalog {
  dataVersionId?: string | null;
  versionNo?: number | null;
  publishedAt?: string | null;
  records?: Array<{ recordId: string; parsedPayload?: Record<string, unknown> | null; rawPayload?: Record<string, unknown> | null }>;
}
interface RecordList { items?: PortalRecord[] }
type LoadState = 'loading' | 'ready' | 'error';

export function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number' && Number.isNaN(value)) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
function formatDate(value?: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

export default function Dashboard(): JSX.Element {
  const [records, setRecords] = useState<PortalRecord[]>([]);
  const [current, setCurrent] = useState<CurrentCatalog | null>(null);
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState('');
  const load = useCallback(async (): Promise<void> => {
    setState('loading'); setError('');
    try {
      const [list, catalog] = await Promise.all([api<RecordList>('/api/v1/records'), api<CurrentCatalog>('/api/v1/data-versions/current')]);
      setRecords(Array.isArray(list?.items) ? list.items : []);
      setCurrent(catalog ?? null); setState('ready');
    } catch (requestError: unknown) {
      setError(requestError instanceof ApiError ? requestError.message : '总览数据加载失败，请稍后重试。'); setState('error');
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const softwareCount = useMemo(() => new Set(records.map((record) => record.softwareId).filter(Boolean)).size, [records]);
  const profileCount = useMemo(() => new Set(records.map((record) => `${record.softwareId ?? ''}:${record.profileId ?? ''}`)).size, [records]);
  const publishedCount = useMemo(() => records.filter((record) => record.lifecycleStatus === 'published').length, [records]);
  if (state === 'loading') return <main className="stack"><Loading label="正在加载性能总览…" /></main>;
  if (state === 'error') return <main className="stack"><div className="page-heading"><div><h1>总览 Dashboard</h1><p>当前发布目录与可见记录概览。</p></div><Button variant="secondary" onClick={() => { void load(); }}>重试</Button></div><ErrorNotice message={error} /></main>;
  if (records.length === 0) return <main className="stack"><div className="page-heading"><div><h1>总览 Dashboard</h1><p>当前发布目录与可见记录概览。</p></div></div><Empty title="暂无性能记录" action={<Link className="button button-primary" to="/records/new">新建记录</Link>} /></main>;
  return <main className="stack">
    <div className="page-heading"><div><h1>总览 Dashboard</h1><p>从当前发布版本快速了解 HPC 性能数据规模与收益。</p></div><Button variant="secondary" onClick={() => { void load(); }}>刷新</Button></div>
    <section className="dashboard-version card"><div><span className="muted">当前数据版本</span><strong className="version-number">{displayValue(current?.versionNo)}</strong></div><div className="muted">发布时间：{formatDate(current?.publishedAt)}</div><StatusBadge value={current?.dataVersionId ? 'published' : 'staging'} /></section>
    <section className="metric-grid" aria-label="总览指标"><div className="metric-card"><span>软件数量</span><strong>{softwareCount}</strong></div><div className="metric-card"><span>软件画像</span><strong>{profileCount}</strong></div><div className="metric-card"><span>可见算例</span><strong>{records.length}</strong></div><div className="metric-card"><span>已发布记录</span><strong>{publishedCount}</strong></div></section>
    <section className="card stack"><div className="section-heading"><h2 className="card-title">软件画像入口</h2><Link to="/profiles" className="table-action">查看全部</Link></div><div className="profile-grid">{Array.from(new Set(records.map((record) => record.softwareId).filter((value): value is string => Boolean(value)))).slice(0, 8).map((software) => <Link className="profile-tile" key={software} to={`/profiles/${encodeURIComponent(software)}`}><strong>{software}</strong><span className="muted">{records.filter((record) => record.softwareId === software).length} 个算例</span></Link>)}</div></section>
  </main>;
}
