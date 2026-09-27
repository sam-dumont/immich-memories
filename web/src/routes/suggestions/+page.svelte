<script lang="ts">
  import { Button, Heading, LoadingSpinner, Text } from '@immich/ui';
  import { mdiPlayOutline, mdiRefresh } from '@mdi/js';
  import { onMount } from 'svelte';
  import { api, post } from '$lib/api';
  import type { components } from '$lib/api-types';
  import { t } from '$lib/i18n.svelte';
  import { memoryTypeLabel, ruleLabel } from '$lib/labels';

  type Suggestions = components['schemas']['Suggestions'];
  type Attempt = components['schemas']['AttemptView'];

  let data = $state<Suggestions | null>(null);
  let loading = $state(false);
  let failed = $state(false);
  let attempt = $state<Attempt | null>(null);
  let busy = $state('');
  let checking = $state<string | null>(null);

  async function load() {
    loading = true;
    failed = false;
    try {
      data = await api<Suggestions>('/suggestions');
    } catch {
      failed = true;
    } finally {
      loading = false;
    }
  }

  onMount(() => void load());

  // The attempt is the automation store's record; the page follows it until it settles.
  $effect(() => {
    if (!attempt || attempt.outcome !== 'running') return;
    const id = attempt.id;
    const timer = setInterval(async () => (attempt = await api<Attempt>(`/automation/attempts/${encodeURIComponent(id)}`)), 1500);
    return () => clearInterval(timer);
  });

  async function start(key: string, dryRun: boolean) {
    busy = '';
    checking = key;
    const { status, body } = await post<Attempt>('/suggestions/run', { memory_key: key, dry_run: dryRun });
    if (status === 202) attempt = body;
    else busy = body.detail ?? t('Automation is already running. Open Runs to follow it.');
  }

  const settled = (value: Attempt) =>
    value.outcome === 'dry_run'
      ? t('Eligible. No video was generated.')
      : `${t(value.outcome.replaceAll('_', ' '))}: ${value.reason}`;
</script>

<svelte:head><title>{t('Suggestions')} · Immich Memories</title></svelte:head>

<div class="flex flex-col gap-6">
  <div class="flex flex-wrap items-end justify-between gap-3">
    <div class="flex flex-col gap-1">
      <Heading size="large" tag="h1">{t('Suggestions')}</Heading>
      <Text color="muted">{t('What automation would make next, the same list `auto suggest` prints. Run one as `auto run` would, or check it first without rendering.')}</Text>
    </div>
    <Button size="small" variant="outline" leadingIcon={mdiRefresh} loading={loading} onclick={load}>{t('Refresh suggestions')}</Button>
  </div>

  {#if attempt}
    <section class="rounded-2xl border border-gray-200 p-4 dark:border-gray-800" aria-live="polite">
      {#if attempt.outcome === 'running'}
        <p>{t('Running on the server: {phase}. It continues if you leave this page.', { phase: attempt.phase ?? t('starting') })}</p>
      {:else}
        <p>{settled(attempt)}</p>
        {#if attempt.run_id}<a class="text-sm text-primary hover:underline" href={`/app/runs/${encodeURIComponent(attempt.run_id)}`}>{t('Open run')}</a>{/if}
      {/if}
    </section>
  {/if}
  {#if busy}<p class="text-sm text-danger" role="alert">{busy}</p>{/if}
  {#if failed}<Text color="danger">{t('Suggestions could not be loaded.')}</Text>{/if}
  {#if data?.error}<Text color="danger">{t('Discovery failed: {error}', { error: data.error })}</Text>{/if}

  {#if !data && loading}
    <LoadingSpinner />
  {:else if data}
    <ul class="grid gap-4 md:grid-cols-2">
      {#each data.candidates as candidate (candidate.memory_key)}
        <li class="flex flex-col gap-2 rounded-2xl border border-gray-200 p-4 dark:border-gray-800">
          <p class="text-lg font-semibold">{candidate.reason}</p>
          {#if candidate.person_names.length}<p class="font-medium">{candidate.person_names.join(', ')}</p>{/if}
          <p class="text-sm text-gray-600 tabular-nums dark:text-gray-400">
            {memoryTypeLabel(candidate.memory_type)} · {candidate.date_range_start} – {candidate.date_range_end} · {t('Pictures: {count}', { count: candidate.asset_count })}
          </p>
          <details class="text-xs"><summary class="cursor-pointer">{t('Candidate key')}</summary><code class="break-all">{candidate.memory_key}</code></details>
          <div class="flex flex-wrap gap-2">
            <Button size="small" variant="outline" disabled={attempt?.outcome === 'running'} onclick={() => start(candidate.memory_key, true)}>{t('Check eligibility')}</Button>
            <Button size="small" leadingIcon={mdiPlayOutline} disabled={attempt?.outcome === 'running'} onclick={() => start(candidate.memory_key, false)}>{t('Run this suggestion')}</Button>
          </div>
        </li>
      {:else}
        <li><Text color="muted">{t('No suggestions right now.')}</Text></li>
      {/each}
    </ul>
    {#if data.skipped.length}
      <details class="rounded-xl border border-gray-200 p-4 dark:border-gray-800">
        <summary class="cursor-pointer text-sm font-semibold">{t('Why other suggestions were skipped')}</summary>
        <ul class="mt-2 flex flex-col gap-1 text-sm">
          {#each data.skipped as item, index (index)}<li><span class="font-medium">{item.label}</span>: {ruleLabel(item.rule)}</li>{/each}
        </ul>
      </details>
    {/if}
  {/if}
</div>
