import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import { Button, Empty, ErrorNotice, Loading, StatusBadge } from '../components/ui';
import type { PortalRecord } from './Dashboard';

function display(value: unknown): string { if (value === null || value === undefined || value === '') return '—'; if (typeof value === 'object') return JSON.stringify(value); return String(value); }
function PayloadTable({ payload }: { payload: Record<string, unknown> }): JSX.Element {
  const entries = Object.entries(payload);
  if (!entries.length) return <Empty title="当前算例暂无数据说明" />;
  return <div className="table-wrap"><table className="data-table"><caption className="sr-only">算例数据</caption><thead><tr><th>字段</th><th>值</th></tr></thead><tbody>{entries.map(([key, value]) => <tr key={key}><td data-label="字段" className="mono">{key}</td><td data-label="值">{display(value)}</td></tr>)}</tbody></table></div>;
}
export default function CaseDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>();
  const [record, setRecord] = useState<PortalRecord | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState('');
  const load = useCallback(async (): Promise<void> => {
    if (!id) { setError('算例 ID 缺失'); setState('error'); return; }
    setState('loading'); setError('');
    try { setRecord(await api<PortalRecord>(`/api/v1/records/${encodeURIComponent(id)}`)); setState('ready'); }
    catch (requestError: unknown) { setError(requestError instanceof ApiError ? requestError.message : '算例详情加载失败，请稍后重试。'); setState('error'); }
  }, [id]);
  useEffect(() => { void load(); }, [load]);
  if (state === 'loading') return <main className="stack"><Loading label="正在加载算例详情…" /></main>;
  if (state === 'error') return <main className="stack"><div className="page-heading"><div><h1>算例详情</h1><p>暂时无法读取该算例。</p></div><Link className="button button-secondary" to="/profiles">返回软件画像</Link></div><ErrorNotice message={error} /><Button onClick={() => { void load(); }}>重试</Button></main>;
  if (!record) return <main className="stack"><Empty title="算例不存在或不可见" action={<Link className="button button-secondary" to="/profiles">返回软件画像</Link>} /></main>;
  return <main className="stack"><div className="page-heading"><div><p className="muted">{record.softwareId || '未指定软件'} / {record.profileId || '默认画像'}</p><h1>{record.stableKey}</h1><p>查看当前算例的性能字段与数据来源。</p></div><Link className="button button-secondary" to={`/profiles/${encodeURIComponent(record.softwareId ?? '')}`}>返回画像</Link></div><section className="card"><h2 className="card-title">算例摘要</h2><dl className="meta-list"><div className="meta-item"><dt>软件</dt><dd>{record.softwareId || '—'}</dd></div><div className="meta-item"><dt>画像</dt><dd>{record.profileId || '—'}</dd></div><div className="meta-item"><dt>状态</dt><dd><StatusBadge value={record.lifecycleStatus || 'unknown'} /></dd></div><div className="meta-item"><dt>Revision</dt><dd>{record.revision ?? '—'}</dd></div></dl></section><section className="card stack"><div className="section-heading"><h2 className="card-title">性能数据</h2><Link className="table-action" to="/data-description">查看数据说明</Link></div><PayloadTable payload={record.payload ?? {}} /></section></main>;
}
