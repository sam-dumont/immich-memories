import { locale, t } from './i18n.svelte';

/** "Updated 3 hours ago", in the interface language, for an answer the server worked out earlier. */
export function updatedAgo(when: string | null | undefined): string {
  if (!when) return '';
  const seconds = Math.round((new Date(when).getTime() - Date.now()) / 1000);
  const [value, unit]: [number, Intl.RelativeTimeFormatUnit] =
    Math.abs(seconds) < 60 ? [seconds, 'second']
    : Math.abs(seconds) < 3600 ? [Math.round(seconds / 60), 'minute']
    : Math.abs(seconds) < 86400 ? [Math.round(seconds / 3600), 'hour']
    : [Math.round(seconds / 86400), 'day'];
  const phrase = new Intl.RelativeTimeFormat(locale(), { numeric: 'auto' }).format(value, unit);
  return t('Updated {when}', { when: phrase });
}
