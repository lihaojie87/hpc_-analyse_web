import type { ReactNode } from 'react';
export default function AuthLayout({ title, children }: { title: string; children: ReactNode }): JSX.Element {
  return <div className="auth-page"><section className="auth-aside"><div><div className="app-brand-mark">H</div><h1>让性能数据<br />可发现、可复用。</h1><p>统一管理 HPC 软件性能记录、数据质量与版本发布，让每一次基准测试都能沉淀为可靠资产。</p></div><small>HPC Performance Platform · 0.1.0</small></section><section className="auth-panel"><div className="auth-card"><h2>{title}</h2>{children}</div></section></div>;
}
