import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from '../api/client';
import { Button, ErrorNotice, Loading, Empty } from '../components/ui';

/* ----- types ----- */
interface SheetInfo { sheetId: string; title: string; rowCount?: number; }

interface QuickSetup { sourceId: string; code: string; sheets: SheetInfo[]; workbookToken: string; type: string; }

interface PreviewResult {
  headers?: string[];
  samples?: Array<Record<string, unknown>>;
  previewId?: string;
  status?: string;
  total?: number;
}

/* ----- wizard steps ----- */
type Step = 'url' | 'select-sheet' | 'preview' | 'result';

export default function ImportWizard(): JSX.Element {
  /* state */
  const [step, setStep] = useState<Step>('url');
  const [url, setUrl] = useState('');
  const [setup, setSetup] = useState<QuickSetup | null>(null);
  const [selectedSheet, setSelectedSheet] = useState<SheetInfo | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  /* ---- Step 1: paste URL → quick setup ---- */
  const handleUrlSubmit = async () => {
    if (!url.trim()) { setError('请输入飞书链接'); return; }
    if (!url.includes('feishu.cn')) { setError('请提供有效的飞书链接'); return; }
    setLoading(true); setError('');
    try {
      const data = await api<QuickSetup>('/api/v1/import/quick-setup', {
        method: 'POST',
        body: JSON.stringify({ url: url.trim() }),
      });
      setSetup(data);
      setStep('select-sheet');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '连接失败，请检查链接是否正确');
    } finally { setLoading(false); }
  };

  /* ---- Step 2: select sheet → preview ---- */
  const doPreview = async (sheet: SheetInfo) => {
    setSelectedSheet(sheet);
    setLoading(true); setError('');
    try {
      const data = await api<PreviewResult>('/api/v1/import/previews', {
        method: 'POST',
        body: JSON.stringify({
          sourceId: setup!.sourceId,
          sheetId: sheet.sheetId,
          template: {},
          mapping: [],
        }),
      });
      setPreview(data);
      setStep('preview');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '预览失败');
    } finally { setLoading(false); }
  };

  /* ---- Step 3: execute import ---- */
  const executeImport = async () => {
    setLoading(true); setError('');
    try {
      const data = await api<{ recordsCreated: number; software: { name: string }; totalRecords: number }>(
        '/api/v1/import/demo-import',
        {
          method: 'POST',
          body: JSON.stringify({
            sourceId: setup!.sourceId,
            sheetId: selectedSheet!.sheetId,
          }),
        }
      );
      setPreview((prev) => prev ? { ...prev, status: 'staging', total: data.recordsCreated } : null);
      setStep('result');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '导入失败');
    } finally { setLoading(false); }
  };

  /* ---- render ---- */
  return (
    <main className="stack">
      <div className="page-heading">
        <div><h1>飞书数据导入</h1><p>粘贴飞书表格链接，自动导入性能数据到平台目录。</p></div>
      </div>
      {error && <ErrorNotice message={error} />}

      {/* Step indicator */}
      <div className="wizard-steps">
        {(['url', 'select-sheet', 'preview', 'result'] as Step[]).map((s, i) => (
          <div key={s} className={`wizard-step ${step === s ? 'active' : ''} ${['url','select-sheet','preview','result'].indexOf(step) > i ? 'done' : ''}`}>
            <span className="wizard-step-num">{i + 1}</span>
            <span>{s === 'url' ? '输入链接' : s === 'select-sheet' ? '选择工作表' : s === 'preview' ? '预览数据' : '完成'}</span>
          </div>
        ))}
      </div>

      {/* ---- STEP 1: URL input ---- */}
      {step === 'url' && (
        <section className="card stack" style={{ maxWidth: 640, margin: '0 auto', textAlign: 'center', padding: '32px 24px' }}>
          <div style={{ fontSize: 40, marginBottom: 8 }}>📎</div>
          <h2 className="card-title">粘贴飞书表格链接</h2>
          <p className="muted">支持飞书 Sheets 和 Base 链接格式，自动识别表格结构。</p>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              className="input"
              value={url}
              onChange={(e) => { setUrl(e.target.value); setError(''); }}
              onKeyDown={(e) => { if (e.key === 'Enter') { void handleUrlSubmit(); } }}
              placeholder="https://xxx.feishu.cn/sheets/..."
              style={{ flex: 1, fontSize: 15, padding: '12px 16px' }}
              autoFocus
            />
            <Button onClick={() => { void handleUrlSubmit(); }} disabled={loading}>
              {loading ? '解析中…' : '连接'}
            </Button>
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            示例：https://lhui08qsvi.feishu.cn/sheets/Il1Ks8pFhha5P0t9Wh9cvR21ndR
          </p>
        </section>
      )}

      {/* ---- STEP 2: Select sheet ---- */}
      {step === 'select-sheet' && setup && (
        <section className="card stack">
          <div className="section-heading">
            <div>
              <h2 className="card-title">选择工作表</h2>
              <p className="muted">表格已连接，选择要导入的工作表。</p>
            </div>
            <Button variant="secondary" onClick={() => setStep('url')}>返回</Button>
          </div>
          {setup.sheets.length === 0 ? (
            <Empty title="未发现任何工作表" />
          ) : (
            <div className="sheet-grid">
              {setup.sheets.map((s) => (
                <div key={s.sheetId} className="source-card" onClick={() => { void doPreview(s); }}>
                  <div className="source-card-header"><strong>{s.title}</strong></div>
                  <div className="source-card-body">
                    <span className="muted">行数: {s.rowCount ?? '?'}</span>
                    <span className="muted">ID: {s.sheetId}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* ---- STEP 3: Preview ---- */}
      {step === 'preview' && preview && (
        <section className="stack">
          <div className="section-heading">
            <h2 className="card-title">数据预览 — {selectedSheet?.title}</h2>
            <div>
              <Button variant="secondary" onClick={() => setStep('select-sheet')} style={{ marginRight: 8 }}>返回</Button>
              <Button onClick={() => { void executeImport(); }} disabled={loading}>
                {loading ? '执行中…' : '执行导入'}
              </Button>
            </div>
          </div>
          {preview.headers && preview.headers.length > 0 && (
            <div className="card">
              <h3 className="card-title">表头（{preview.headers.length} 列）</h3>
              <div className="field-tags">
                {preview.headers.slice(0, 24).map((h, i) => (
                  <span key={i} className="field-tag">{String(h || `列${i}`).substring(0, 30)}</span>
                ))}
                {preview.headers.length > 24 && <span className="field-tag" style={{ background: 'var(--color-line)' }}>+{preview.headers.length - 24} 列</span>}
              </div>
            </div>
          )}
          {preview.samples && preview.samples.length > 0 && (
            <div className="card">
              <h3 className="card-title">示例数据（{preview.samples.length} / {preview.total ?? '?'} 条）</h3>
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th>#</th><th>stableKey</th><th>raw</th></tr></thead>
                  <tbody>
                    {preview.samples.slice(0, 15).map((r, i) => (
                      <tr key={i}><td>{i + 1}</td>
                        <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{String(r.stableKey ?? '—')}</td>
                        <td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{JSON.stringify(r.raw).substring(0, 80)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      )}

      {/* ---- STEP 4: Result ---- */}
      {step === 'result' && (
        <section className="card stack" style={{ textAlign: 'center', padding: '48px 24px' }}>
          {preview?.status === 'failed' ? (
            <>
              <div style={{ fontSize: 48, marginBottom: 12 }}>❌</div>
              <h2>导入失败</h2>
              <p className="muted">请检查数据源配置后重试。</p>
              <Button onClick={() => setStep('url')}>返回重试</Button>
            </>
          ) : (
            <>
              <div style={{ fontSize: 48, marginBottom: 12 }}>✅</div>
              <h2>导入成功！</h2>
              <p className="muted">{preview?.total ?? '?'} 条数据已发布到正式目录，看板已更新。</p>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 16 }}>
                <Button variant="secondary" onClick={() => { setStep('url'); setSetup(null); }}>导入更多</Button>
                <Button onClick={() => window.location.href = '/dashboard'}>返回看板</Button>
              </div>
            </>
          )}
        </section>
      )}
    </main>
  );
}