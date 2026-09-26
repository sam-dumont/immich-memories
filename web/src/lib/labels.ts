import { N_, t } from './i18n.svelte';

// The msgids the server pages already use, so every language's translation carries over.
const MEMORY_TYPES: Record<string, string> = {
  year_in_review: N_('Year in Review'),
  season: N_('Season'),
  person_spotlight: N_('Person Spotlight'),
  multi_person: N_('Multi-Person'),
  monthly_highlights: N_('Monthly Highlights'),
  on_this_day: N_('On This Day'),
  album: N_('Album'),
  trip: N_('Trip'),
  holiday: N_('Holiday'),
  special_day: N_('Surprise me'),
  custom: N_('Custom date range'),
};

export const memoryTypeLabel = (value: string | null) => t(MEMORY_TYPES[value ?? 'custom'] ?? N_('Memory'));

export const RUN_STATUSES = ['completed', 'running', 'failed', 'cancelled', 'interrupted'] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];

const SOURCES: Record<string, string> = { manual: N_('Manual'), scheduled: N_('Scheduled'), auto: N_('Automatic') };

export const sourceLabel = (value: string) => t(SOURCES[value] ?? value);
