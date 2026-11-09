// Fetch-based Server-Sent Events client (SPEC §6).
//
// Why not EventSource: the server closes the stream after the terminal event,
// and EventSource would then auto-reconnect and replay forever. Here we parse
// the stream ourselves (id / event / data / retry / comment lines), reconnect
// with Last-Event-ID on drops, dedupe by seq (the server replays from the start
// anyway), and stop for good after run.completed / run.failed.

import type { RunEvent, RunEventType } from '../types';
import { runEventsUrl } from './api';

export interface SseMessage {
  id: string | null;
  event: string;
  data: string;
}

/** Incremental parser for the text/event-stream format (WHATWG HTML §9.2.6). */
export class SseParser {
  private buf = '';
  private event = '';
  private data: string[] = [];
  private hasData = false;
  lastEventId: string | null = null;
  retryMs: number | null = null;
  onComment: ((text: string) => void) | null = null;

  push(chunk: string): SseMessage[] {
    this.buf += chunk;
    const out: SseMessage[] = [];
    // A trailing CR may be the first half of a CRLF split across chunks: hold it.
    let text = this.buf;
    let hold = '';
    if (text.endsWith('\r')) {
      hold = '\r';
      text = text.slice(0, -1);
    }
    // Split on CRLF, LF or CR; keep the trailing partial line in the buffer.
    const lines = text.split(/\r\n|\n|\r/);
    this.buf = (lines.pop() ?? '') + hold;
    for (const line of lines) {
      if (line === '') {
        if (this.hasData) out.push({ id: this.lastEventId, event: this.event || 'message', data: this.data.join('\n') });
        this.event = '';
        this.data = [];
        this.hasData = false;
        continue;
      }
      if (line.startsWith(':')) {
        this.onComment?.(line.slice(1).trim());
        continue;
      }
      const idx = line.indexOf(':');
      const field = idx === -1 ? line : line.slice(0, idx);
      let value = idx === -1 ? '' : line.slice(idx + 1);
      if (value.startsWith(' ')) value = value.slice(1);
      switch (field) {
        case 'event':
          this.event = value;
          break;
        case 'data':
          this.data.push(value);
          this.hasData = true;
          break;
        case 'id':
          if (!value.includes('\u0000')) this.lastEventId = value;
          break;
        case 'retry':
          if (/^\d+$/.test(value)) this.retryMs = Number(value);
          break;
        default:
          break; // unknown fields are ignored per spec
      }
    }
    return out;
  }
}

export type ConnectionState = 'connecting' | 'open' | 'reconnecting' | 'closed';

export interface RunStreamHandlers {
  onEvent: (ev: RunEvent) => void;
  onConnection?: (state: ConnectionState, attempt: number) => void;
  /** Fatal (non-retryable) error, e.g. 404 for an unknown run. */
  onFatal?: (message: string) => void;
}

const KNOWN: ReadonlySet<RunEventType> = new Set(['run.started', 'stage.started', 'stage.completed', 'stage.failed', 'run.completed', 'run.failed', 'override']);
const TERMINAL: ReadonlySet<RunEventType> = new Set(['run.completed', 'run.failed']);
const STALL_MS = 45_000; // server pings every 15 s; three missed pings = reconnect

/** Subscribe to a run's event stream. Returns an unsubscribe function. */
export function subscribeRun(runId: string, handlers: RunStreamHandlers): () => void {
  let stopped = false;
  let maxSeq = 0;
  let lastId: string | null = null;
  let attempt = 0;
  let retryMs = 1500;
  let ctrl: AbortController | null = null;
  let stallTimer: ReturnType<typeof setTimeout> | null = null;

  const armStall = () => {
    if (stallTimer) clearTimeout(stallTimer);
    stallTimer = setTimeout(() => ctrl?.abort(), STALL_MS);
  };

  const run = async () => {
    while (!stopped) {
      handlers.onConnection?.(attempt === 0 ? 'connecting' : 'reconnecting', attempt);
      ctrl = new AbortController();
      let finished = false;
      try {
        const headers: Record<string, string> = { Accept: 'text/event-stream' };
        if (lastId) headers['Last-Event-ID'] = lastId;
        const res = await fetch(runEventsUrl(runId), { headers, signal: ctrl.signal, cache: 'no-store' });
        if (res.status === 404) {
          handlers.onFatal?.('This run does not exist.');
          stopped = true;
          break;
        }
        if (!res.ok || !res.body) throw new Error(`SSE HTTP ${res.status}`);
        handlers.onConnection?.('open', attempt);
        attempt = 0;
        const parser = new SseParser();
        parser.onComment = () => armStall();
        const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
        armStall();
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          armStall();
          for (const msg of parser.push(value)) {
            const seq = msg.id != null ? Number(msg.id) : NaN;
            if (!Number.isNaN(seq)) {
              if (seq <= maxSeq) continue; // replayed duplicate
              maxSeq = seq;
              lastId = msg.id;
            }
            if (!KNOWN.has(msg.event as RunEventType)) continue;
            let data: unknown;
            try {
              data = JSON.parse(msg.data);
            } catch {
              continue;
            }
            const ev = { seq: Number.isNaN(seq) ? maxSeq : seq, type: msg.event, data } as RunEvent;
            handlers.onEvent(ev);
            if (TERMINAL.has(ev.type)) finished = true;
          }
          if (parser.retryMs != null) retryMs = parser.retryMs;
          if (finished || stopped) break;
        }
        try {
          ctrl.abort();
        } catch {
          /* already closed */
        }
      } catch {
        if (stopped) break;
      } finally {
        if (stallTimer) clearTimeout(stallTimer);
      }
      if (finished) {
        stopped = true;
        break;
      }
      if (stopped) break;
      // Stream ended without a terminal event: back off and reconnect.
      attempt += 1;
      const wait = Math.min(10_000, retryMs * Math.min(attempt, 4));
      handlers.onConnection?.('reconnecting', attempt);
      await new Promise((r) => setTimeout(r, wait));
    }
    handlers.onConnection?.('closed', attempt);
  };

  void run();
  return () => {
    stopped = true;
    if (stallTimer) clearTimeout(stallTimer);
    ctrl?.abort();
  };
}
