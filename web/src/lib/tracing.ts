// The web client's side of a trace: tiny, always loaded. The OpenTelemetry SDK itself is a
// separate chunk, fetched only when the server says it exports traces (#2888).
type Sdk = typeof import('./tracing-sdk');

let sdk: Sdk | null = null;

/** Ask the server whether it traces; load and start the tracer only if it does. */
export async function startTracing(fetcher: typeof fetch = fetch): Promise<void> {
  try {
    const response = await fetcher('/api/v1/telemetry', { headers: { accept: 'application/json' } });
    if (!response.ok || !((await response.json()) as { traces: boolean }).traces) return;
    sdk = await import('./tracing-sdk');
    sdk.start();
  } catch {
    // Tracing is a lens on the work, never a reason for the page to fail.
  }
}

/** `run` as one user action: its requests, and the server work they start, sit under it. */
export function action<T>(name: string, run: () => Promise<T>): Promise<T> {
  return sdk ? sdk.action(name, run) : run();
}

/** A page change between two client routes, named by route template (`/runs/[run_id]`). */
export function navigating(from: string | null, to: string | null): () => void {
  return sdk ? sdk.navigating(from, to) : () => {};
}

// Ids make every request its own name; the server scrubs too, this keeps names readable.
const IDS = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\b[0-9a-f]{16,}\b|\b\d{6,}\b|\b\d{8}_\d{6}_[0-9a-f]{4}\b/gi;

/** `path` with ids replaced by `{id}` and no query string. */
export const template = (path: string) => path.split('?')[0].replace(IDS, '{id}');
