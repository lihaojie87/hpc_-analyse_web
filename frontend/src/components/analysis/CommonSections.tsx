import type { PortalRecord } from '../../pages/Dashboard';

interface Props { content: string; }
function mdToHtml(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br/>');
}
export function TextBlock({ content }: Props) {
  return <div className="analysis-text" dangerouslySetInnerHTML={{ __html: mdToHtml(content) }} />;
}

interface TagCloudProps { tags: string[]; }
interface TagCloudProps { tags: string[]; }
export function TagCloud({ tags }: TagCloudProps) {
  return <div className="analysis-tags">{tags.map((t) => <span className="analysis-tag" key={t}>{t}</span>)}</div>;
}

interface DataTableProps { records: PortalRecord[]; }
export function DataTable({ records }: DataTableProps) {
  if (!records.length) return <p className="muted">暂无性能记录</p>;
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead><tr><th>稳定键</th><th>画像</th><th>指标</th><th>值</th><th>状态</th></tr></thead>
        <tbody>
          {records.map((r) => (
            <tr key={r.id}>
              <td data-label="稳定键" className="mono" style={{ fontSize: 12 }}>{r.stableKey}</td>
              <td data-label="画像">{r.profileName || '—'}</td>
              <td data-label="指标">{String(r.payload?.metric ?? '—')}</td>
              <td data-label="值">{String(r.payload?.value ?? '—')}{String(r.payload?.unit ?? '')}</td>
              <td data-label="状态"><span className="status-badge status-badge-neutral">{r.lifecycleStatus ?? 'draft'}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}