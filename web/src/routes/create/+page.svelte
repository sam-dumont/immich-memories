<script lang="ts">
  import { goto } from '$app/navigation';
  import { Button, Heading, Text } from '@immich/ui';
  import { mdiMovieOpenPlayOutline } from '@mdi/js';
  import { onMount } from 'svelte';
  import { api, post, type AlbumChoice, type CutBrief, type JobView, type NamedPerson } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import { followJob } from '$lib/job.svelte';
  import JobPanel from '$lib/JobPanel.svelte';
  import { memoryTypeLabel } from '$lib/labels';

  // Which of generate's scope flags each memory type reads, in the order the form asks them.
  const FIELDS: Record<string, string[]> = {
    monthly_highlights: ['year', 'month'],
    year_in_review: ['year'],
    season: ['year', 'season', 'hemisphere'],
    person_spotlight: ['year', 'person'],
    multi_person: ['year', 'person', 'person_match'],
    on_this_day: ['day', 'years_back'],
    album: ['from_album'],
    trip: ['year', 'trip_index', 'all_trips'],
    holiday: ['year', 'holiday'],
    custom: ['start', 'end', 'person'],
  };
  const TYPES = Object.keys(FIELDS);
  const SEASONS = ['spring', 'summer', 'fall', 'winter'] as const;
  const now = new Date();

  let kind = $state('monthly_highlights');
  let year = $state(now.getFullYear());
  let month = $state(now.getMonth() || 12);
  let season = $state<(typeof SEASONS)[number]>('summer');
  let hemisphere = $state<'north' | 'south'>('north');
  let day = $state(now.toISOString().slice(0, 10));
  let yearsBack = $state<number | null>(null);
  let start = $state('');
  let end = $state('');
  let chosen = $state<string[]>([]);
  let match = $state<'and' | 'or'>('and');
  let album = $state('');
  let tripIndex = $state<number | null>(null);
  let allTrips = $state(false);
  let holiday = $state('');
  let minutes = $state<number | null>(null);
  let photos = $state(true);
  let live = $state(true);
  let sharing = $state<'just-us' | 'family' | 'shareable' | ''>('');

  let people = $state<NamedPerson[]>([]);
  let albums = $state<AlbumChoice[]>([]);
  let command = $state('');
  let job = $state<JobView | null>(null);
  let problem = $state('');
  let stop: (() => void) | null = null;

  const shown = $derived(FIELDS[kind]);

  const brief = $derived.by((): CutBrief => {
    const has = (name: string) => shown.includes(name);
    return {
      memory_type: kind === 'custom' ? null : kind,
      year: has('year') ? year : null,
      month: has('month') ? month : null,
      season: has('season') ? season : null,
      hemisphere: has('hemisphere') ? hemisphere : null,
      day: has('day') ? day : null,
      years_back: has('years_back') ? yearsBack : null,
      start: has('start') && start ? start : null,
      end: has('end') && end ? end : null,
      person: has('person') ? chosen : [],
      person_match: has('person_match') && chosen.length > 1 ? match : null,
      from_album: has('from_album') && album ? album : null,
      trip_index: has('trip_index') ? tripIndex : null,
      all_trips: has('all_trips') && allTrips,
      holiday: has('holiday') && holiday ? holiday : null,
      duration: minutes ? Math.round(minutes * 60) : null,
      include_photos: photos,
      include_live_photos: live,
      sharing: sharing || null,
    } as CutBrief;
  });

  // The command is the server's own reading of the brief, so what the page shows is what runs.
  $effect(() => {
    const body = brief;
    const timer = setTimeout(async () => {
      const { body: shownCommand } = await post<{ command: string }>('/cuts/command', body);
      command = shownCommand.command ?? '';
    }, 150);
    return () => clearTimeout(timer);
  });

  function follow(started: JobView) {
    job = started;
    stop?.();
    stop = followJob(started.id, (update) => {
      job = update;
      if (update.status === 'succeeded' && update.result_run_id) void goto(`/app/runs/${encodeURIComponent(update.result_run_id)}`);
    });
  }

  onMount(() => {
    void api<JobView | null>('/jobs/active').then((running) => running && follow(running));
    void api<NamedPerson[]>('/people').then((found) => (people = found)).catch(() => (people = []));
    void api<AlbumChoice[]>('/albums').then((found) => (albums = found)).catch(() => (albums = []));
    return () => stop?.();
  });

  async function cut() {
    problem = '';
    const { status, body } = await post<JobView>('/cuts', brief);
    if (status === 202) follow(body);
    else if (status === 409 && body.job) follow(body.job);
    else problem = body.detail ?? t('The cut could not start.');
  }

  async function cancel() {
    if (job) job = (await post<JobView>(`/jobs/${encodeURIComponent(job.id)}/cancel`, {})).body;
  }

  const field = 'rounded-lg border border-gray-300 bg-light px-3 py-2 dark:border-gray-700';
  const label = 'flex flex-col gap-1 text-sm font-medium';
</script>

<svelte:head><title>{t('New memory')} · Immich Memories</title></svelte:head>

<div class="flex max-w-3xl flex-col gap-6">
  <div class="flex flex-col gap-1">
    <Heading size="large" tag="h1">{t('New memory')}</Heading>
    <Text color="muted">{t('Choose what the film covers. The cut is made the way the command below makes it; you review it before anything renders.')}</Text>
  </div>

  {#if job && job.status === 'running'}
    <JobPanel {job} onCancel={cancel} />
  {:else}
    <form class="flex flex-col gap-6" onsubmit={(event) => { event.preventDefault(); void cut(); }}>
      <fieldset class="flex flex-col gap-3">
        <legend class="mb-2 text-sm font-semibold">{t('Memory type')}</legend>
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {#each TYPES as type (type)}
            <label class={['cursor-pointer rounded-xl border px-3 py-2 text-sm', kind === type ? 'border-primary bg-primary/10 font-medium' : 'border-gray-200 dark:border-gray-800']}>
              <input type="radio" name="kind" value={type} bind:group={kind} class="sr-only" />{memoryTypeLabel(type)}
            </label>
          {/each}
        </div>
      </fieldset>

      <div class="grid gap-4 sm:grid-cols-2">
        {#if shown.includes('year')}<label class={label}>{t('Year')}<input class={field} type="number" min="1990" max="2100" bind:value={year} /></label>{/if}
        {#if shown.includes('month')}<label class={label}>{t('Month')}<input class={field} type="number" min="1" max="12" bind:value={month} /></label>{/if}
        {#if shown.includes('season')}
          <label class={label}>{t('Season')}<select class={field} bind:value={season}>{#each SEASONS as value (value)}<option {value}>{t(value)}</option>{/each}</select></label>
        {/if}
        {#if shown.includes('hemisphere')}
          <label class={label}>{t('Hemisphere')}<select class={field} bind:value={hemisphere}><option value="north">{t('North')}</option><option value="south">{t('South')}</option></select></label>
        {/if}
        {#if shown.includes('day')}<label class={label}>{t('Day')}<input class={field} type="date" bind:value={day} /></label>{/if}
        {#if shown.includes('years_back')}<label class={label}>{t('Years back (all when empty)')}<input class={field} type="number" min="1" bind:value={yearsBack} /></label>{/if}
        {#if shown.includes('start')}<label class={label}>{t('From')}<input class={field} type="date" bind:value={start} required /></label>{/if}
        {#if shown.includes('end')}<label class={label}>{t('To')}<input class={field} type="date" bind:value={end} required /></label>{/if}
        {#if shown.includes('holiday')}<label class={label}>{t('Holiday')}<input class={field} bind:value={holiday} placeholder="christmas" required /></label>{/if}
        {#if shown.includes('trip_index')}<label class={label}>{t('Trip number (the biggest when empty)')}<input class={field} type="number" min="1" bind:value={tripIndex} /></label>{/if}
        {#if shown.includes('all_trips')}<label class="flex items-center gap-2 text-sm"><input type="checkbox" bind:checked={allTrips} />{t('Every trip of the year')}</label>{/if}
        {#if shown.includes('from_album')}
          <label class={label}>{t('Album')}
            <select class={field} bind:value={album} required>
              <option value="" disabled>{t('Choose an album')}</option>
              {#each albums as choice (choice.id)}<option value={choice.name}>{choice.name} ({choice.asset_count})</option>{/each}
            </select>
          </label>
        {/if}
      </div>

      {#if shown.includes('person')}
        <fieldset class="flex flex-col gap-2">
          <legend class="mb-1 text-sm font-semibold">{t('People')}</legend>
          <div class="flex max-h-48 flex-wrap gap-2 overflow-y-auto">
            {#each people as person (person.id)}
              <label class={['cursor-pointer rounded-full border px-3 py-1 text-sm', chosen.includes(person.name) ? 'border-primary bg-primary/10' : 'border-gray-200 dark:border-gray-800']}>
                <input type="checkbox" class="sr-only" value={person.name} bind:group={chosen} />{person.name}
              </label>
            {:else}
              <Text size="small" color="muted">{t('No named people in Immich yet.')}</Text>
            {/each}
          </div>
          {#if shown.includes('person_match') && chosen.length > 1}
            <label class="flex items-center gap-2 text-sm">{t('Pictures with')}
              <select class={field} bind:value={match}><option value="and">{t('all of them together')}</option><option value="or">{t('any of them')}</option></select>
            </label>
          {/if}
        </fieldset>
      {/if}

      <details class="rounded-xl border border-gray-200 p-4 dark:border-gray-800">
        <summary class="cursor-pointer text-sm font-semibold">{t('Length and pictures')}</summary>
        <div class="mt-4 grid gap-4 sm:grid-cols-2">
          <label class={label}>{t('Length in minutes (fitted to the pictures when empty)')}<input class={field} type="number" min="0.5" step="0.5" bind:value={minutes} /></label>
          <label class={label}>{t('Who may see it')}
            <select class={field} bind:value={sharing}>
              <option value="">{t('As configured')}</option><option value="just-us">{t('Just us')}</option>
              <option value="family">{t('Family')}</option><option value="shareable">{t('Shareable')}</option>
            </select>
          </label>
          <label class="flex items-center gap-2 text-sm"><input type="checkbox" bind:checked={photos} />{t('Include photos')}</label>
          <label class="flex items-center gap-2 text-sm"><input type="checkbox" bind:checked={live} />{t('Include Live Photos')}</label>
        </div>
      </details>

      <div class="flex flex-col gap-2">
        <code class="rounded-md bg-gray-100 px-3 py-2 text-xs break-all dark:bg-gray-900" aria-label={t('Command')}>{command}</code>
        {#if problem}<p class="text-sm text-danger" role="alert">{problem}</p>{/if}
        {#if job && job.status !== 'running'}<JobPanel {job} onCancel={cancel} />{/if}
        <Button type="submit" leadingIcon={mdiMovieOpenPlayOutline} class="w-fit">{t('Cut')}</Button>
      </div>
    </form>
  {/if}
</div>
