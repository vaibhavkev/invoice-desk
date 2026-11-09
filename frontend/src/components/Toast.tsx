import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import { CircleAlert, CircleCheck, Info, X } from 'lucide-react';
import { cx } from '../lib/format';

type Tone = 'error' | 'success' | 'info';
interface Toast {
  id: number;
  tone: Tone;
  title: string;
  message?: string;
}

interface ToastApi {
  push: (t: Omit<Toast, 'id'>) => void;
  error: (title: string, message?: string) => void;
  success: (title: string, message?: string) => void;
  info: (title: string, message?: string) => void;
}

const Ctx = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);

  const dismiss = useCallback((id: number) => setToasts((ts) => ts.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (t: Omit<Toast, 'id'>) => {
      const id = next.current++;
      setToasts((ts) => {
        // Collapse identical consecutive toasts (e.g. repeated network errors).
        if (ts.some((x) => x.title === t.title && x.message === t.message)) return ts;
        return [...ts.slice(-3), { ...t, id }];
      });
      setTimeout(() => dismiss(id), t.tone === 'error' ? 7000 : 4000);
    },
    [dismiss],
  );
  const api = useMemo<ToastApi>(
    () => ({
      push,
      error: (title, message) => push({ tone: 'error', title, message }),
      success: (title, message) => push({ tone: 'success', title, message }),
      info: (title, message) => push({ tone: 'info', title, message }),
    }),
    [push],
  );

  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-[360px] flex-col gap-2" role="region" aria-label="Notifications" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto flex animate-fade-up items-start gap-3 rounded-xl border border-ink-200 bg-white p-3.5 shadow-lift" role={t.tone === 'error' ? 'alert' : 'status'}>
            <span className={cx('mt-0.5', t.tone === 'error' ? 'text-reject' : t.tone === 'success' ? 'text-approve' : 'text-running')}>
              {t.tone === 'error' ? <CircleAlert className="h-4 w-4" /> : t.tone === 'success' ? <CircleCheck className="h-4 w-4" /> : <Info className="h-4 w-4" />}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-ink-900">{t.title}</p>
              {t.message && <p className="mt-0.5 break-words text-[13px] text-ink-500">{t.message}</p>}
            </div>
            <button type="button" onClick={() => dismiss(t.id)} className="rounded p-0.5 text-ink-400 hover:text-ink-700" aria-label="Dismiss notification">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): ToastApi {
  const v = useContext(Ctx);
  if (!v) throw new Error('useToast outside ToastProvider');
  return v;
}
