import { api, type Messages } from './api';

const PREFERENCE_KEY = 'immich-memories.ui-language';

let current = $state<Messages>({ locale: 'en', messages: {}, languages: [] });

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
export const languages = () => current.languages;
export const chosenLanguage = () => preference();

/** Keep this browser's interface language ("auto" follows the browser) and load its words. */
export async function chooseLanguage(code: string): Promise<void> {
  try {
    localStorage.setItem(PREFERENCE_KEY, code);
  } catch {
    // A browser that keeps nothing still switches for this page.
  }
  await loadMessages(fetch);
}

/** Translate an interface template from the shared `ui.po`; `{name}` placeholders are filled in. */
export function t(message: string, values: Record<string, string | number> = {}): string {
  const template = current.messages[message] || message;
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key]) : whole));
}

/** Mark a label stored in a table for extraction; `t` translates it where it is shown. */
export const N_ = (message: string) => message;
