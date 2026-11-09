import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useEffect } from 'react';
import { api } from '../lib/api';
import { cx } from '../lib/format';
import { useResource } from '../hooks/useResource';
import { ErrorBoundary } from './ErrorBoundary';

const NAV = [
  { to: '/', label: 'Process', end: true, match: (p: string) => p === '/' || p.startsWith('/runs/') },
  { to: '/dashboard', label: 'Dashboard', match: (p: string) => p.startsWith('/dashboard') },
  { to: '/reference', label: 'Reference data', match: (p: string) => p.startsWith('/reference') },
];

function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
      <rect width="32" height="32" rx="8" fill="#1a2233" />
      <path d="M10 8h9l4 4v12a1 1 0 0 1-1 1H10a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M12.5 18.5l2.5 2.5 4.5-5" fill="none" stroke="#4ade80" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function HealthBadge() {
  const health = useResource(() => api.health(), 'health', { intervalMs: 30_000 });
  const ok = health.data?.ok && !health.error;
  const label = health.loading && !health.data ? 'Connecting…' : ok ? (health.data?.mock ? 'Mock API' : health.data?.model ?? 'Online') : 'API offline';
  return (
    <span
      className="hidden items-center gap-2 rounded-full border border-ink-200 bg-white px-2.5 py-1 text-xs text-ink-600 md:inline-flex"
      title={ok ? `API healthy · model ${health.data?.model ?? '?'} · db ${health.data?.db ?? '?'}` : health.error ?? ''}
    >
      <span className={cx('h-1.5 w-1.5 rounded-full', health.loading && !health.data ? 'bg-pending' : ok ? 'bg-approve' : 'bg-reject')} aria-hidden />
      {label}
    </span>
  );
}

export function Layout() {
  const { pathname } = useLocation();
  useEffect(() => {
    const titles: Record<string, string> = { '/dashboard': 'Dashboard', '/reference': 'Reference data' };
    document.title = `${titles[pathname] ?? 'Process invoice'} · Invoice Desk`;
  }, [pathname]);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-ink-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-8 px-6">
          <NavLink to="/" className="flex items-center gap-2.5" aria-label="Invoice Desk home">
            <Logo />
            <span className="leading-tight">
              <span className="block text-[15px] font-semibold tracking-tight text-ink-950">Invoice Desk</span>
              <span className="block text-[11px] text-ink-500">Accounts payable · 2-way match</span>
            </span>
          </NavLink>
          <nav className="flex h-full items-stretch gap-1" aria-label="Primary">
            {NAV.map((n) => {
              const active = n.match(pathname);
              return (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  className={cx(
                    'relative flex items-center px-3 text-sm font-medium transition-colors',
                    active ? 'text-ink-950' : 'text-ink-500 hover:text-ink-900',
                  )}
                  aria-current={active ? 'page' : undefined}
                >
                  {n.label}
                  {active && <span className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-ink-900" aria-hidden />}
                </NavLink>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <HealthBadge />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1440px] px-6 py-6">
        <ErrorBoundary title="Could not render this page" resetKey={pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  );
}
