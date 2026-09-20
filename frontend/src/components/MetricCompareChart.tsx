import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';

export interface MetricPoint {
  /** FULL stableKey; used as the unique X-axis category so records whose first
   *  N chars match don't collide after truncation (D2). Display is truncated
   *  only via the XAxis tickFormatter. */
  stableKey: string;
  /** numeric value, already validated as a finite number */
  value: number;
  /** metric name from the record payload */
  metric: string;
}

const MAX_AXIS_LABEL = 14;
function truncateLabel(value: string): string {
  return value.length > MAX_AXIS_LABEL ? `${value.slice(0, MAX_AXIS_LABEL - 2)}…` : value;
}

interface MetricCompareChartProps {
  /** the grouped unit, e.g. "s" / "%" / "GB" */
  unit: string;
  /** display label for the metric name(s) in this unit group */
  metricsLabel: string;
  data: MetricPoint[];
  /** records in this unit that were dropped because value was missing / non-numeric */
  valueSkipped: number;
  /** records in this unit that were dropped because metric name was missing */
  metaSkipped: number;
}

/**
 * One bar chart per `unit`. Different units are NEVER mixed into the same chart
 * (the parent groups by unit). Missing / non-numeric values are skipped upstream
 * and only surfaced as a muted skip note below the chart.
 */
export default function MetricCompareChart({
  unit, metricsLabel, data, valueSkipped, metaSkipped,
}: MetricCompareChartProps): JSX.Element {
  return (
    <section className="card chart-card metric-compare-card" role="region" aria-label={`指标对比图：${metricsLabel}（${unit}）`}>
      <h2 className="card-title">{metricsLabel}（{unit}）</h2>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis
            dataKey="stableKey"
            tickFormatter={(value) => truncateLabel(String(value))}
            tick={{ fontSize: 11 }}
            interval={0}
            angle={-30}
            textAnchor="end"
            height={72}
          />
          <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
          <Tooltip
            formatter={(_, __, item) => [`${item.payload.value} ${unit}`, item.payload.stableKey]}
            labelFormatter={(label) => String(label)}
          />
          <Bar dataKey="value" fill="#176b87" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
      {valueSkipped > 0 && (
        <p className="muted metric-skip-note">已跳过 {valueSkipped} 条缺少数值的记录</p>
      )}
      {metaSkipped > 0 && (
        <p className="muted metric-skip-note">已跳过 {metaSkipped} 条缺少指标名的记录</p>
      )}
    </section>
  );
}
