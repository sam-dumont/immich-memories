import { api, type Messages } from './api';

const PREFERENCE_KEY = 'immich-memories.ui-language';

let current = $state<Messages>({ locale: 'en', messages: {} });

function preference(): string {
  try {
    return localStorage.getItem(PREFERENCE_KEY) ?? 'auto';
  } catch {
    return 'auto';
  }
}

export async function loadMessages(fetcher: typeof fetch): Promise<void> {
  current = await api<Messages>(`/i18n?preference=${encodeURIComponent(preference())}`, fetcher);
  document.documentElement.lang = current.locale;
}

export const locale = () => current.locale;

/** Translate an interface template from the shared `ui.po`; `{name}` placeholders are filled in. */
export function t(message: string, values: Record<string, string | number> = {}): string {
  const template = current.messages[message] || message;
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key]) : whole));
}

/** Mark a label stored in a table for extraction; `t` translates it where it is shown. */
export const N_ = (message: string) => message;
