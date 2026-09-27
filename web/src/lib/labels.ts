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

// What a seat the model polish filled means; the same msgids as the server pages.
const SEATS: Record<string, string> = {
  'vote-weak': N_('Replaced a picture the model doubted.'),
  'vote-bad': N_('Took the seat of a picture the model removed from this story.'),
  'gate-refused': N_('Took the seat of a picture a check refused.'),
  notable: N_('Added for a moment the catalogue records as notable.'),
};

export const seatLabel = (seat: string) => (SEATS[seat] ? t(SEATS[seat]) : seat);

/** 0:56 style clock for a position or a length in the film. */
export const clock = (seconds: number) => {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
};

// Why automation set a candidate aside; the same sentences the server pages showed.
const RULES: Record<string, string> = {
  same_category_as_previous: N_('The previous automatic memory used this category.'),
  category_limit_two_of_six: N_('This category already appears twice in the last six memories.'),
  monthly_review_already_completed_this_month: N_('A monthly review already finished this month.'),
  person_in_last_two_person_runs: N_('These people appear in the last two people memories.'),
};

export const ruleLabel = (rule: string) => (RULES[rule] ? t(RULES[rule]) : rule);
