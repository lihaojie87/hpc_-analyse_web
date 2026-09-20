import type { ComparisonColumn, ComparisonRow } from '../../config/displayTemplates';
import type { PortalRecord } from '../../pages/Dashboard';

interface Props {
  columns: ComparisonColumn[];
  rows: ComparisonRow[];
  /** payload.variant field used to group records */
  variantField: string;
  records: PortalRecord[];
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return v < 1 ? v.toFixed(3) : v < 100 ? v.toFixed(1) : Math.round(v).toString();
  return String(v);
}

export function ComparisonTable({ columns, rows, variantField, records }: Props) {
  if (!columns.length || !rows.length) return null;
  // Build lookup: variant_key → metric_name → record
  const lookup = new Map<string, Map<string, PortalRecord>>();
  for (const r of records) {
    const vk = String(r.payload?.variant ?? '');
    if (!vk) continue;
    if (!lookup.has(vk)) lookup.set(vk, new Map());
    lookup.get(vk)!.set(String(r.payload?.metric ?? ''), r);
  }

  return (
    <div className="table-wrap" style={{ marginTop: 8 }}>
      <table className="data-table">
        <thead>
          <tr>
            <th>指标</th>
            {columns.map((c) => (
              <th key={c.key} title={c.desc}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.metric}>
              <td data-label="指标"><strong>{row.label}</strong>{row.unit ? <span className="muted" style={{ marginLeft: 4 }}>({row.unit})</span> : null}</td>
              {columns.map((col) => {
                const colRecords = lookup.get(col.key);
                const rec = colRecords?.get(row.metric);
                if (!rec) return <td key={col.key} data-label={col.label}>—</td>;
                const v = rec.payload?.value;
                const isNumber = typeof v === 'number' || (typeof v === 'string' && !isNaN(Number(v)));
                return (
                  <td key={col.key} data-label={col.label}>
                    {isNumber ? <strong>{fmt(v)}</strong> : fmt(v)}
                    {col.key !== 'baseline' && isNumber ? (
                      <span className="muted" style={{ fontSize: 11, marginLeft: 4 }}>
                        (×{(Number(v) / (Number(records.find((r) => String(r.payload?.variant) === 'baseline' && String(r.payload?.metric) === row.metric)?.payload?.value ?? 1))).toFixed(2)})
                      </span>
                    ) : null}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}