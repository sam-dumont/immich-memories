import { loadMessages } from '$lib/i18n.svelte';

// A client-only app: the Python server hands out index.html and the JSON API.
export const ssr = false;
export const prerender = false;

export const load = async ({ fetch }) => {
  await loadMessages(fetch);
};
