<script lang="ts">
  import { Badge, Button, Text, type Color } from '@immich/ui';
  import { mdiMovieOpenPlayOutline, mdiTextSearch } from '@mdi/js';
  import { onMount } from 'svelte';
  import { api, post, type AskAvailability, type AskPreview, type JobView } from './api';
  import { docsPage } from './docs';
  import { N_, t } from './i18n.svelte';
  import { followJob } from './job.svelte';
  import JobPanel from './JobPanel.svelte';

  // The film is the page's ordinary cut of the same sentence: the page starts and follows it.
  let { onFilm }: { onFilm: (sentence: string) => Promise<string> } = $props();

  // The trace's parts as the CLI prints them, worded for reading.
  const HEADS: Record<string, string> = {
    READING: N_('How it read your words'),
    WHO: N_('Who'),
    WHEN: N_('When'),
    WHERE: N_('Where'),
    WHAT: N_('What'),
    FACTS: N_('What the library measures'),
    POOL: N_('The pool'),
    VERDICT: N_('Verdict'),
    FILM: N_('The film'),
  };
  const VERDICTS: Record<string, { label: string; color: Color }> = {
    possible: { label: N_('Possible'), color: 'success' },
    thin: { label: N_('Thin'), color: 'warning' },
    'not possible': { label: N_('Not possible'), color: 'danger' },
  };

  let availability = $state<AskAvailability | null>(null);
  let sentence = $state('');
  let job = $state<JobView | null>(null);
  let preview = $state<AskPreview | null>(null);
  let problem = $state('');
  let stop: (() => void) | null = null;

  // A preview belongs to the words it read: edited words need a new one before a film.
  const current = $derived(preview !== null && preview.request === sentence.trim());
  const filmable = $derived(current && preview?.verdict !== 'not possible' && preview?.film.route !== 'none');

  // The last preview survives a reload, like the page's last cut.
  const LAST_ASK = 'immich-memories:last-ask';
  const remember = (id: string) => { try { localStorage.setItem(LAST_ASK, id); } catch { /* private window */ } };
  const recalled = () => { try { return localStorage.getItem(LAST_ASK); } catch { return null; } };

  async function show(finished: JobView) {
    if (finished.status !== 'succeeded') return;
    preview = await api<AskPreview>(`/ask/preview/${encodeURIComponent(finished.id)}`).catch(() => null);
    if (preview && !sentence.trim()) sentence = preview.request;
  }

  function follow(started: JobView) {
    job = started;
    preview = null;
    remember(started.id);
    stop?.();
    stop = followJob(started.id, (update) => {
      job = update;
      void show(update);
    });
  }

  onMount(() => {
    void api<AskAvailability>('/ask').then((found) => (availability = found)).catch(() => (availability = null));
    void api<JobView | null>('/jobs/active').then(async (running) => {
      if (running?.kind === 'ask') return follow(running);
      const last = recalled();
      if (!last) return;
      const earlier = await api<JobView>(`/jobs/${encodeURIComponent(last)}`).catch(() => null);
      if (earlier?.kind !== 'ask') return;
      job = earlier;
      await show(earlier);
    });
    return () => stop?.();
  });

  async function start() {
    problem = '';
    const { status, body } = await post<JobView>('/ask/preview', { sentence: sentence.trim() });
    if (status === 202) follow(body);
    else if (status === 409 && body.job?.kind === 'ask') follow(body.job);
    else problem = body.detail ?? t('The preview could not start.');
  }

  async function film() {
    if (preview) problem = await onFilm(preview.request);
  }

  async function cancel() {
    if (job) job = (await post<JobView>(`/jobs/${encodeURIComponent(job.id)}/cancel`, {})).body;
  }
</script>

<section class="flex flex-col gap-4 rounded-2xl border border-gray-200 p-5 dark:border-gray-800" aria-labelledby="ask-heading">
  <div class="flex flex-wrap items-center gap-3">
    <h2 id="ask-heading" class="text-base font-semibold">{t('Describe the film you want')}</h2>
    <a href={docsPage('make/free-text')} target="_blank" rel="noopener noreferrer" class="rounded-full border border-warning px-2 py-0.5 text-xs font-medium text-warning hover:bg-warning/10">
      {t('Experimental')}
    </a>
  </div>

  {#if availability && !availability.available}
    <Text size="small" color="muted">
      {t('A film from a sentence needs the model tier: set advanced.llm.base_url and advanced.llm.model to the reader that answers it (tier: full).')}
    </Text>
  {:else if availability}
    <Text size="small" color="muted">{t('The model reads your words against your prepared library. Preview first: it shows what each part of the sentence became and how many pictures fit, and films nothing.')}</Text>
    {#if job && job.status === 'running'}
      <JobPanel {job} onCancel={cancel} />
    {:else}
      <form class="flex flex-col gap-3" onsubmit={(event) => { event.preventDefault(); void start(); }}>
        <textarea class="min-h-20 rounded-lg border border-gray-300 bg-light px-3 py-2 dark:border-gray-700" bind:value={sentence} maxlength="500"
          aria-label={t('Describe the film you want')} placeholder={t('our cat along the years')}></textarea>
        {#if problem}<p class="text-sm text-danger" role="alert">{problem}</p>{/if}
        {#if job && (job.status === 'failed' || job.status === 'interrupted')}<JobPanel {job} onCancel={cancel} />{/if}
        <div class="flex flex-wrap gap-2">
          <Button type="submit" variant={filmable ? 'outline' : 'filled'} leadingIcon={mdiTextSearch} disabled={!sentence.trim()}>{t('Preview')}</Button>
          {#if filmable && preview}
            <Button type="button" leadingIcon={mdiMovieOpenPlayOutline} onclick={film}>{t('Make the film')}</Button>
          {/if}
        </div>
      </form>
    {/if}

    {#if preview}
      {@const verdict = VERDICTS[preview.verdict] ?? { label: preview.verdict, color: 'secondary' as Color }}
      <div class={['flex flex-col gap-4', !current && 'opacity-60']} aria-label={t('Preview')}>
        <div class="flex flex-col gap-2 rounded-xl bg-gray-100 p-4 dark:bg-gray-900">
          <div class="flex flex-wrap items-center gap-3">
            <Badge color={verdict.color}>{t(verdict.label)}</Badge>
            <span class="text-sm tabular-nums">{t('{pictures} pictures: {photos} photos, {videos} videos', { ...preview.pool })}</span>
          </div>
          <p class="text-sm">{preview.why}</p>
          {#if preview.verdict === 'not possible'}
            <p class="text-sm font-medium">{t('No film: the library cannot show this. Try other words, or read below what each part of the sentence found.')}</p>
          {:else if preview.verdict === 'thin'}
            <p class="text-sm">{t('Fewer than 12 pictures fit: the film will be short.')}</p>
          {/if}
          {#if preview.film.route !== 'none'}<p class="text-sm text-gray-600 dark:text-gray-400">{preview.film.line}</p>{/if}
          {#if !current}<p class="text-sm text-gray-600 dark:text-gray-400">{t('The words changed since this preview: preview again before making the film.')}</p>{/if}
        </div>

        <dl class="flex flex-col gap-3 text-sm" aria-label={t('How the sentence was read')}>
          {#each preview.blocks as block (block.head)}
            <div class="grid gap-1 sm:grid-cols-[10rem_1fr] sm:gap-4">
              <dt class="font-semibold">{HEADS[block.head] ? t(HEADS[block.head]) : block.head}</dt>
              <dd class="flex min-w-0 flex-col gap-1">
                {#each block.lines as line, index (index)}
                  {#if block.head === 'POOL' && index === 0}
                    <ol class="flex flex-wrap items-center gap-1" aria-label={t('Pictures left after each step')}>
                      {#each line.split(' -> ') as step, n (n)}
                        <li class="flex items-center gap-1">
                          {#if n}<span aria-hidden="true" class="text-gray-500">→</span>{/if}
                          <span class="rounded-full border border-gray-300 px-2 py-0.5 text-xs tabular-nums dark:border-gray-700">{step}</span>
                        </li>
                      {/each}
                    </ol>
                  {:else}
                    <p class="break-words text-gray-700 dark:text-gray-300">{line}</p>
                  {/if}
                {/each}
              </dd>
            </div>
          {/each}
        </dl>
      </div>
    {/if}
  {/if}
</section>
