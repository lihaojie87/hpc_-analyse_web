import {
  type FormEvent,
  type MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Link, useParams } from 'react-router-dom';

import { ApiError, api } from '../api/client';
import { useAuth } from '../auth/store';
import {
  Button,
  ErrorNotice,
  InfoNotice,
  Loading,
  StatusBadge,
  SuccessNotice,
  Textarea,
} from '../components/ui';
import { NameWithId, PayloadView } from '../components/PayloadView';

/**
 * A single performance record as returned by `GET /api/v1/records/{id}` and
 * `PATCH /api/v1/records/{id}` (`catalog_service.record_dict`).
 *
 * `etag` is the strong, resource-bound validator `"record-<id>-<revision>"` that
 * the backend's `PATCH` handler parses from the `If-Match` header.
 */
interface RecordItem {
  id: string;
  stableKey: string;
  softwareId: string;
  softwareName?: string | null;
  profileId: string;
  profileName?: string | null;
  templateVersionId: string;
  templateName?: string | null;
  ownerUserId: string;
  lifecycleStatus: string;
  revision: number;
  payload: Record<string, unknown>;
  etag: string;
}

type LoadState = 'loading' | 'ready' | 'error';

/** Save lifecycle so the footer can render an explicit 保存中/成功/失败 affordance. */
type SaveState = 'idle' | 'saving' | 'success' | 'error';

interface JsonFeedback {
  tone: 'ok' | 'error';
  text: string;
}

/** Canonical editor text for a payload (2-space indent) — the dirty baseline. */
function pretty(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2);
}

/**
 * Record detail editor (UI-T04).
 *
 * - shows record metadata (stable key, software, profile, template version,
 *   owner), a lifecycle status tag, the live `revision` / `ETag` and a
 *   "返回列表" entry;
 * - edits the payload as JSON with validate / format helpers;
 * - keeps `If-Match` optimistic concurrency on every save — a stale ETag is
 *   rejected by the backend (HTTP 412 `PRECONDITION_FAILED`) and surfaced as a
 *   *high-visibility* conflict banner that preserves the local draft and offers
 *   two explicit recovery flows ("重载最新" / "放弃覆盖");
 * - surfaces 保存中 / 成功 / 失败 states and guards unsaved navigation.
 */
export default function RecordDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>();
  const { token } = useAuth();

  const [record, setRecord] = useState<RecordItem | null>(null);
  const [payload, setPayload] = useState<string>('{}');
  /** Editor text considered "saved"; `payload !== savedText` means dirty. */
  const [savedText, setSavedText] = useState<string>('{}');
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [loadError, setLoadError] = useState<string>('');
  const [conflict, setConflict] = useState<boolean>(false);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [saveMessage, setSaveMessage] = useState<string>('');
  const [jsonFeedback, setJsonFeedback] = useState<JsonFeedback | null>(null);
  // Synchronous re-entrancy guard: set/read happen in the same tick so a burst
  // of `requestSubmit()` calls cannot fire more than one PATCH.
  const submittingRef = useRef<boolean>(false);

  const applyLoaded = useCallback((latest: RecordItem): void => {
    const text = pretty(latest.payload);
    setRecord(latest);
    setPayload(text);
    setSavedText(text);
    setConflict(false);
    setSaveState('idle');
    setSaveMessage('');
    setJsonFeedback(null);
  }, []);

  /** Fetch the record and reset the editor to the server snapshot. */
  const load = useCallback(async (): Promise<void> => {
    if (!id) {
      setLoadError('记录 ID 缺失');
      setLoadState('error');
      return;
    }
    setLoadState('loading');
    setLoadError('');
    try {
      const latest = await api<RecordItem>(`/api/v1/records/${encodeURIComponent(id)}`);
      applyLoaded(latest);
      setLoadState('ready');
    } catch (requestError: unknown) {
      setLoadError(requestError instanceof Error ? requestError.message : '加载失败');
      setLoadState('error');
    }
  }, [id, token, applyLoaded]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty: boolean = record !== null && payload !== savedText;

  /** Live JSON validity, used for the inline hint and the submit guard. */
  const jsonValid = useMemo<boolean>(() => {
    try {
      JSON.parse(payload);
      return true;
    } catch {
      return false;
    }
  }, [payload]);

  /**
   * Live parse of the editor text for the read-only structured preview. Only
   * set when the JSON is valid and a non-array object, so the preview tracks
   * the editable draft without ever blocking the save flow.
   */
  const parsedPreview = useMemo<Record<string, unknown> | null>(() => {
    if (!jsonValid) return null;
    try {
      const parsed = JSON.parse(payload) as unknown;
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : null;
    } catch {
      return null;
    }
  }, [payload, jsonValid]);

  // Warn on hard navigation (tab close / reload) while the draft is dirty.
  useEffect(() => {
    if (!dirty) return undefined;
    const handler = (event: BeforeUnloadEvent): void => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  /** Intercept the in-app "返回列表" link when there are unsaved changes. */
  function guardLeave(event: MouseEvent<HTMLAnchorElement>): void {
    if (dirty && !window.confirm('当前有未保存的修改，返回列表将丢失这些修改。确认离开？')) {
      event.preventDefault();
    }
  }

  async function save(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!record || conflict) return; // never blindly re-save a conflicted draft
    if (submittingRef.current) return; // synchronous dedup for same-tick bursts

    let parsedPayload: Record<string, unknown>;
    try {
      parsedPayload = JSON.parse(payload) as Record<string, unknown>;
    } catch {
      setJsonFeedback({ tone: 'error', text: 'Payload 不是合法的 JSON，已阻止提交（未发送请求）。' });
      setSaveState('error');
      setSaveMessage('Payload 不是合法的 JSON，未发送请求，请修正后重试。');
      return;
    }

    submittingRef.current = true;
    setSaveState('saving');
    setSaveMessage('正在保存…');
    try {
      const next = await api<RecordItem>(`/api/v1/records/${encodeURIComponent(record.id)}`, {
        method: 'PATCH',
        // Optimistic concurrency: the backend rejects a stale validator with 412.
        headers: { 'If-Match': record.etag },
        body: JSON.stringify({ payload: parsedPayload }),
      });
      applyLoaded(next);
      setSaveState('success');
      setSaveMessage(`保存成功，revision 已更新为 ${next.revision}。`);
    } catch (requestError: unknown) {
      const message = requestError instanceof Error ? requestError.message : '保存失败，请稍后重试。';
      if (requestError instanceof ApiError && requestError.code === 'PRECONDITION_FAILED') {
        // Keep the user's draft in the editor. They must explicitly pick
        // "重载最新" or "放弃覆盖" before another save — never a silent overwrite.
        setConflict(true);
        setSaveState('error');
        setSaveMessage('检测到并发冲突：记录已被其他用户修改，你的修改未被保存。');
      } else {
        setSaveState('error');
        setSaveMessage(message);
      }
    } finally {
      submittingRef.current = false;
    }
  }

  /** Conflict recovery A: pull the newest server version and adopt it. */
  function reloadLatest(): void {
    void load();
  }

  /** Conflict recovery B: discard local edits, revert to the loaded snapshot. */
  function discardLocalChanges(): void {
    setPayload(savedText);
    setConflict(false);
    setSaveState('idle');
    setSaveMessage('');
    setJsonFeedback(null);
  }

  function validateJson(): void {
    try {
      JSON.parse(payload);
      setJsonFeedback({ tone: 'ok', text: 'JSON 校验通过。' });
    } catch (parseError: unknown) {
      setJsonFeedback({
        tone: 'error',
        text: `JSON 格式无效：${parseError instanceof Error ? parseError.message : '无法解析'}`,
      });
    }
  }

  function formatJson(): void {
    try {
      const parsed = JSON.parse(payload) as unknown;
      setPayload(JSON.stringify(parsed, null, 2));
      setJsonFeedback({ tone: 'ok', text: '已格式化（缩进 2 空格）。' });
    } catch (parseError: unknown) {
      setJsonFeedback({
        tone: 'error',
        text: `JSON 格式无效，无法格式化：${parseError instanceof Error ? parseError.message : '无法解析'}`,
      });
    }
  }

  if (loadState === 'loading' && !record) {
    return (
      <main className="stack">
        <Loading label="正在加载记录…" />
      </main>
    );
  }

  if (loadState === 'error' && !record) {
    return (
      <main className="stack">
        <div className="page-heading">
          <div>
            <h1>记录详情</h1>
            <p>无法加载该记录。</p>
          </div>
          <Link className="button button-secondary" to="/records">返回列表</Link>
        </div>
        <ErrorNotice message={loadError} />
        <div className="btn-row">
          <Button type="button" onClick={() => { void load(); }}>重试</Button>
        </div>
      </main>
    );
  }

  if (!record) {
    return (
      <main className="stack">
        <div className="page-heading">
          <div>
            <h1>记录详情</h1>
            <p>记录不存在或不可见。</p>
          </div>
        </div>
        <InfoNotice message="未找到该记录。" />
        <div className="btn-row">
          <Link className="button button-secondary" to="/records">返回列表</Link>
        </div>
      </main>
    );
  }

  const busy = saveState === 'saving';

  return (
    <main className="stack">
      <div className="page-heading">
        <div>
          <h1>{record.stableKey}</h1>
          <p>
            查看并编辑记录数据；保存时使用 <code className="mono-inline">If-Match</code> 乐观并发控制。
          </p>
        </div>
        <Link className="button button-secondary" to="/records" onClick={guardLeave}>
          返回列表
        </Link>
      </div>

      {/* ---- 记录元信息卡片：状态标签 + revision / ETag 展示 ---- */}
      <section className="card stack">
        <h2 className="card-title">记录元信息</h2>
        <dl className="meta-list">
          <div className="meta-item">
            <dt>Stable Key</dt>
            <dd className="mono" data-testid="record-stable-key">{record.stableKey}</dd>
          </div>
          <div className="meta-item">
            <dt>软件</dt>
            <dd data-testid="record-software-id"><NameWithId name={record.softwareName} id={record.softwareId} /></dd>
          </div>
          <div className="meta-item">
            <dt>画像</dt>
            <dd data-testid="record-profile-id"><NameWithId name={record.profileName} id={record.profileId} /></dd>
          </div>
          <div className="meta-item">
            <dt>模板版本</dt>
            <dd data-testid="record-template-version-id"><NameWithId name={record.templateName} id={record.templateVersionId} /></dd>
          </div>
          <div className="meta-item">
            <dt>所有者</dt>
            <dd className="mono" data-testid="record-owner">{record.ownerUserId || '—'}</dd>
          </div>
          <div className="meta-item">
            <dt>状态</dt>
            <dd data-testid="record-status"><StatusBadge value={record.lifecycleStatus} /></dd>
          </div>
          <div className="meta-item">
            <dt>Revision</dt>
            <dd className="mono" data-testid="record-revision">{record.revision}</dd>
          </div>
          <div className="meta-item">
            <dt>ETag</dt>
            <dd className="mono meta-etag" data-testid="record-etag">{record.etag}</dd>
          </div>
        </dl>
      </section>

      {/* ---- 高可见度并发冲突提示 + 两条恢复流程 ---- */}
      {conflict && (
        <section className="conflict-banner" role="alert" data-testid="conflict-banner" aria-live="assertive">
          <h2>检测到并发冲突，你的修改尚未保存</h2>
          <p>
            该记录已被其他用户修改（服务器上的 revision 已前移），你的保存请求已被拒绝，
            <strong>本地草稿仍然保留在下方编辑区</strong>，不会被静默覆盖。请选择：
          </p>
          <div className="btn-row">
            <Button type="button" variant="primary" onClick={reloadLatest} disabled={busy}>
              重载最新
            </Button>
            <Button type="button" variant="secondary" onClick={discardLocalChanges} disabled={busy}>
              放弃覆盖
            </Button>
          </div>
          <p className="muted">
            「重载最新」将拉取服务器最新版本并载入编辑器（放弃本地草稿）；「放弃覆盖」将撤销本地修改，
            恢复到上次加载的内容且不覆盖服务器。
          </p>
        </section>
      )}

      {/* ---- Payload 结构化只读预览（随编辑区实时解析，不参与保存） ---- */}
      {parsedPreview && (
        <section className="card stack" aria-label="Payload 结构化预览">
          <div className="section-heading">
            <h2 className="card-title">Payload 结构化预览</h2>
            <span className="muted">只读 · 实时反映下方编辑区</span>
          </div>
          <PayloadView payload={parsedPreview} />
        </section>
      )}

      {/* ---- Payload 编辑区 ---- */}
      <form className="stack" onSubmit={save} noValidate>
        <section className="card stack">
          <div className="editor-toolbar">
            <h2 className="card-title">Payload</h2>
            {dirty && <span className="dirty-flag" data-testid="dirty-flag">● 有未保存的修改</span>}
          </div>
          <Textarea
            label="Payload JSON"
            data-testid="payload-editor"
            rows={16}
            spellCheck={false}
            value={payload}
            onChange={(event) => { setPayload(event.target.value); setJsonFeedback(null); }}
            hint={jsonValid ? '当前 JSON 合法。' : '当前 JSON 不合法，保存将被阻止。'}
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
          <Button type="submit" disabled={busy || conflict} aria-busy={busy}>
            {busy ? '保存中…' : '保存修改'}
          </Button>
          {conflict && <span className="muted">存在未解决的冲突，请先「重载最新」或「放弃覆盖」。</span>}
        </div>

        {/* ---- 保存中 / 成功 / 失败 状态反馈 ---- */}
        <div className="save-status" data-testid="save-status" aria-live="polite">
          {saveState === 'saving' && <InfoNotice message="保存中…" />}
          {saveState === 'success' && <SuccessNotice message={saveMessage} />}
          {saveState === 'error' && <ErrorNotice message={saveMessage} />}
        </div>
      </form>
    </main>
  );
}
