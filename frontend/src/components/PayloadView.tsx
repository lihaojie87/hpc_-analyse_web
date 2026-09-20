import { Empty } from './ui';

/** A performance payload is a flat bag of arbitrary fields. */
export type Payload = Record<string, unknown>;

/**
 * Render a readable name with its raw ID as an auxiliary line.
 * Prefers `softwareName`/`profileName`; falls back to the UUID when the
 * backend has not resolved a name (it always keeps the ID available).
 */
export function NameWithId({ name, id }: { name?: string | null; id?: string | null }): JSX.Element {
  if (name) {
    return (
      <div className="name-with-id">
        <span>{name}</span>
        {id && <span className="sub-id muted mono">{id}</span>}
      </div>
    );
  }
  return <span className="mono">{id || '—'}</span>;
}

/** Top-level keys that, together, describe a single "core metric". */
const CORE_METRIC_KEYS = ['metric', 'value', 'unit'];

function isPrimitive(value: unknown): boolean {
  return (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  );
}

/** Render a scalar/primitive payload value for display. */
export function displayPrimitive(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number' && Number.isNaN(value)) return '—';
  return String(value);
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

interface CoreMetric {
  metric: string;
  value: unknown;
  unit: string;
}

/**
 * Group a record payload for display (UI-T05):
 *  - a highlighted **core metric** card when the payload carries `metric` +
 *    `value` (+ optional `unit`);
 *  - a **fields table** for every other primitive top-level field;
 *  - a **collapsible JSON block** for each complex (object/array) field.
 *
 * The editor in `RecordDetail` owns the mutable copy; this view is purely a
 * read-only, structured rendering of whatever payload it is handed.
 */
export function PayloadView({ payload }: { payload: Payload }): JSX.Element {
  const data = payload ?? {};
  const entries = Object.entries(data);
  if (entries.length === 0) {
    return <Empty title="当前算例暂无性能数据" />;
  }

  // Split the explicit core metric (metric / value / unit) from the rest.
  const hasCoreValue = 'value' in data;
  const coreMetric: CoreMetric | null = hasCoreValue
    ? {
        metric: 'metric' in data ? displayPrimitive(data.metric) : '指标',
        value: data.value,
        unit: 'unit' in data ? displayPrimitive(data.unit) : '',
      }
    : null;

  const restEntries = entries.filter(([key]) => !CORE_METRIC_KEYS.includes(key));
  const scalarRows = restEntries.filter(([, value]) => isPrimitive(value));
  const complexRows = restEntries.filter(([, value]) => !isPrimitive(value));

  return (
    <div className="stack">
      {coreMetric && (
        <section className="metric-grid" aria-label="核心指标">
          <div className="metric-card metric-card-accent" data-testid="core-metric-card">
            <span>
              {coreMetric.metric || '指标'}
              {coreMetric.unit ? `（${coreMetric.unit}）` : ''}
            </span>
            <strong>{displayPrimitive(coreMetric.value)}</strong>
          </div>
        </section>
      )}

      {scalarRows.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <caption className="sr-only">其余性能字段</caption>
            <thead>
              <tr>
                <th>字段</th>
                <th>值</th>
              </tr>
            </thead>
            <tbody>
              {scalarRows.map(([key, value]) => (
                <tr key={key}>
                  <td data-label="字段" className="mono">{key}</td>
                  <td data-label="值">{displayPrimitive(value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {complexRows.map(([key, value]) => (
        <details className="collapsible" key={key}>
          <summary>
            {key}
            <span className="muted">（复杂对象，点击展开 JSON）</span>
          </summary>
          <pre className="json-block mono" data-testid="payload-json-block">{prettyJson(value)}</pre>
        </details>
      ))}
    </div>
  );
}
