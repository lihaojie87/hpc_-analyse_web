import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import { Button, Empty, ErrorNotice, Input, Loading } from '../components/ui';
import MetricCompareChart, { type MetricPoint } from '../components/MetricCompareChart';
import type { PortalRecord } from './Dashboard';

type LoadState = 'loading' | 'ready' | 'error';
interface RecordList { items?: PortalRecord[]; total?: number; dataVersionId?: string | null; versionNo?: number | null }
function safeName(value: string | null | undefined): string { return value?.trim() || '未分类'; }


/** A single software profile card; reused by both the single grid and the grouped sections. */
function ProfileCard({ record }: { record: PortalRecord }): JSX.Element {
  return (
    <Link className="profile-card card" key={record.id} to={`/cases/${encodeURIComponent(record.id)}`}>
      <div className="profile-card-head">
        <strong>{record.softwareName || record.softwareId?.slice(0, 20) || '—'}</strong>
        <span className="role-badge">{record.profileName || record.profileId?.slice(0, 20) || '—'}</span>
      </div>
      <h2>{record.stableKey}</h2>
      <p className="muted">算例详情 · revision {record.revision ?? '—'}</p>
      <span className="table-action">查看详情 →</span>
    </Link>
  );
}

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
  const softwareNames = useMemo(() => {
    const map = new Map<string, string>();
    records.forEach((r) => {
      if (r.softwareId) map.set(r.softwareId, r.softwareName || r.softwareId);
    });
    return Array.from(map.entries()).sort((a, b) => a[1].localeCompare(b[1]));
  }, [records]);
  const visible = useMemo(() => records.filter((record) => (!selected || record.softwareId === selected) && (!search.trim() || `${record.stableKey} ${record.profileName ?? record.profileId ?? ''}`.toLowerCase().includes(search.trim().toLowerCase()))), [records, selected, search]);

  /* ----- UI-T05: metric comparison (grouped by unit, no extra request) ----- */
  const metricComparison = useMemo(() => {
    const pointsByUnit = new Map<string, MetricPoint[]>();
    const valueSkippedByUnit = new Map<string, number>();
    const metaSkippedByUnit = new Map<string, number>();
    let unitMissingSkipped = 0;
    let totalPlotted = 0;

    for (const record of visible) {
      const payload = record.payload as Record<string, unknown> | null | undefined;
      if (!payload || typeof payload !== 'object') { unitMissingSkipped += 1; continue; }
      const metricRaw = payload.metric;
      const unitRaw = payload.unit;
      const valueRaw = payload.value;
      const metric = typeof metricRaw === 'string' ? metricRaw.trim() : '';
      const unit = typeof unitRaw === 'string' ? unitRaw.trim() : '';
      if (!unit) { unitMissingSkipped += 1; continue; }

      // accept number, or a numeric string (sample payloads may serialize numbers as strings)
      let numeric: number;
      if (typeof valueRaw === 'number') numeric = valueRaw;
      else if (typeof valueRaw === 'string' && valueRaw.trim() !== '' && Number.isFinite(Number(valueRaw))) numeric = Number(valueRaw);
      else numeric = NaN;

      if (!metric) {
        metaSkippedByUnit.set(unit, (metaSkippedByUnit.get(unit) ?? 0) + 1);
        continue;
      }
      if (!Number.isFinite(numeric)) {
        valueSkippedByUnit.set(unit, (valueSkippedByUnit.get(unit) ?? 0) + 1);
        continue;
      }
      if (!pointsByUnit.has(unit)) pointsByUnit.set(unit, []);
      // stableKey kept FULL here so it stays a unique X-axis category; the chart
      // truncates it only for display (avoids collision when prefixes match — D2).
      pointsByUnit.get(unit)!.push({
        stableKey: record.stableKey ?? '',
        value: numeric,
        metric,
      });
      totalPlotted += 1;
    }

    const unitGroups = Array.from(pointsByUnit.entries()).map(([unit, points]) => {
      const metrics = Array.from(new Set(points.map((p) => p.metric)));
      const metricsLabel = metrics.length === 1 ? metrics[0] : metrics.join('、');
      return {
        unit,
        points,
        metricsLabel,
        valueSkipped: valueSkippedByUnit.get(unit) ?? 0,
        metaSkipped: metaSkippedByUnit.get(unit) ?? 0,
      };
    });
    unitGroups.sort((a, b) => a.unit.localeCompare(b.unit));

    // D1 fix: a unit may have records but produce zero plottable points (every record
    // skipped for missing value/metric). Those skips live only in the per-unit skip
    // maps and would otherwise be silently dropped. Sum them for units with no chart.
    let allSkippedValue = 0;
    let allSkippedMeta = 0;
    for (const [unit, n] of valueSkippedByUnit) if (!pointsByUnit.has(unit)) allSkippedValue += n;
    for (const [unit, n] of metaSkippedByUnit) if (!pointsByUnit.has(unit)) allSkippedMeta += n;

    return { unitGroups, unitMissingSkipped, totalPlotted, allSkippedValue, allSkippedMeta };
  }, [visible]);

  /* ----- UI-T05: group the card grid by profileName (search filter preserved) ----- */
  const profileGroups = useMemo(() => {
    const map = new Map<string, PortalRecord[]>();
    for (const r of visible) {
      const key = r.profileName?.trim() || r.profileId?.trim() || '未分类';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(r);
    }
    return map;
  }, [visible]);
  const multipleProfiles = profileGroups.size > 1;

  if (state === 'loading') return <main className="stack"><Loading label="正在加载软件画像…" /></main>;
  if (state === 'error') return <main className="stack"><div className="page-heading"><div><h1>软件画像</h1><p>按软件查看可见算例。</p></div><Button variant="secondary" onClick={() => { void load(); }}>重试</Button></div><ErrorNotice message={error} /></main>;
  if (records.length === 0) return <main className="stack"><div className="page-heading"><div><h1>软件画像</h1><p>按软件查看可见算例。</p></div></div><Empty title="暂无软件画像数据" /></main>;
  return <main className="stack">
    <div className="page-heading"><div><h1>{selected ? `${selected} 软件画像` : '软件画像'}</h1><p>选择软件后查看其算例与性能记录，缺失字段保持为空。</p></div><Link className="button button-secondary" to="/dashboard">返回总览</Link></div>
    <div className="toolbar"><Input label="搜索算例" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="按 Stable Key / 画像搜索" /><label className="field"><span className="field-label">切换软件</span><select className="input" value={selected} onChange={(event) => { window.location.href = event.target.value ? `/profiles/${encodeURIComponent(event.target.value)}` : '/profiles'; }}><option value="">全部软件</option>{softwareNames.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label></div>

    {/* 指标对比：仅在选中软件且有可见记录时渲染 */}
    {selected && visible.length > 0 && (
      <section className="metric-compare-section" aria-label="指标对比">
        <div className="section-heading">
          <h2 className="card-title">指标对比</h2>
        </div>
        {metricComparison.unitGroups.length === 0 ? (
          // no plottable points at all — but if records were skipped, say so instead of a misleading "no metrics"
          metricComparison.allSkippedValue + metricComparison.allSkippedMeta + metricComparison.unitMissingSkipped > 0 ? (
            <Empty title={`当前软件有 ${metricComparison.allSkippedValue + metricComparison.allSkippedMeta + metricComparison.unitMissingSkipped} 条记录，但因缺少数值/指标/单位未纳入对比`} />
          ) : (
            <Empty title="当前软件暂无可对比的数值指标" />
          )
        ) : (
          <>
            <div className="dashboard-row metric-compare-grid">
              {metricComparison.unitGroups.map((group) => (
                <MetricCompareChart
                  key={group.unit}
                  unit={group.unit}
                  metricsLabel={group.metricsLabel}
                  data={group.points}
                  valueSkipped={group.valueSkipped}
                  metaSkipped={group.metaSkipped}
                />
              ))}
            </div>
            {metricComparison.allSkippedValue + metricComparison.allSkippedMeta > 0 && (
              <p className="muted metric-skip-note">
                另有 {metricComparison.allSkippedValue + metricComparison.allSkippedMeta} 条记录因缺少数值或指标名，其所属单位下无有效数值，未绘制对比图。
              </p>
            )}
            {metricComparison.unitMissingSkipped > 0 && (
              <p className="muted metric-skip-note">
                另有 {metricComparison.unitMissingSkipped} 条记录缺少单位，未纳入任何对比图。
              </p>
            )}
            <p className="muted metric-scope-note">
              数据口径：以上对比基于各记录的私有版本（draft/published 等，以 lifecycleStatus 为准），并非 current 发布版本。当前软件：{selected}，共 {metricComparison.totalPlotted} 条记录参与绘图。
            </p>
          </>
        )}
      </section>
    )}

    {/* 算例卡片：多个画像时分节，单画像时保持原单网格 */}
    {visible.length === 0 ? (
      <Empty title="当前筛选暂无算例" action={<Button variant="secondary" onClick={() => setSearch('')}>清除筛选</Button>} />
    ) : multipleProfiles ? (
      <div className="profile-sections">
        {Array.from(profileGroups.entries()).map(([name, items]) => (
          <section className="profile-section" key={name}>
            <h2 className="section-subtitle">{name}</h2>
            <div className="profile-grid">
              {items.map((record) => <ProfileCard key={record.id} record={record} />)}
            </div>
          </section>
        ))}
      </div>
    ) : (
      <div className="profile-grid">
        {visible.map((record) => <ProfileCard key={record.id} record={record} />)}
      </div>
    )}
  </main>;
}
