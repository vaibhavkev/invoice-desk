import { useEffect, useRef, type ReactNode } from 'react';
import { Button } from './ui';

/** Native <dialog> modal: focus trap, Esc to close and backdrop come for free. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  busy,
  confirmDisabled,
  tone = 'primary',
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busy?: boolean;
  confirmDisabled?: boolean;
  tone?: 'primary' | 'danger';
  onConfirm: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      cancelRef.current?.focus();
    } else if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current && !busy) onClose();
      }}
      className="m-auto w-[440px] max-w-[calc(100vw-2rem)] rounded-2xl border border-ink-200 bg-white p-0 text-ink-900 shadow-lift backdrop:bg-ink-950/30 backdrop:backdrop-blur-[1px]"
    >
      <div className="p-6">
        <h2 className="text-base font-semibold">{title}</h2>
        <div className="mt-2 text-sm leading-relaxed text-ink-600">{children}</div>
      </div>
      <div className="flex justify-end gap-2 border-t border-ink-100 bg-ink-50 px-6 py-3.5">
        <Button ref={cancelRef} variant="secondary" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant={tone === 'danger' ? 'danger' : 'primary'} onClick={onConfirm} disabled={busy || confirmDisabled}>
          {busy ? 'Working…' : confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}
