import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';
import { ApiError, api } from '../api/client';
import { Button, ErrorNotice, Loading, StatusBadge, Empty } from '../components/ui';

/* ----- types ----- */
export interface PortalRecord {
  id: string;
  stableKey: string;
  softwareId?: string | null;
  softwareName?: string | null;
  softwareCode?: string | null;
  templateName?: string | null;
  etag?: string | null;
  ownerUserId?: string | null;
  profileId?: string | null;
  profileName?: string | null;
  lifecycleStatus?: string | null;
  revision?: number | null;
  payload?: Record<string, unknown> | null;
}

interface CatalogData { items: PortalRecord[]; total: number; }

interface AnalyticsOverview {
  counts: {
    software: number; profiles: number; templates: number;
    dataSources: number; users: number; totalRecords: number;
  };
  recordStatus: Record<string, number>;
  topSoftware: Array<{ code: string; name: string; count: number }>;
  importStatus: Record<string, number>;
  totalImports: number;
}

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿', submitted: '已提交', reviewed: '已审核',
  published: '已发布', rejected: '已驳回',
  queued: '排队中', previewed: '已预览', validated: '已校验',
  staging: '待审核', awaiting_review: '待审核',
  failed: '失败', dead_letter: '死信',
};

const PIE_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316'];

/* ----- helpers ----- */
function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number' && Number.isNaN(value)) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

type LoadState = 'loading' | 'ready' | 'error';

/* ----- component ----- */
export default function Dashboard(): JSX.Element {
  const [analytics, setAnalytics] = useState<AnalyticsOverview | null>(null);
  const [recentRecords, setRecentRecords] = useState<PortalRecord[]>([]);
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState('');

  const load = useCallback(async (): Promise<void> => {
    setState('loading'); setError('');
    try {
      const [data, catalog] = await Promise.all([
        api<AnalyticsOverview>('/api/v1/analytics/overview'),
        api<CatalogData>('/api/v1/catalog/records?pageSize=10'),
      ]);
      setAnalytics(data);
      setRecentRecords(catalog?.items ?? []);
      setState('ready');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '数据加载失败');
      setState('error');
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const recordStatusData = useMemo(() => {
    if (!analytics?.recordStatus) return [];
    return Object.entries(analytics.recordStatus).map(([key, value]) => ({
      name: statusLabel(key), value,
    }));
  }, [analytics]);

  const importStatusData = useMemo(() => {
    if (!analytics?.importStatus) return [];
    return Object.entries(analytics.importStatus).map(([key, value]) => ({
      name: statusLabel(key), value,
    }));
  }, [analytics]);

  const topSwData = useMemo(() => {
    if (!analytics?.topSoftware) return [];
    return analytics.topSoftware.map((item) => ({
      name: (item.name || item.code).length > 16
        ? (item.name || item.code).slice(0, 14) + '…'
        : (item.name || item.code),
      count: item.count,
      full: item.name || item.code,
    }));
  }, [analytics]);

  /* ----- loading / error ----- */
  if (state === 'loading') return <main className="stack"><Loading label="正在加载总览数据…" /></main>;
  if (state === 'error') return (
    <main className="stack">
      <div className="page-heading">
        <div><h1>数据看板</h1><p>HPC 性能画像数据平台全景总览。</p></div>
        <Button variant="secondary" onClick={() => { void load(); }}>重试</Button>
      </div>
      <ErrorNotice message={error} />
    </main>
  );

  if (!analytics || analytics.counts.totalRecords === 0) return (
    <main className="stack">
      <div className="page-heading">
        <div><h1>数据看板</h1><p>HPC 性能画像数据平台全景总览。</p></div>
      </div>
      <Empty
        title="暂无数据"
        action={<Link className="button button-primary" to="/records/new">新建记录</Link>}
      />
    </main>
  );

  const { counts } = analytics;

  return (
    <main className="stack">
      {/* header */}
      <div className="page-heading">
        <div>
          <h1>数据看板</h1>
          <p>HPC 性能画像数据平台全景总览。</p>
        </div>
        <div className="heading-actions">
          <Button variant="secondary" onClick={() => { void load(); }}>刷新</Button>
          <Link className="button button-primary" to="/records/new">新建记录</Link>
        </div>
      </div>

      {/* metric cards */}
      <section className="metric-grid" aria-label="平台总览指标">
        <div className="metric-card"><span>软件</span><strong>{counts.software}</strong></div>
        <div className="metric-card"><span>画像</span><strong>{counts.profiles}</strong></div>
        <div className="metric-card"><span>性能记录</span><strong>{counts.totalRecords}</strong></div>
        <div className="metric-card"><span>数据模板</span><strong>{counts.templates}</strong></div>
        <div className="metric-card"><span>数据源</span><strong>{counts.dataSources}</strong></div>
        <div className="metric-card"><span>活跃用户</span><strong>{counts.users}</strong></div>
      </section>

      {/* charts row */}
      <div className="dashboard-row">
        {/* record status pie */}
        <section className="card chart-card">
          <h2 className="card-title">记录状态分布</h2>
          {recordStatusData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  data={recordStatusData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  label={({ name, value }) => `${name} ${value}`}
                >
                  {recordStatusData.map((_, idx) => (
                    <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="muted">暂无记录数据。</p>
          )}
        </section>

        {/* top software bar chart */}
        <section className="card chart-card">
          <h2 className="card-title">软件记录 Top 10</h2>
          {topSwData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={topSwData} layout="vertical" margin={{ left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} />
                <YAxis type="category" dataKey="name" width={140} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(_, __, props) => [props.payload.count, props.payload.full]} />
                <Bar dataKey="count" fill="#3b82f6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="muted">暂无软件数据。</p>
          )}
        </section>
      </div>

      {/* second row: import status + quick links */}
      <div className="dashboard-row">
        {/* import status pie */}
        {analytics.totalImports > 0 && (
          <section className="card chart-card">
            <h2 className="card-title">导入任务状态</h2>
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={importStatusData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%" cy="50%"
                  outerRadius={80}
                  label={({ name, value }) => `${name} ${value}`}
                >
                  {importStatusData.map((_, idx) => (
                    <Cell key={idx} fill={PIE_COLORS[(idx + 2) % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </section>
        )}

        {/* quick links */}
        <section className="card quick-links-card">
          <h2 className="card-title">快捷入口</h2>
          <div className="quick-link-grid">
            <Link to="/records" className="quick-link">
              <span className="ql-icon">📋</span>
              <div><strong>记录管理</strong><span className="muted">浏览和检索性能记录</span></div>
            </Link>
            <Link to="/records/new" className="quick-link">
              <span className="ql-icon">✏️</span>
              <div><strong>新建记录</strong><span className="muted">录入新的性能数据</span></div>
            </Link>
            <Link to="/profiles" className="quick-link">
              <span className="ql-icon">📊</span>
              <div><strong>软件画像</strong><span className="muted">按软件维度查看记录</span></div>
            </Link>
            <Link to="/data-description" className="quick-link">
              <span className="ql-icon">📖</span>
              <div><strong>数据说明</strong><span className="muted">了解性能指标含义</span></div>
            </Link>
          </div>
        </section>
      </div>

      {/* data version info */}
      <section className="card dashboard-version">
        <div>
          <span className="muted">记录总数</span>
          <strong className="version-number">{counts.totalRecords}</strong>
        </div>
        <div className="muted">
          {Object.entries(analytics.recordStatus).map(([k, v]) => (
            <span key={k} style={{ marginRight: 16 }}>
              <StatusBadge value={k} /> {statusLabel(k)}: {v}
            </span>
          ))}
        </div>
      </section>

      {/* recent records */}
      {recentRecords.length > 0 && (
        <section className="card">
          <div className="section-heading">
            <h2 className="card-title">最近记录</h2>
            <Link to="/records" className="button button-secondary">查看全部</Link>
          </div>
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>稳定键</th><th>软件</th><th>指标</th><th>值</th><th>状态</th></tr></thead>
              <tbody>
                {recentRecords.slice(0, 10).map((r) => {
                  const p = r.payload as Record<string, unknown> || {};
                  return (
                    <tr key={r.id}>
                      <td data-label="稳定键" style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        <Link to={`/records/${r.id}`}>{r.stableKey}</Link>
                      </td>
                      <td data-label="软件">{String(r.softwareId || '—').slice(0, 20)}</td>
                      <td data-label="指标">{String(p.metric || '—')}</td>
                      <td data-label="值">{String(p.value || '—')}</td>
                      <td data-label="状态"><StatusBadge value={r.lifecycleStatus || 'draft'} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </main>
  );
}