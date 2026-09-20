import { NavLink, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useAuth } from '../auth/store';
import { Button } from './ui';

interface NavItem { to: string; label: string; icon: string; admin?: boolean; }

const navItems: NavItem[] = [
  { to: '/dashboard', label: '数据看板', icon: '⌂' },
  { to: '/records', label: '性能记录', icon: '▦' },
  { to: '/records/new', label: '新建记录', icon: '+' },
  { to: '/profiles', label: '软件画像', icon: '◈' },
  { to: '/import', label: '飞书导入', icon: '⇩' },
  { to: '/data-description', label: '数据说明', icon: 'i' },
  { to: '/admin/users', label: '用户管理', icon: '⚙', admin: true },
  { to: '/admin/templates', label: '模板管理', icon: '▤', admin: true },
  { to: '/admin/software', label: '软件管理', icon: '◈', admin: true },
];

const ROLE_LABELS: Record<string, string> = { viewer: '仅查看', provider: '提供数据', admin: '管理员' };
function roleLabel(code: string): string {
  return ROLE_LABELS[code] ?? code;
}

export default function AppShell({ children }: { children: ReactNode }): JSX.Element {
  const location = useLocation();
  const { user, roles, logout } = useAuth();
  const displayName = user?.displayName?.trim() || user?.username || '未登录';
  const primaryRole = roles[0] ?? 'viewer';
  const isAdmin = roles.includes('admin');

  const current = [...navItems]
    .sort((left, right) => right.to.length - left.to.length)
    .find((item) => location.pathname === item.to || location.pathname.startsWith(`${item.to}/`));

  const caseRoute = location.pathname.startsWith('/cases/');
  const pageTitle = caseRoute ? '算例详情' : (current?.label ?? '工作台');

  const visibleItems = navItems.filter((item) => !item.admin || isAdmin);

  return (
    <div className="app-shell app-page">
      <aside className="app-sidebar">
        <div className="app-brand"><div className="app-brand-mark">H</div><div className="app-brand-title">HPC 性能目录</div><div className="app-brand-subtitle">Performance Platform</div></div>
        <nav className="app-nav" aria-label="主导航">
          {visibleItems.map((item) => <NavLink key={item.to} to={item.to} end={item.to === '/records'} className={({ isActive }) => `app-nav-link ${isActive ? 'active' : ''}`}><b aria-hidden="true">{item.icon}</b><span>{item.label}</span></NavLink>)}
        </nav>
        <div className="app-sidebar-footer">数据质量与发布控制台</div>
      </aside>
      <section className="app-main">
        <header className="app-topbar">
          <div className="app-topbar-title">{pageTitle}</div>
          <div className="app-topbar-actions">
            <div className="app-user">
              <span className="app-user-name">{displayName}</span>
              <span className="role-badge app-user-role">{roleLabel(primaryRole)}</span>
            </div>
            <Button variant="ghost" onClick={() => { void logout(); }}>退出登录</Button>
          </div>
        </header>
        <main className="app-content">{children}</main>
      </section>
    </div>
  );
}