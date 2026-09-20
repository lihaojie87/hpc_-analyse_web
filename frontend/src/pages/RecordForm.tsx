import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import { useAuth } from '../auth/store';
import { Button, ErrorNotice, InfoNotice, Input, Loading, Select, SuccessNotice, Textarea } from '../components/ui';

interface TemplateItem {
  id: string;
  code: string;
  name: string;
  status: string;
  revision: number;
}

interface TemplateVersionItem {
  id: string;
  versionNo: number;
  status: string;
  revision: number;
}

type LoadState = 'loading' | 'ready' | 'unavailable';

interface JsonFeedback {
  tone: 'ok' | 'error';
  text: string;
}

/**
 * Accept both response shapes the backend may use for list endpoints: a bare
 * array (current `GET /templates/{id}/versions`) or an `{ items: [...] }`
 * envelope (current `GET /templates`). This keeps the picker working whichever
 * shape the `template:read` rollout lands with.
 */
function extractList<T>(payload: unknown): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === 'object') {
    const items = (payload as { items?: unknown }).items;
    if (Array.isArray(items)) return items as T[];
  }
  return [];
}

/**
 * Turn a template-load failure into readable copy. A 403 is *expected* for
 * viewers (no `template:read`) and must degrade quietly — never surfaced as a
 * raw `FORBIDDEN` code and never crashing the page.
 */
function describeTemplateError(error: unknown): string {
  if (error instanceof ApiError && (error.status === 403 || error.code === 'FORBIDDEN')) {
    return '当前账号暂无模板读取权限，已切换为手工填写模板版本 ID。';
  }
  if (error instanceof ApiError) {
    return `模板列表加载失败：${error.message} 可手工填写模板版本 ID。`;
  }
  return '模板列表加载失败，可手工填写模板版本 ID。';
}

/**
 * Create-record form (UI-T03).
 *
 * - grouped into 基本信息 / 关联对象 / Payload;
 * - consumes `GET /api/v1/templates` (+ `.../versions`) so the user never has to
 *   type a template version id by hand — with a 403-safe manual fallback;
 * - validates/beautifies JSON and refuses to send a request for invalid JSON.
 */
export default function RecordForm(): JSX.Element {
  const { token } = useAuth();
  const navigate = useNavigate();

  const [stableKey, setStableKey] = useState('');
  const [softwareId, setSoftwareId] = useState('');
  const [profileId, setProfileId] = useState('');

  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [templatesState, setTemplatesState] = useState<LoadState>('loading');
  const [templatesNotice, setTemplatesNotice] = useState('');
  const [templateId, setTemplateId] = useState('');

  const [versions, setVersions] = useState<TemplateVersionItem[]>([]);
  const [versionsState, setVersionsState] = useState<LoadState>('unavailable');
  const [versionsNotice, setVersionsNotice] = useState('');
  const [templateVersionId, setTemplateVersionId] = useState('');

  const [payload, setPayload] = useState('{}');
  const [jsonFeedback, setJsonFeedback] = useState<JsonFeedback | null>(null);

  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  // Synchronous re-entrancy guard: set/read happen in the same tick, so a burst
  // of `requestSubmit()` calls cannot fire more than one request.
  const submittingRef = useRef(false);

  /** Load the template catalogue; degrade gracefully (no crash) when forbidden. */
  const loadTemplates = useCallback(async (): Promise<void> => {
    setTemplatesState('loading');
    setTemplatesNotice('');
    try {
      const data = await api<unknown>('/api/v1/templates');
      const list = extractList<TemplateItem>(data);
      setTemplates(list);
      setTemplatesState('ready');
      if (list.length === 0) {
        setTemplatesNotice('当前没有可用模板，可手工填写模板版本 ID。');
      } else {
        // Auto-select the first template so its versions load without extra effort.
        setTemplateId(list[0].id);
      }
    } catch (requestError: unknown) {
      setTemplates([]);
      setTemplatesState('unavailable');
      setTemplatesNotice(describeTemplateError(requestError));
    }
  }, [token]);

  useEffect(() => {
    void loadTemplates();
  }, [loadTemplates]);

  /** Load versions for the selected template so the user picks from a list. */
  useEffect(() => {
    if (!templateId) {
      setVersions([]);
      setVersionsState('unavailable');
      setVersionsNotice('');
      setTemplateVersionId('');
      return undefined;
    }
    let cancelled = false;
    setVersionsState('loading');
    setVersionsNotice('');
    api<unknown>(`/api/v1/templates/${encodeURIComponent(templateId)}/versions`)
      .then((data) => {
        if (cancelled) return;
        const list = extractList<TemplateVersionItem>(data);
        // Only a PUBLISHED template version can back a performance record.
        // Hide drafts/archived versions from the picker so users cannot
        // accidentally submit a record against an unpublished contract (the
        // backend enforces the same rule and returns 409 模板版本未发布).
        const published = list.filter((v) => v.status === "published");
        setVersions(published);
        setVersionsState("ready");
        setTemplateVersionId(published[0]?.id ?? "");
        setVersionsNotice(
          published.length === 0
            ? "该模板暂无已发布版本，请先发布模板版本或手工填写模板版本 ID。"
            : "",
        );
      })
      .catch((requestError: unknown) => {
        if (cancelled) return;
        setVersions([]);
        setVersionsState('unavailable');
        setTemplateVersionId('');
        setVersionsNotice(describeTemplateError(requestError));
      });
    return () => {
      cancelled = true;
    };
  }, [templateId, token]);

  /** Live JSON validity, used for the inline hint and the submit guard. */
  const jsonValid = useMemo<boolean>(() => {
    try {
      JSON.parse(payload);
      return true;
    } catch {
      return false;
    }
  }, [payload]);

  function validateJson(): void {
    try {
      JSON.parse(payload);
      setJsonFeedback({ tone: 'ok', text: 'JSON 校验通过。' });
    } catch (parseError: unknown) {
      setJsonFeedback({ tone: 'error', text: `JSON 格式无效：${parseError instanceof Error ? parseError.message : '无法解析'}` });
    }
  }

  function formatJson(): void {
    try {
      const parsed = JSON.parse(payload) as unknown;
      setPayload(JSON.stringify(parsed, null, 2));
      setJsonFeedback({ tone: 'ok', text: '已格式化（缩进 2 空格）。' });
    } catch (parseError: unknown) {
      setJsonFeedback({ tone: 'error', text: `JSON 格式无效，无法格式化：${parseError instanceof Error ? parseError.message : '无法解析'}` });
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submittingRef.current) return; // synchronous dedup for same-tick bursts
    setError('');

    if (!stableKey.trim() || !softwareId.trim() || !profileId.trim()) {
      setError('请填写基本信息中的必填项。');
      return;
    }
    if (!templateVersionId.trim()) {
      setError('请选择或填写模板版本 ID。');
      return;
    }

    // Invalid JSON → surface a readable error and DO NOT send a request.
    let parsedPayload: Record<string, unknown>;
    try {
      parsedPayload = JSON.parse(payload) as Record<string, unknown>;
    } catch {
      setJsonFeedback({ tone: 'error', text: 'Payload 不是合法的 JSON，已阻止提交（未发送请求）。' });
      setError('Payload 不是合法的 JSON，未发送请求，请修正后重试。');
      return;
    }

    submittingRef.current = true;
    setBusy(true);
    try {
      const created = await api<{ id: string }>('/api/v1/records', {
        method: 'POST',
        body: JSON.stringify({
          stableKey: stableKey.trim(),
          softwareId: softwareId.trim(),
          profileId: profileId.trim(),
          templateVersionId: templateVersionId.trim(),
          payload: parsedPayload,
        }),
      });
      navigate(`/records/${created.id}`);
    } catch (requestError: unknown) {
      setError(requestError instanceof ApiError ? requestError.message : '保存失败，请稍后重试。');
    } finally {
      submittingRef.current = false;
      setBusy(false);
    }
  }

  const showTemplateSelectors = templates.length > 0;
  const showManualVersionInput = templatesState !== 'loading' && templates.length === 0;

  return (
    <main className="stack">
      <div className="page-heading">
        <div>
          <h1>新建性能记录</h1>
          <p>分「基本信息 / 关联对象 / Payload」三部分填写。</p>
        </div>
        <Link className="button button-secondary" to="/records">返回列表</Link>
      </div>

      <form className="stack" onSubmit={submit} noValidate>
        {error && <ErrorNotice message={error} />}

        <section className="card stack">
          <h2 className="card-title">基本信息</h2>
          <div className="grid-2">
            <Input
              label="稳定主键 Stable Key"
              required
              value={stableKey}
              onChange={(event) => setStableKey(event.target.value)}
              placeholder="例如 cpu-gcc13-O3"
              autoFocus
            />
            <Input
              label="软件 ID"
              required
              value={softwareId}
              onChange={(event) => setSoftwareId(event.target.value)}
              placeholder="软件的唯一标识"
            />
            <Input
              label="画像 ID"
              required
              value={profileId}
              onChange={(event) => setProfileId(event.target.value)}
              placeholder="运行画像标识"
            />
          </div>
        </section>

        <section className="card stack">
          <h2 className="card-title">关联对象</h2>
          {templatesState === 'loading' && <Loading label="正在加载模板…" />}
          {templatesNotice && <InfoNotice message={templatesNotice} />}

          {showTemplateSelectors && (
            <div className="grid-2">
              <Select
                label="模板"
                value={templateId}
                onChange={(event) => setTemplateId(event.target.value)}
              >
                <option value="">请选择模板</option>
                {templates.map((template) => (
                  <option key={template.id} value={template.id}>{template.code} · {template.name}</option>
                ))}
              </Select>
              <Select
                label="模板版本"
                value={templateVersionId}
                disabled={versionsState === 'loading' || !templateId}
                onChange={(event) => setTemplateVersionId(event.target.value)}
              >
                {versions.length === 0 ? (
                  <option value="">{versionsState === 'loading' ? '加载中…' : '暂无版本'}</option>
                ) : (
                  versions.map((version) => (
                    <option key={version.id} value={version.id}>v{version.versionNo} · {version.status}</option>
                  ))
                )}
              </Select>
            </div>
          )}

          {versionsNotice && <InfoNotice message={versionsNotice} />}

          {showManualVersionInput && (
            <Input
              label="模板版本 ID（手工填写）"
              required
              value={templateVersionId}
              onChange={(event) => setTemplateVersionId(event.target.value)}
              hint="当前无法从服务端加载模板列表，请手工填写模板版本 ID 作为兜底。"
            />
          )}
        </section>

        <section className="card stack">
          <h2 className="card-title">Payload</h2>
          <Textarea
            label="Payload JSON"
            rows={14}
            spellCheck={false}
            value={payload}
            onChange={(event) => { setPayload(event.target.value); setJsonFeedback(null); }}
            hint={jsonValid ? '当前 JSON 合法。' : '当前 JSON 不合法，提交将被阻止。'}
            error={jsonValid ? undefined : 'JSON 格式无效'}
          />
          <div className="btn-row">
            <Button variant="secondary" type="button" onClick={validateJson}>校验 JSON</Button>
            <Button variant="secondary" type="button" onClick={formatJson}>格式化 JSON</Button>
          </div>
          {jsonFeedback && (jsonFeedback.tone === 'ok'
            ? <SuccessNotice message={jsonFeedback.text} />
            : <ErrorNotice message={jsonFeedback.text} />)}
        </section>

        <div className="btn-row">
          <Button type="submit" disabled={busy} aria-busy={busy}>{busy ? '保存中…' : '保存草稿'}</Button>
        </div>
      </form>
    </main>
  );
}
