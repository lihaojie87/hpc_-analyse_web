import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import { useAuth } from '../auth/store';
import { Button, Empty, ErrorNotice, Input, Loading, Select, StatusBadge } from '../components/ui';

/** A single performance record as returned by `GET /api/v1/records`. */
interface RecordItem {
  id: string;
  stableKey: string;
  softwareId: string;
  softwareName?: string;
  profileId: string;
  profileName?: string;
  templateVersionId?: string;
  lifecycleStatus: string;
  revision: number;
  /**
   * `updatedAt` is NOT part of the current backend contract
   * (`catalog_service.record_dict`). It is read opportunistically so the column
   * lights up automatically once the API exposes it — otherwise a `—` is shown
   * rather than a fabricated timestamp.
   */
  updatedAt?: string;
}

/** Backend pagination envelope. Present, but server-side paging is not enabled yet. */
interface PaginationMeta {
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}

interface RecordListResponse {
  items: RecordItem[];
  pagination?: PaginationMeta;
}

type LoadState = 'loading' | 'error' | 'ready';

/** Human-readable timestamp, or an em dash when the field is absent/unparsable. */
function formatTime(value?: string): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
}

/**
 * Records list (UI-T03).
 *
 * Covers the five required states — loading, error (+ retry), empty, success
 * and the filtered "no match" variant — with client-side search / status filter
 * and an explicit *reserved* pagination footer. The backend currently returns
 * the full collection (its `page` parameter is ignored), so no server-side
 * page/total semantics are invented here.
 */
export default function Records(): JSX.Element {
  const { token } = useAuth();
  const [records, setRecords] = useState<RecordItem[]>([]);
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const load = useCallback(async (): Promise<void> => {
    setLoadState('loading');
    setError('');
    try {
      const data = await api<RecordListResponse>('/api/v1/records');
      setRecords(Array.isArray(data?.items) ? data.items : []);
      setLoadState('ready');
    } catch (requestError: unknown) {
      setError(requestError instanceof ApiError ? requestError.message : '加载记录失败，请稍后重试。');
      setLoadState('error');
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Distinct lifecycle statuses actually present in the data (no invented options). */
  const statusOptions = useMemo<string[]>(() => {
    const seen = new Set<string>();
    records.forEach((record) => {
      if (record.lifecycleStatus) seen.add(record.lifecycleStatus);
    });
    return Array.from(seen).sort();
  }, [records]);

  const filtered = useMemo<RecordItem[]>(() => {
    const query = search.trim().toLowerCase();
    return records.filter((record) => {
      if (statusFilter !== 'all' && record.lifecycleStatus !== statusFilter) return false;
      if (!query) return true;
      return [record.stableKey, record.softwareName, record.softwareId, record.profileName, record.profileId, record.lifecycleStatus]
        .some((value) => (value ?? '').toLowerCase().includes(query));
    });
  }, [records, search, statusFilter]);

  const isFiltering = search.trim() !== '' || statusFilter !== 'all';

  return (
    <main className="stack">
      <div className="page-heading">
        <div>
          <h1>性能记录</h1>
          <p>浏览、搜索并维护你可见的性能数据记录。</p>
        </div>
        <Link className="button button-primary" to="/records/new">新建记录</Link>
      </div>

      <div className="toolbar">
        <Input
          label="搜索"
          type="search"
          value={search}
          placeholder="按 Stable Key / 软件 / 画像搜索"
          aria-label="搜索记录"
          onChange={(event) => setSearch(event.target.value)}
        />
        <Select
          label="状态筛选"
          value={statusFilter}
          aria-label="状态筛选"
          onChange={(event) => setStatusFilter(event.target.value)}
        >
          <option value="all">全部状态</option>
          {statusOptions.map((status) => (
            <option key={status} value={status}>{status.replaceAll('_', ' ')}</option>
          ))}
        </Select>
        <Button variant="secondary" type="button" onClick={() => { void load(); }} disabled={loadState === 'loading'}>
          {loadState === 'loading' ? '刷新中…' : '刷新'}
        </Button>
      </div>

      {loadState === 'loading' && <Loading label="正在加载记录…" />}

      {loadState === 'error' && (
        <div className="stack">
          <ErrorNotice message={error} />
          <div className="btn-row">
            <Button type="button" onClick={() => { void load(); }}>重试</Button>
          </div>
        </div>
      )}

      {loadState === 'ready' && records.length === 0 && (
        <Empty
          title="暂无记录"
          action={<Link className="button button-primary" to="/records/new">新建第一条记录</Link>}
        />
      )}

      {loadState === 'ready' && records.length > 0 && filtered.length === 0 && (
        <Empty
          title="没有匹配的记录"
          action={
            <Button variant="secondary" type="button" onClick={() => { setSearch(''); setStatusFilter('all'); }}>
              清除筛选条件
            </Button>
          }
        />
      )}

      {loadState === 'ready' && filtered.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <caption className="sr-only">性能记录列表</caption>
            <thead>
              <tr>
                <th scope="col">Stable Key</th>
                <th scope="col">软件</th>
                <th scope="col">画像</th>
                <th scope="col">状态</th>
                <th scope="col">Revision</th>
                <th scope="col">更新时间</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((record) => (
                <tr key={record.id}>
                  <td data-label="Stable Key"><span className="mono">{record.stableKey}</span></td>
                  <td data-label="软件">{record.softwareName || record.softwareId?.slice(0, 20) || '—'}</td>
                  <td data-label="画像">{record.profileName || record.profileId?.slice(0, 20) || '—'}</td>
                  <td data-label="状态"><StatusBadge value={record.lifecycleStatus} /></td>
                  <td data-label="Revision">{record.revision}</td>
                  <td data-label="更新时间">{formatTime(record.updatedAt)}</td>
                  <td data-label="操作"><Link className="table-action" to={`/records/${record.id}`}>查看</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {loadState === 'ready' && (
        <>
          <div className="pagination-bar">
            <span className="muted">
              已加载 {records.length} 条{isFiltering ? `，筛选后 ${filtered.length} 条` : ''}
            </span>
            <div className="pagination-controls" aria-label="分页预留">
              <Button variant="secondary" type="button" disabled aria-disabled="true">上一页</Button>
              <Button variant="secondary" type="button" disabled aria-disabled="true">下一页</Button>
            </div>
          </div>
          <p className="muted pagination-hint">
            分页预留：服务端分页尚未启用，接口当前返回全量数据，待后端支持后再启用翻页。
          </p>
        </>
      )}
    </main>
  );
}
