import { useEffect, useRef, useState } from 'react';
import { ExternalLink, FileText } from 'lucide-react';
import { Card, CardHeader } from '../ui';

const RENDER_WAIT_MS = 2000;

/** Small inline preview of the input PDF so the reviewer sees what went in. */
export function PdfPreview({ src, name, note }: { src: string | null; name?: string | null; note?: string }) {
  return (
    <Card>
      <CardHeader
        title="Input document"
        subtitle={name ?? undefined}
        right={
          src ? (
            <a href={src} target="_blank" rel="noreferrer" className="mt-0.5 inline-flex shrink-0 items-center gap-1 text-xs font-medium text-ink-600 hover:text-ink-950">
              Open <ExternalLink className="h-3 w-3" aria-hidden />
            </a>
          ) : undefined
        }
      />
      <div className="p-3">
        <div className="relative aspect-[1/1.3] w-full overflow-hidden rounded-lg border border-ink-200 bg-ink-50">
          {src ? (
            <PdfFrame key={src} src={src} name={name} />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-ink-400">
              <FileText className="h-6 w-6" aria-hidden />
              <p className="text-xs">{note ?? 'The PDF you run appears here.'}</p>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

/**
 * Embedded viewers fail silently: browsers fire no `error` for a PDF they cannot show,
 * and the frame just stays on an empty document. So also check its contents on load and
 * after a short wait. A null document means a cross-origin viewer, which is working. The
 * link is a small pill rather than a cover, so a wrong guess never hides a good preview.
 */
function PdfFrame({ src, name }: { src: string; name?: string | null }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [blank, setBlank] = useState(navigator.pdfViewerEnabled === false);
  const check = () => {
    const doc = frame.current?.contentDocument;
    setBlank(!!doc && !doc.body?.childElementCount);
  };

  useEffect(() => {
    const t = setTimeout(check, RENDER_WAIT_MS);
    return () => clearTimeout(t);
  }, []);

  return (
    <>
      <iframe ref={frame} src={`${src}#toolbar=0&navpanes=0&view=FitH`} title={name ? `Preview of ${name}` : 'Invoice preview'} className="h-full w-full" onLoad={check} onError={() => setBlank(true)} />
      {blank && (
        <div className="absolute inset-x-0 bottom-3 flex justify-center px-3">
          <a href={src} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-md border border-ink-200 bg-white px-2.5 py-1.5 text-[13px] font-medium text-ink-900 shadow-card hover:border-ink-300">
            Open PDF in a new tab <ExternalLink className="h-3 w-3" aria-hidden />
          </a>
        </div>
      )}
    </>
  );
}
