import type { MetricCardDef } from '../../config/displayTemplates';
import type { PortalRecord } from '../../pages/Dashboard';

function findValue(records: PortalRecord[], metric: string): { value: string; records: PortalRecord[] } {
  const matching = records.filter((r) => r.payload?.metric === metric);
  if (matching.length === 0) return { value: '—', records: [] };
  const vals = matching.map((r) => Number(r.payload?.value)).filter((v) => Number.isFinite(v));
  if (vals.length === 0) return { value: `${matching.length} 条(缺值)`, records: matching };
  const sum = vals.reduce((a, b) => a + b, 0);
  const unit = matching[0].payload?.unit ?? '';
  return { value: sum < 1 ? sum.toFixed(4) : sum < 100 ? sum.toFixed(1) : Math.round(sum).toLocaleString(), records: matching };
}

interface Props { cards: MetricCardDef[]; records: PortalRecord[]; }
export function MetricCards({ cards, records }: Props) {
  if (!cards.length) return null;
  return (
    <div className="analysis-cards">
      {cards.map((c) => {
        const { value } = findValue(records, c.metric);
        return (
          <div className="analysis-card" key={c.metric}>
            <div className="analysis-card-icon">{c.icon ?? '●'}</div>
            <div>
              <div className="analysis-card-label">{c.label}</div>
              <div className="analysis-card-value">{value} <span className="analysis-card-unit">{c.unit ?? ''}</span></div>
            </div>
          </div>
        );
      })}
    </div>
  );
}