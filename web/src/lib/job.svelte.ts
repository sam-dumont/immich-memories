import type { JobView } from './api';

type Connection = 'connecting' | 'live' | 'reconnecting' | 'unauthorized';
let connections = $state<Record<string, Connection>>({});

export const jobConnection = (id: string): Connection | undefined => connections[id];

/** Keep the saved job authoritative even after sleep, a lost stream or an expired login. */
export function followJob(id: string, onUpdate: (job: JobView) => void): () => void {
  const url = `/api/v1/jobs/${encodeURIComponent(id)}`;
  const source = new EventSource(`${url}/events`);
  let stopped = false;
  let request: AbortController | undefined;
  connections[id] = 'connecting';

  function stop() {
    stopped = true;
    source.close();
    request?.abort();
    clearInterval(poll);
    document.removeEventListener('visibilitychange', visible);
  }

  function accept(job: JobView) {
    if (stopped) return;
    onUpdate(job);
    if (job.status !== 'running') {
      stop();
      delete connections[id];
    }
  }

  async function refresh() {
    if (stopped || request || document.hidden) return;
    const pending = new AbortController();
    request = pending;
    const timeout = setTimeout(() => pending.abort(), 10000);
    try {
      const response = await fetch(url, { signal: pending.signal, cache: 'no-store' });
      if (stopped) return;
      if (response.status === 401 || response.status === 403) {
        connections[id] = 'unauthorized';
        stop();
        return;
      }
      if (!response.ok) throw new Error('Job status unavailable');
      accept(await response.json() as JobView);
    } catch {
      if (!stopped) connections[id] = 'reconnecting';
    } finally {
      clearTimeout(timeout);
      request = undefined;
    }
  }

  function visible() {
    if (!document.hidden) void refresh();
  }

  const poll = setInterval(() => void refresh(), 15000);
  document.addEventListener('visibilitychange', visible);
  source.onopen = () => { if (!stopped) connections[id] = 'live'; };
  source.onmessage = (event) => {
    try {
      if (!stopped) connections[id] = 'live';
      accept(JSON.parse(event.data) as JobView);
    } catch {
      if (!stopped) connections[id] = 'reconnecting';
      void refresh();
    }
  };
  source.onerror = () => {
    if (stopped) return;
    connections[id] = 'reconnecting';
    void refresh();
  };
  return () => { stop(); delete connections[id]; };
}
