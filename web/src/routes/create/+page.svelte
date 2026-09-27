<script lang="ts">
  import { goto } from '$app/navigation';
  import { Button, Heading, LoadingSpinner, Text } from '@immich/ui';
  import { mdiMovieOpenPlayOutline } from '@mdi/js';
  import { onMount } from 'svelte';
  import { api, post, type AlbumChoice, type CutBrief, type JobView, type NamedPerson, type SpecialDay, type TripChoice } from '$lib/api';
  import { locale, N_, t } from '$lib/i18n.svelte';
  import { followJob } from '$lib/job.svelte';
  import JobPanel from '$lib/JobPanel.svelte';
  import { memoryTypeLabel } from '$lib/labels';

  // Which of generate's scope flags each memory type reads, in the order the form asks them.
  // Every date-range memory can be narrowed to people; a trip, an album and a spotlight cannot take a
  // grouped condition (generate refuses it there).
  const PEOPLE = ['person', 'person_match', 'people_expression'];
  const FIELDS: Record<string, string[]> = {
    monthly_highlights: ['year', 'month', ...PEOPLE],
    year_in_review: ['year', ...PEOPLE],
    season: ['year', 'season', 'hemisphere', ...PEOPLE],
    person_spotlight: ['year', 'person', 'birthday', 'years_back'],
    multi_person: ['year', ...PEOPLE],
    on_this_day: ['day', 'years_back', ...PEOPLE],
    album: ['from_album'],
    trip: ['year', 'trip_index', 'all_trips'],
    holiday: ['year', 'holiday', 'years_back', ...PEOPLE],
    special_day: ['day', 'event_id'],
    custom: ['start', 'end', 'period', ...PEOPLE],
  };
  // The types that are about their people: the names are the brief, not a narrowing of it.
  const ABOUT_PEOPLE = new Set(['person_spotlight', 'multi_person']);
  // What each level lets into the film, so the choice is not a guess.
  const SHARING_LINES = {
    'just-us': N_('The household. Private moments a caption names, like a bath, play too.'),
    family: N_('Grandparents, siblings, the group chat. Private moments stay out.'),
    shareable: N_('Anyone. Only pictures nothing held back: no detector flag, no private moment.'),
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
  let span = $state<'until' | 'for'>('until');
  let period = $state('6m');
  let birthdayYear = $state(false);
  let birthdayOverride = $state('');
  let chosen = $state<string[]>([]);
  let match = $state<'and' | 'or'>('and');
  let expression = $state('');
  let album = $state('');
  let tripIndex = $state<number | null>(null);
  let allTrips = $state(false);
  let holidayPick = $state('christmas');
  let holidayOther = $state('');
  let holidays = $state<{ key: string; name: string }[]>([]);
  const holiday = $derived(holidayPick === 'other' ? holidayOther.trim() : holidayPick);
  let minutes = $state<number | null>(null);
  let photos = $state(true);
  let live = $state(true);
  let sharing = $state<'just-us' | 'family' | 'shareable' | ''>('');
  let photoSeconds = $state<number | null>(null);
  let forwarded = $state(false);

  let trips = $state<TripChoice[] | null>(null);
  let specialDays = $state<SpecialDay[] | null>(null);
  let eventId = $state<string | null>(null);
  let tripProblem = $state('');
  let people = $state<NamedPerson[]>([]);
  let albums = $state<AlbumChoice[]>([]);
  let command = $state('');
  let job = $state<JobView | null>(null);
  let problem = $state('');
  let stop: (() => void) | null = null;

  const shown = $derived(FIELDS[kind]);
  const grouped = $derived(shown.includes('people_expression') && expression.trim() !== '');

  const brief = $derived.by((): CutBrief => {
    const has = (name: string) => shown.includes(name);
    return {
      memory_type: kind === 'custom' ? null : kind,
      year: has('year') ? year : null,
      month: has('month') ? month : null,
      season: has('season') ? season : null,
      hemisphere: has('hemisphere') ? hemisphere : null,
      day: has('day') ? day : null,
      // --years-back reaches back over earlier birthdays only when the year runs birthday to birthday.
      years_back: has('years_back') && (kind !== 'person_spotlight' || birthdayYear) ? yearsBack : null,
      start: has('start') && start ? start : null,
      end: has('end') && span === 'until' && end ? end : null,
      period: has('period') && span === 'for' && period ? period : null,
      birthday: has('birthday') && birthdayYear ? birthdayOverride.trim() || 'auto' : null,
      // A grouped condition names its own people: it replaces --person rather than refining it.
      person: has('person') && !grouped ? chosen : [],
      person_match: has('person_match') && !grouped && chosen.length > 1 ? match : null,
      people_expression: grouped ? expression.trim() : null,
      from_album: has('from_album') && album ? album : null,
      trip_index: has('trip_index') ? tripIndex : null,
      all_trips: has('all_trips') && allTrips,
      holiday: has('holiday') && holiday ? holiday : null,
      event_id: has('event_id') ? eventId : null,
      duration: minutes ? Math.round(minutes * 60) : null,
      include_photos: photos,
      include_live_photos: live,
      sharing: sharing || null,
      photo_duration: photoSeconds || null,
      accept_any_provenance: forwarded,
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

  // Without a trip chosen, `generate` only lists the year's trips: the form lists them here instead.
  $effect(() => {
    if (kind !== 'trip' || !year) return;
    const asked = year;
    trips = null;
    tripProblem = '';
    tripIndex = null;
    const timer = setTimeout(() => {
      api<TripChoice[]>(`/trips?year=${asked}`)
        .then((found) => { if (asked === year) trips = found; })
        .catch(() => { trips = []; tripProblem = t('Trip detection failed.'); });
    }, 300);
    return () => clearTimeout(timer);
  });
  // Albums are asked of Immich only when the brief is about one.
  let albumsAsked = false;
  $effect(() => {
    if (kind !== 'album' || albumsAsked) return;
    albumsAsked = true;
    void api<AlbumChoice[]>('/albums').then((found) => (albums = found)).catch(() => (albums = []));
  });

  $effect(() => {
    if (kind !== 'holiday') return;
    const lang = locale();
    void api<{ key: string; name: string }[]>(`/holidays?lang=${encodeURIComponent(lang)}`).then((found) => (holidays = found)).catch(() => (holidays = []));
  });

  $effect(() => {
    if (kind === 'special_day' && specialDays === null)
      void api<SpecialDay[]>('/special-days').then((found) => (specialDays = found)).catch(() => (specialDays = []));
  });

  function chooseDay(choice: SpecialDay) {
    day = choice.day;
    eventId = choice.event_id ?? null;
  }

  const tripChosen = $derived(kind !== 'trip' || allTrips || tripIndex !== null);

  // A failed cut's message is often a command to copy into a terminal: a reload must not lose it.
  const LAST_CUT = 'immich-memories:last-cut';
  const remember = (id: string) => { try { localStorage.setItem(LAST_CUT, id); } catch { /* private window */ } };
  const recalled = () => { try { return localStorage.getItem(LAST_CUT); } catch { return null; } };

  function follow(started: JobView) {
    job = started;
    remember(started.id);
    stop?.();
    stop = followJob(started.id, (update) => {
      job = update;
      if (update.status === 'succeeded' && update.result_run_id) void goto(`/app/runs/${encodeURIComponent(update.result_run_id)}`);
    });
  }

  onMount(() => {
    void api<JobView | null>('/jobs/active').then(async (running) => {
      if (running?.kind === 'cut') return follow(running);
      const last = recalled();
      if (!last) return;
      const earlier = await api<JobView>(`/jobs/${encodeURIComponent(last)}`).catch(() => null);
      if (earlier && (earlier.status === 'failed' || earlier.status === 'interrupted')) job = earlier;
    });
    void api<NamedPerson[]>('/people').then((found) => (people = found)).catch(() => (people = []));
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
        {#if shown.includes('day')}<label class={label}>{t('Day')}<input class={field} type="date" bind:value={day} oninput={() => (eventId = null)} /></label>{/if}
        {#if shown.includes('birthday')}
          <label class="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" bind:checked={birthdayYear} />{t('Birthday to birthday, with earlier birthdays')}</label>
          {#if birthdayYear}<label class={label}>{t('Birthday (MM-DD; Immich’s birth date when empty)')}<input class={field} bind:value={birthdayOverride} placeholder="03-15" pattern="\d\d-\d\d" /></label>{/if}
        {/if}
        {#if shown.includes('years_back') && (kind !== 'person_spotlight' || birthdayYear)}
          <label class={label}>{kind === 'holiday' ? t('Years to span') : t('Years back (all when empty)')}<input class={field} type="number" min="1" bind:value={yearsBack} /></label>
        {/if}
        {#if shown.includes('start')}<label class={label}>{t('From')}<input class={field} type="date" bind:value={start} required /></label>{/if}
        {#if shown.includes('period')}
          <label class={label}>{t('Ends')}
            <select class={field} bind:value={span}><option value="until">{t('On a date')}</option><option value="for">{t('After a period')}</option></select>
          </label>
        {/if}
        {#if shown.includes('end') && span === 'until'}<label class={label}>{t('To')}<input class={field} type="date" bind:value={end} required /></label>{/if}
        {#if shown.includes('period') && span === 'for'}<label class={label}>{t('Period (6m, 1y, 2w)')}<input class={field} bind:value={period} pattern="\d+[dwmy]" required /></label>{/if}
        {#if shown.includes('holiday')}
          <label class={label}>{t('Holiday')}
            <select class={field} bind:value={holidayPick}>
              {#each holidays as choice (choice.key)}<option value={choice.key}>{choice.name}</option>{/each}
              <option value="other">{t('Another day (MM-DD)')}</option>
            </select>
          </label>
          {#if holidayPick === 'other'}<label class={label}>{t('Day (MM-DD)')}<input class={field} bind:value={holidayOther} placeholder="07-14" pattern="\d\d-\d\d" required /></label>{/if}
        {/if}
        {#if shown.includes('from_album')}
          <label class={label}>{t('Album')}
            <select class={field} bind:value={album} required>
              <option value="" disabled>{t('Choose an album')}</option>
              {#each albums as choice (choice.id)}<option value={choice.id}>{choice.name} ({choice.asset_count})</option>{/each}
            </select>
          </label>
        {/if}
      </div>

      {#if kind === 'special_day'}
        <fieldset class="flex flex-col gap-2">
          <legend class="mb-1 text-sm font-semibold">{t('Catalogued days')}</legend>
          {#if specialDays === null}
            <LoadingSpinner size="small" />
          {:else if specialDays.length}
            <Text size="small" color="muted">{t('Anniversaries first, then the rest. A scheduled run only proposes a day on its anniversary; here you can pick any day the catalogue holds.')}</Text>
            <ul class="flex max-h-72 flex-col gap-1 overflow-y-auto" aria-label={t('Catalogued days')}>
              {#each specialDays as choice (`${choice.day}-${choice.event_id ?? ''}`)}
                <li>
                  <button type="button" onclick={() => chooseDay(choice)} aria-pressed={day === choice.day && eventId === (choice.event_id ?? null)}
                    class={['flex w-full flex-wrap items-baseline gap-x-3 rounded-lg border px-3 py-2 text-left text-sm', day === choice.day && eventId === (choice.event_id ?? null) ? 'border-primary bg-primary/10' : 'border-gray-200 dark:border-gray-800']}>
                    <span class="font-medium">{choice.name}</span>
                    <span class="text-gray-600 tabular-nums dark:text-gray-400">{choice.day}</span>
                    {#if choice.years_ago}<span class="text-primary">{t('{years} years ago', { years: choice.years_ago })}</span>{/if}
                  </button>
                </li>
              {/each}
            </ul>
          {:else}
            <Text size="small" color="muted">{t('No catalogued days yet. Run immich-memories discover-days to find them, or film any day by its date.')}</Text>
          {/if}
        </fieldset>
      {/if}

      {#if shown.includes('trip_index')}
        <fieldset class="flex flex-col gap-2">
          <legend class="mb-1 text-sm font-semibold">{t('Trip')}</legend>
          {#if trips === null && !tripProblem}
            <span class="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400"><LoadingSpinner size="small" />{t('Detecting trips from GPS data...')}</span>
          {:else if tripProblem}
            <p class="text-sm text-danger" role="alert">{tripProblem}</p>
          {:else if trips && trips.length}
            <ul class="flex flex-col gap-1" aria-label={t('Trips')}>
              {#each trips as trip (trip.index)}
                <li>
                  <label class={['flex cursor-pointer flex-wrap items-baseline gap-x-3 rounded-lg border px-3 py-2 text-sm', !allTrips && tripIndex === trip.index ? 'border-primary bg-primary/10' : 'border-gray-200 dark:border-gray-800']}>
                    <input type="radio" name="trip" class="sr-only" value={trip.index} bind:group={tripIndex} disabled={allTrips} />
                    <span class="font-medium">{trip.place}</span>
                    <span class="text-gray-600 tabular-nums dark:text-gray-400">{trip.start} – {trip.end}</span>
                    <span class="text-gray-600 tabular-nums dark:text-gray-400">{t('{days} days · {count} pictures', { days: trip.days, count: trip.pictures })}</span>
                  </label>
                </li>
              {/each}
            </ul>
            <label class="flex items-center gap-2 text-sm"><input type="checkbox" bind:checked={allTrips} />{t('Every trip of the year')}</label>
          {:else}
            <Text size="small" color="muted">{t('No trips detected for this year.')}</Text>
          {/if}
        </fieldset>
      {/if}

      {#if shown.includes('person')}
        <fieldset class="flex flex-col gap-2">
          <legend class="mb-1 text-sm font-semibold">{ABOUT_PEOPLE.has(kind) ? t('People') : t('Only with (optional)')}</legend>
          <div class="flex max-h-48 flex-wrap gap-2 overflow-y-auto">
            {#each people as person (person.id)}
              <label class={['cursor-pointer rounded-full border px-3 py-1 text-sm', chosen.includes(person.name) ? 'border-primary bg-primary/10' : 'border-gray-200 dark:border-gray-800']}>
                <input type="checkbox" class="sr-only" value={person.name} bind:group={chosen} disabled={grouped} />{person.name}
              </label>
            {:else}
              <Text size="small" color="muted">{t('No named people in Immich yet.')}</Text>
            {/each}
          </div>
          {#if shown.includes('people_expression')}
            <details class="text-sm" open={grouped}>
              <summary class="cursor-pointer text-gray-600 dark:text-gray-400">{t('Grouped condition')}</summary>
              <label class="mt-2 flex flex-col gap-1 font-medium">{t('People condition')}
                <input class={field} bind:value={expression} placeholder={'("Person A" OR "Person B") AND "Person C"'} />
              </label>
              <Text size="small" color="muted">{t('Use exact library names; each picture must match. It replaces the names above.')}</Text>
            </details>
          {/if}
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
            {#if sharing}<span class="text-xs font-normal text-gray-600 dark:text-gray-400">{t(SHARING_LINES[sharing])}</span>{/if}
          </label>
          <label class="flex items-center gap-2 text-sm"><input type="checkbox" bind:checked={photos} />{t('Include photos')}</label>
          <label class="flex items-center gap-2 text-sm"><input type="checkbox" bind:checked={live} />{t('Include Live Photos')}</label>
          <label class={label}>{t('Photo duration (seconds)')}<input class={field} type="number" min="1" step="0.5" bind:value={photoSeconds} placeholder="4" /></label>
          <label class="flex items-center gap-2 text-sm"><input type="checkbox" bind:checked={forwarded} />{t('Accept forwarded and downloaded media')}</label>
        </div>
      </details>

      <div class="flex flex-col gap-2">
        <code class="rounded-md bg-gray-100 px-3 py-2 text-xs break-all dark:bg-gray-900" aria-label={t('Command')}>{command}</code>
        {#if problem}<p class="text-sm text-danger" role="alert">{problem}</p>{/if}
        {#if job && job.status !== 'running'}<JobPanel {job} onCancel={cancel} />{/if}
        <Button type="submit" leadingIcon={mdiMovieOpenPlayOutline} class="w-fit" disabled={!tripChosen}>{t('Cut')}</Button>
      </div>
    </form>
  {/if}
</div>
