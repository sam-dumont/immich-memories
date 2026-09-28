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
  special_day: N_('Special day'),
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

// The editor weighs each story in its own words; a weight with no reader word gets no badge.
const WEIGHTS: Record<string, string> = {
  dominant: N_('Main story'),
  major: N_('Important'),
  minor: N_('Supporting'),
  glimpse: N_('Small moment'),
};

export const weightLabel = (weight: string) => (WEIGHTS[weight] ? t(WEIGHTS[weight]) : '');

// The server words the reduced preparation tiers (operations/story_view.py); listed so the
// catalogues carry them.
N_('Edited without descriptions — picture content was classified, not read.');
N_('Edited from metadata only — picture content was neither classified nor read, so every picture is held to family viewing.');
// The connection's refusals (web/connection.py), shown as the server words them.
N_('The server URL changed: enter the API key for the new server.');
N_('Please enter both URL and API key');
// The music upload's refusals (web/job_routes.py).
N_('That file is too large for a soundtrack');

// The preparation passes report under their engine names; readers get what each pass looks at.
const PREPARATION_PASSES: Record<string, string> = {
  previews: N_('Fetching picture previews'),
  pixels: N_('Measuring the pictures'),
  faces: N_('Finding faces'),
  public_heads: N_('Reading what each picture shows'),
  detectors: N_('Checking pictures for the family audience'),
  motion: N_('Measuring motion in the videos'),
  captions: N_('Describing the pictures'),
  remote_facts: N_('Reading picture facts'),
};

export const stageLabel = (label: string) => (PREPARATION_PASSES[label] ? t(PREPARATION_PASSES[label]) : label);
