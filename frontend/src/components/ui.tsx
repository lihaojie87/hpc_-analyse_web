import { useId } from 'react';
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost';
export function Button({ variant = 'primary', className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }): JSX.Element {
  return <button className={`button button-${variant} ${className}`.trim()} {...props} />;
}

/**
 * Text input with an *explicitly associated* label (`htmlFor` + `id`, backed by
 * `useId`) so assistive tech and automated checks can bind the field to its
 * label even when more than one instance is rendered.
 */
export function Input({ label, hint, error, id, ...props }: InputHTMLAttributes<HTMLInputElement> & { label?: string; hint?: string; error?: string }): JSX.Element {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const errorId = `${inputId}-error`;
  const hintId = `${inputId}-hint`;
  const describedBy = error ? errorId : hint ? hintId : undefined;
  return (
    <label className="field" htmlFor={inputId}>
      <span className="field-label">{label}</span>
      <input id={inputId} className="input" aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...props} />
      {error ? <span id={errorId} className="notice notice-error" role="alert">{error}</span> : hint ? <span id={hintId} className="field-hint">{hint}</span> : null}
    </label>
  );
}

/** Native select with the same label/hint/error wiring as {@link Input}. */
export function Select({ label, hint, error, id, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label?: string; hint?: string; error?: string; children?: ReactNode }): JSX.Element {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const errorId = `${inputId}-error`;
  const hintId = `${inputId}-hint`;
  const describedBy = error ? errorId : hint ? hintId : undefined;
  return (
    <label className="field" htmlFor={inputId}>
      <span className="field-label">{label}</span>
      <select id={inputId} className="input" aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...props}>
        {children}
      </select>
      {error ? <span id={errorId} className="notice notice-error" role="alert">{error}</span> : hint ? <span id={hintId} className="field-hint">{hint}</span> : null}
    </label>
  );
}

/** Multi-line input with the same label/hint/error wiring as {@link Input}. */
export function Textarea({ label, hint, error, id, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string; hint?: string; error?: string }): JSX.Element {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const errorId = `${inputId}-error`;
  const hintId = `${inputId}-hint`;
  const describedBy = error ? errorId : hint ? hintId : undefined;
  return (
    <label className="field" htmlFor={inputId}>
      <span className="field-label">{label}</span>
      <textarea id={inputId} className="input" aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...props} />
      {error ? <span id={errorId} className="notice notice-error" role="alert">{error}</span> : hint ? <span id={hintId} className="field-hint">{hint}</span> : null}
    </label>
  );
}

const statusTone: Record<string, string> = { published: 'success', approved: 'success', active: 'success', draft: 'neutral', staging: 'warning', awaiting_review: 'warning', rejected: 'danger', deleted: 'danger' };
export function StatusBadge({ value }: { value: string }): JSX.Element {
  const tone = statusTone[value] ?? 'neutral';
  return <span className={`status-badge status-badge-${tone}`}>{value.replaceAll('_', ' ')}</span>;
}

export function Loading({ label = '正在加载…' }: { label?: string }): JSX.Element { return <div className="loading" role="status">{label}</div>; }
export function Empty({ title = '暂无数据', action }: { title?: string; action?: ReactNode }): JSX.Element { return <div className="empty-state"><p>{title}</p>{action}</div>; }
export function ErrorNotice({ message }: { message: string }): JSX.Element { return <div className="notice notice-error" role="alert">{message}</div>; }
export function SuccessNotice({ message }: { message: string }): JSX.Element { return <div className="notice notice-success" role="status">{message}</div>; }
export function InfoNotice({ message }: { message: string }): JSX.Element { return <div className="notice notice-info" role="status">{message}</div>; }
