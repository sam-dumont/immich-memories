import { loadMessages } from '$lib/i18n.svelte';

// A client-only app: the Python server hands out index.html and the JSON API.
export const ssr = false;
export const prerender = false;

export const load = async ({ fetch }) => {
  const [, session, health] = await Promise.all([
    loadMessages(fetch),
    fetch('/api/v1/session').then((response) => response.json()),
    fetch('/health/live').then((response) => response.ok ? response.json() : null).catch(() => null),
  ]);
  return { session, version: typeof health?.version === 'string' ? health.version : null };
};
