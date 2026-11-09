import { useRef, useState, type DragEvent, type KeyboardEvent } from 'react';
import { CloudUpload, LoaderCircle, Play } from 'lucide-react';
import { cx, titleParts } from '../../lib/format';
import type { Sample } from '../../types';
import { Card, CardHeader, DecisionChip, Skeleton, EmptyState } from '../ui';

const MAX_BYTES = 15 * 1024 * 1024;

export function DropZone({ onFile, busy, onReject }: { onFile: (f: File) => void; busy: boolean; onReject: (msg: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const accept = (f: File | undefined | null) => {
    if (!f) return;
    const isPdf = f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf');
    if (!isPdf) return onReject(`${f.name} is not a PDF.`);
    if (f.size > MAX_BYTES) return onReject(`${f.name} is ${(f.size / 1048576).toFixed(1)} MB; the limit is 15 MB.`);
    onFile(f);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (busy) return;
    accept(e.dataTransfer.files?.[0]);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      input.current?.click();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Upload an invoice PDF: drop a file or press Enter to browse"
      aria-disabled={busy}
      onKeyDown={onKey}
      onClick={() => !busy && input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        if (!over) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={cx(
        'flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-5 text-center transition-colors',
        over ? 'border-running bg-running-soft' : 'border-ink-200 bg-ink-50/60 hover:border-ink-300 hover:bg-ink-50',
        busy && 'cursor-wait opacity-60',
      )}
    >
      {busy ? <LoaderCircle className="h-5 w-5 animate-spin text-ink-500" aria-hidden /> : <CloudUpload className={cx('h-5 w-5', over ? 'text-running' : 'text-ink-500')} aria-hidden />}
      <p className="mt-2 text-[13px] font-medium text-ink-900">{over ? 'Drop to process' : 'Drop an invoice PDF'}</p>
      <p className="text-xs text-ink-500">or click to browse · PDF up to 15 MB</p>
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(e) => {
          accept(e.target.files?.[0]);
          e.target.value = '';
        }}
      />
    </div>
  );
}

export function SampleList({
  samples,
  loading,
  error,
  activeSampleId,
  startingId,
  onPick,
}: {
  samples: Sample[] | null;
  loading: boolean;
  error: string | null;
  activeSampleId: string | null;
  startingId: string | null;
  onPick: (s: Sample) => void;
}) {
  const sorted = samples ? [...samples].sort((a, b) => a.demo_order - b.demo_order) : null;
  return (
    <Card>
      <CardHeader title="Sample invoices" subtitle="Click to run. Ordered for the demo." />
      <div className="px-2 pb-2 pt-2">
        {loading && !sorted && (
          <div className="space-y-1 px-2 py-1">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        )}
        {!loading && !sorted && <EmptyState title="Samples unavailable" body={error ?? 'Could not load /api/samples.'} className="py-6" />}
        {sorted && sorted.length === 0 && <EmptyState title="No samples configured" body="data/samples.json is empty." className="py-6" />}
        {sorted && sorted.length > 0 && (
          <ul className="space-y-0.5">
            {sorted.map((s) => {
              const [head, tail] = titleParts(s.title);
              const active = s.id === activeSampleId;
              const starting = s.id === startingId;
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => onPick(s)}
                    disabled={!!startingId}
                    title={s.notes}
                    className={cx(
                      'group flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors disabled:cursor-wait',
                      active ? 'bg-ink-100' : 'hover:bg-ink-50',
                    )}
                  >
                    <span className={cx('flex h-7 w-11 shrink-0 items-center justify-center rounded-md border font-mono text-[11px] font-semibold', active ? 'border-ink-900 bg-ink-900 text-white' : 'border-ink-200 bg-white text-ink-700')}>
                      {starting ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden /> : s.id}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium text-ink-900">{head}</span>
                      {tail && <span className="block truncate text-xs text-ink-500">{tail}</span>}
                    </span>
                    <span className="flex shrink-0 items-center">
                      <span className="group-hover:hidden group-focus-visible:hidden">
                        <DecisionChip decision={s.expected_decision} size="xs" />
                      </span>
                      <span className="hidden items-center gap-1 text-xs font-medium text-ink-700 group-hover:inline-flex group-focus-visible:inline-flex">
                        <Play className="h-3 w-3" aria-hidden /> Run
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <p className="border-t border-ink-100 px-5 py-2.5 text-[11px] text-ink-400">Chips show the expected outcome on a fresh ledger.</p>
    </Card>
  );
}
