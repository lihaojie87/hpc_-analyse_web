import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import { useAuth } from '../auth/store';
import { Button, ErrorNotice, InfoNotice, Input, Loading, Select, SuccessNotice, Textarea } from '../components/ui';

interface TemplateItem { id: string; code: string; name: string; status: string; revision: number; }
interface TemplateVersionItem { id: string; versionNo: number; status: string; revision: number; }
interface TemplateFieldDef { id: string; path: string; label: string; dataType: string; unit: string | null; required: boolean; rules: Record<string, unknown>; }
interface SoftwareItem { id: string; name: string; code: string; }
interface ProfileItem { id: string; name: string; code: string; softwareId: string; }

type LoadState = 'loading' | 'ready' | 'unavailable';
interface JsonFeedback { tone: 'ok' | 'error'; text: string; }

function extractList<T>(payload: unknown): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === 'object') {
    const items = (payload as { items?: unknown }).items;
    if (Array.isArray(items)) return items as T[];
  }
  return [];
}

function describeTemplateError(error: unknown): string {
  if (error instanceof ApiError && (error.status === 403 || error.code === 'FORBIDDEN'))
    return '当前账号暂无模板读取权限，已切换为手工填写模板版本 ID。';
  if (error instanceof ApiError) return `模板列表加载失败：${error.message} 可手工填写模板版本 ID。`;
  return '模板列表加载失败，可手工填写模板版本 ID。';
}

export default function RecordForm(): JSX.Element {
  const { token, permissions } = useAuth();
  const canManage = permissions.includes('user:manage');
  const navigate = useNavigate();

  const [stableKey, setStableKey] = useState('');
  const [softwareId, setSoftwareId] = useState('');
  const [profileId, setProfileId] = useState('');
  const [softwareList, setSoftwareList] = useState<SoftwareItem[]>([]);
  const [profileList, setProfileList] = useState<ProfileItem[]>([]);

  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [templatesState, setTemplatesState] = useState<LoadState>('loading');
  const [templatesNotice, setTemplatesNotice] = useState('');
  const [templateId, setTemplateId] = useState('');
  const [versions, setVersions] = useState<TemplateVersionItem[]>([]);
  const [versionsState, setVersionsState] = useState<LoadState>('unavailable');
  const [versionsNotice, setVersionsNotice] = useState('');
  const [templateVersionId, setTemplateVersionId] = useState('');

  const [fields, setFields] = useState<TemplateFieldDef[]>([]);
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});
  const [payload, setPayload] = useState('{}');
  const [jsonFeedback, setJsonFeedback] = useState<JsonFeedback | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const submittingRef = useRef(false);

  // Load software & profiles for dropdowns
  useEffect(() => {
    if (!canManage) return;
    api<{ items: SoftwareItem[] }>('/api/v1/admin/software').then((d) => setSoftwareList(d.items ?? [])).catch(() => {});
  }, [canManage, token]);

  useEffect(() => {
    if (!softwareId || !canManage) { setProfileList([]); return; }
    api<{ items: ProfileItem[] }>(`/api/v1/admin/profiles?software=${softwareId}`).then((d) => setProfileList(d.items ?? [])).catch(() => setProfileList([]));
  }, [softwareId, canManage, token]);

  // ---- templates ----
  const loadTemplates = useCallback(async () => {
    setTemplatesState('loading'); setTemplatesNotice('');
    try {
      const list = extractList<TemplateItem>(await api<unknown>('/api/v1/templates'));
      setTemplates(list); setTemplatesState('ready');
      if (list.length === 0) setTemplatesNotice('当前没有可用模板，可手工填写。');
      else setTemplateId(list[0].id);
    } catch (e) { setTemplates([]); setTemplatesState('unavailable'); setTemplatesNotice(describeTemplateError(e)); }
  }, [token]);
  useEffect(() => { void loadTemplates(); }, [loadTemplates]);

  // ---- versions ----
  useEffect(() => {
    if (!templateId) { setVersions([]); setVersionsState('unavailable'); setTemplateVersionId(''); return; }
    let c = false;
    setVersionsState('loading');
    api<unknown>(`/api/v1/templates/${encodeURIComponent(templateId)}/versions`).then((data) => {
      if (c) return;
      const pub = extractList<TemplateVersionItem>(data).filter((v) => v.status === 'published');
      setVersions(pub); setVersionsState('ready');
      setTemplateVersionId(pub[0]?.id ?? '');
      setVersionsNotice(pub.length === 0 ? '该模板暂无已发布版本。' : '');
    }).catch((e) => { if (!c) { setVersions([]); setVersionsState('unavailable'); setTemplateVersionId(''); setVersionsNotice(describeTemplateError(e)); }});
    return () => { c = true; };
  }, [templateId, token]);

  // ---- template fields (dynamic form) ----
  useEffect(() => {
    if (!templateVersionId) { setFields([]); return; }
    let c = false;
    api<{ items: TemplateFieldDef[] }>(`/api/v1/templates/versions/${encodeURIComponent(templateVersionId)}/fields`).then((data) => {
      if (c) return;
      const fs = data.items ?? [];
      setFields(fs);
      // init values from existing payload or empty
      const existing: Record<string, string> = {};
      try { Object.assign(existing, JSON.parse(payload)); } catch {}
      const vals: Record<string, string> = {};
      fs.forEach((f) => { vals[f.path] = existing[f.path] ?? ''; });
      setFieldValues(vals);
    }).catch(() => { if (!c) setFields([]); });
    return () => { c = true; };
  }, [templateVersionId, token]);

  function setField(path: string, value: string) {
    setFieldValues((prev) => {
      const next = { ...prev, [path]: value };
      // Build payload from field values and sync to JSON editor
      const obj: Record<string, unknown> = {};
      Object.entries(next).forEach(([k, v]) => {
        if (v.trim() === '') return;
        const fld = fields.find((f) => f.path === k);
        if (fld?.dataType === 'number') {
          const n = Number(v);
          if (Number.isFinite(n)) obj[k] = n;
        } else {
          obj[k] = v;
        }
      });
      setPayload(JSON.stringify(obj, null, 2));
      return next;
    });
  }

  const jsonValid = useMemo(() => {
    try { JSON.parse(payload); return true; } catch { return false; }
  }, [payload]);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault(); if (submittingRef.current) return; setError('');
    if (!stableKey.trim() || !softwareId.trim() || !profileId.trim()) { setError('请填写基本信息中的必填项。'); return; }
    if (!templateVersionId.trim()) { setError('请选择模板版本。'); return; }
    let parsed: Record<string, unknown>;
    try { parsed = JSON.parse(payload) as Record<string, unknown>; } catch { setError('Payload JSON 不合法'); return; }
    submittingRef.current = true; setBusy(true);
    try {
      const created = await api<{ id: string }>('/api/v1/records', {
        method: 'POST', body: JSON.stringify({ stableKey: stableKey.trim(), softwareId: softwareId.trim(), profileId: profileId.trim(), templateVersionId: templateVersionId.trim(), payload: parsed }),
      });
      navigate(`/records/${created.id}`);
    } catch (e) { setError(e instanceof ApiError ? e.message : '保存失败'); }
    finally { submittingRef.current = false; setBusy(false); }
  }

  const hasDynamicFields = fields.length > 0;

  return (
    <main className="stack">
      <div className="page-heading">
        <div><h1>新建性能记录</h1><p>{hasDynamicFields ? '按模板字段填写数据，自动生成 Payload。' : '分「基本信息 / 关联对象 / Payload」三部分填写。'}</p></div>
        <Link className="button button-secondary" to="/records">返回列表</Link>
      </div>
      <form className="stack" onSubmit={submit} noValidate>
        {error && <ErrorNotice message={error} />}

        <section className="card stack">
          <h2 className="card-title">基本信息</h2>
          <div className="grid-2">
            <Input label="稳定主键 Stable Key" required value={stableKey} onChange={(e) => setStableKey(e.target.value)} placeholder="vasp-si-64atoms-O3" autoFocus />
            {canManage ? (
              <Select label="软件" value={softwareId} onChange={(e) => { setSoftwareId(e.target.value); setProfileId(''); }}>
                <option value="">请选择软件</option>
                {softwareList.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.code})</option>)}
              </Select>
            ) : (
              <Input label="软件 ID" required value={softwareId} onChange={(e) => setSoftwareId(e.target.value)} placeholder="UUID" />
            )}
            {canManage && softwareId ? (
              <Select label="画像" value={profileId} onChange={(e) => setProfileId(e.target.value)}>
                <option value="">请选择画像</option>
                {profileList.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.code})</option>)}
              </Select>
            ) : (
              <Input label="画像 ID" required value={profileId} onChange={(e) => setProfileId(e.target.value)} placeholder="UUID" />
            )}
          </div>
        </section>

        <section className="card stack">
          <h2 className="card-title">关联对象</h2>
          {templatesState === 'loading' && <Loading label="正在加载模板…" />}
          {templatesNotice && <InfoNotice message={templatesNotice} />}
          {templates.length > 0 && (
            <div className="grid-2">
              <Select label="模板" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                <option value="">请选择模板</option>
                {templates.map((t) => <option key={t.id} value={t.id}>{t.code} · {t.name}</option>)}
              </Select>
              <Select label="模板版本" value={templateVersionId} disabled={versionsState === 'loading' || !templateId} onChange={(e) => setTemplateVersionId(e.target.value)}>
                {versions.length === 0 ? <option value="">{versionsState === 'loading' ? '加载中…' : '暂无已发布版本'}</option>
                  : versions.map((v) => <option key={v.id} value={v.id}>v{v.versionNo} · {v.status}</option>)}
              </Select>
            </div>
          )}
          {versionsNotice && <InfoNotice message={versionsNotice} />}
          {templates.length === 0 && templatesState !== 'loading' && (
            <Input label="模板版本 ID（手工填写）" required value={templateVersionId} onChange={(e) => setTemplateVersionId(e.target.value)} hint="当前无法从服务端加载模板列表" />
          )}
        </section>

        {hasDynamicFields ? (
          <section className="card stack">
            <h2 className="card-title">数据字段</h2>
            <div className="grid-2">
              {fields.map((f) => (
                <Input
                  key={f.id}
                  label={`${f.label}${f.unit ? ` (${f.unit})` : ''}${f.required ? ' *' : ''}`}
                  value={fieldValues[f.path] ?? ''}
                  onChange={(e) => setField(f.path, e.target.value)}
                  placeholder={f.dataType === 'number' ? '0.0' : f.label}
                  type={f.dataType === 'number' ? 'number' : 'text'}
                  hint={f.rules && Object.keys(f.rules).length > 0 ? JSON.stringify(f.rules) : undefined}
                  required={f.required}
                />
              ))}
            </div>
            <details style={{ marginTop: 8 }}>
              <summary className="muted" style={{ cursor: 'pointer', fontSize: 12 }}>查看/编辑生成的 Payload JSON</summary>
              <Textarea label="Payload JSON" rows={8} spellCheck={false} value={payload} onChange={(e) => { setPayload(e.target.value); setJsonFeedback(null); }} error={jsonValid ? undefined : 'JSON 格式无效'} />
            </details>
          </section>
        ) : (
          <section className="card stack">
            <h2 className="card-title">Payload</h2>
            <Textarea label="Payload JSON" rows={14} spellCheck={false} value={payload} onChange={(e) => { setPayload(e.target.value); setJsonFeedback(null); }} hint={jsonValid ? '当前 JSON 合法。' : '当前 JSON 不合法，提交将被阻止。'} error={jsonValid ? undefined : 'JSON 格式无效'} />
            <div className="btn-row">
              <Button variant="secondary" type="button" onClick={() => { try { JSON.parse(payload); setJsonFeedback({ tone: 'ok', text: 'JSON 校验通过。' }); } catch (e) { setJsonFeedback({ tone: 'error', text: `JSON 格式无效：${e instanceof Error ? e.message : '无法解析'}` }); } }}>校验 JSON</Button>
              <Button variant="secondary" type="button" onClick={() => { try { setPayload(JSON.stringify(JSON.parse(payload), null, 2)); setJsonFeedback({ tone: 'ok', text: '已格式化' }); } catch (e) { setJsonFeedback({ tone: 'error', text: `格式无效：${e instanceof Error ? e.message : ''}` }); } }}>格式化 JSON</Button>
            </div>
            {jsonFeedback && (jsonFeedback.tone === 'ok' ? <SuccessNotice message={jsonFeedback.text} /> : <ErrorNotice message={jsonFeedback.text} />)}
          </section>
        )}

        <div className="btn-row">
          <Button type="submit" disabled={busy} aria-busy={busy}>{busy ? '保存中…' : '保存草稿'}</Button>
        </div>
      </form>
    </main>
  );
}