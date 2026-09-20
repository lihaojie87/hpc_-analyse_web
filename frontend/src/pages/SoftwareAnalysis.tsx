import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import { Button, Loading, ErrorNotice, StatusBadge } from '../components/ui';
import { MetricCards } from '../components/analysis/MetricCards';
import { TextBlock, TagCloud, DataTable } from '../components/analysis/CommonSections';
import { ComparisonTable } from '../components/analysis/ComparisonTable';
import { getAllDisplayTemplates, type DisplayTemplate } from '../config/displayTemplates';
import type { PortalRecord } from './Dashboard';

export default function SoftwareAnalysis(): JSX.Element {
  const { softwareCode } = useParams<{ softwareCode: string }>();
  const code = softwareCode ?? '';
  const [template, setTemplate] = useState<DisplayTemplate | null>(null);
  const [records, setRecords] = useState<PortalRecord[]>([]);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setState('loading'); setError('');
    try {
      // resolve display template
      const tpl = getAllDisplayTemplates().find((t) => t.softwareCode === code) ?? null;
      setTemplate(tpl);
      // fetch records for this software (by code)
      const recs = await api<PortalRecord[]>(`/api/v1/records`);
      const items = Array.isArray(recs) ? recs : (recs as { items?: PortalRecord[] }).items ?? [];
      // filter by software code (records don't have softwareCode, use softwareId lookup via softwareName)
      // For now fetch all and filter client-side — records list API returns softwareName
      const all = await api<{ items: PortalRecord[] }>(`/api/v1/records?softwareCode=${code}`);
      setRecords(all.items ?? []);
      setState('ready');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '加载失败');
      setState('error');
    }
  }, [code]);

  useEffect(() => { void load(); }, [load]);

  if (state === 'loading') return <main className="stack"><div className="page-heading"><div><h1>{template?.title ?? code} 方案分析</h1></div></div><Loading label="正在加载分析数据…" /></main>;
  if (state === 'error') return <main className="stack"><div className="page-heading"><div><h1>方案分析</h1></div><Link className="button button-secondary" to="/profiles">返回画像</Link></div><ErrorNotice message={error} /><Button variant="secondary" onClick={() => { void load(); }}>重试</Button></main>;
  if (!template) return <main className="stack"><div className="page-heading"><div><h1>{code} 方案分析</h1><p>该软件尚未配置分析模板。</p></div><Link className="button button-secondary" to="/profiles">返回画像</Link></div></main>;

  const t = template;

  return (
    <main className="stack">
      {/* Hero */}
      <section className="analysis-hero">
        <div className="analysis-hero-left">
          <p className="analysis-hero-breadcrumb">方案分析 / {t.title}</p>
          <h1 className="analysis-hero-title">{t.title}</h1>
          {t.subtitle && <p className="analysis-hero-subtitle">{t.subtitle}</p>}
          {t.heroTags && t.heroTags.length > 0 && (
            <div className="analysis-hero-tags">
              {t.heroTags.map((tag) => <span className="analysis-hero-tag" key={tag}>{tag}</span>)}
            </div>
          )}
        </div>
        <div className="analysis-hero-right">
          <Link className="button button-secondary" to="/profiles">返回画像</Link>
          <span className="muted" style={{ marginLeft: 12 }}>{records.length} 条记录</span>
        </div>
      </section>

      {/* Sections */}
      {t.sections.map((sec, i) => (
        <section className="card stack" key={i}>
          {sec.title && <h2 className="card-title">{sec.title}</h2>}
          {sec.type === 'metric_cards' && sec.cards && <MetricCards cards={sec.cards} records={records} />}
          {sec.type === 'text_block' && sec.content && <TextBlock content={sec.content} />}
          {sec.type === 'tag_cloud' && sec.tags && <TagCloud tags={sec.tags} />}
          {sec.type === 'comparison_table' && sec.columns && sec.rows && (
            <ComparisonTable columns={sec.columns} rows={sec.rows} variantField={sec.variantField ?? 'variant'} records={records} />
          )}
          {sec.type === 'data_table' && <DataTable records={records} />}
        </section>
      ))}
    </main>
  );
}