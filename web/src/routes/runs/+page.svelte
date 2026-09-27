<script lang="ts">
  import { Badge, Button, Heading, LoadingSpinner, Text, type Color } from '@immich/ui';
  import { mdiImageOffOutline } from '@mdi/js';
  import { api, thumbnail, type RunPage, type RunSummary } from '$lib/api';
  import { locale, t } from '$lib/i18n.svelte';
  import { memoryTypeLabel, RUN_STATUSES, sourceLabel, type RunStatus } from '$lib/labels';

  const PAGE = 24;
  const STATUS_COLOR: Record<string, Color> = {
    completed: 'success',
    running: 'info',
    failed: 'danger',
    cancelled: 'secondary',
    interrupted: 'warning',
  };

  let status = $state<RunStatus | 'all'>('all');
  let runs = $state<RunSummary[]>([]);
  let nextOffset = $state<number | null>(0);
  let loading = $state(false);
  let failed = $state(false);
  let sentinel = $state<HTMLElement>();

  async function more() {
    if (loading || nextOffset === null) return;
    loading = true;
    const asked = status;
    try {
      const query = new URLSearchParams({ limit: String(PAGE), offset: String(nextOffset) });
      if (asked !== 'all') query.set('status', asked);
      const page = await api<RunPage>(`/runs?${query}`);
      if (asked !== status) return;
      runs = [...runs, ...page.runs];
      nextOffset = page.next_offset;
      failed = false;
    } catch {
      failed = true;
    } finally {
      loading = false;
    }
  }

  function choose(value: RunStatus | 'all') {
    status = value;
    runs = [];
    nextOffset = 0;
    loading = false;
    void more();
  }

  // The next page loads as the last card scrolls into view.
  $effect(() => {
    if (!sentinel) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void more();
    }, { rootMargin: '600px' });
    observer.observe(sentinel);
    return () => observer.disconnect();
  });

  const when = (value: string) => {
    const seconds = (new Date(value).getTime() - Date.now()) / 1000;
    const format = new Intl.RelativeTimeFormat(locale(), { numeric: 'auto' });
    for (const [unit, size] of [['day', 86400], ['hour', 3600], ['minute', 60]] as const) {
      if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
    }
    return format.format(Math.round(seconds), 'second');
  };
  const day = (value: string) => new Intl.DateTimeFormat(locale(), { dateStyle: 'medium' }).format(new Date(`${value}T00:00:00`));
  const span = (run: RunSummary) =>
    run.date_range_start && run.date_range_end
      ? t('{date_range_start} to {date_range_end}', { date_range_start: day(run.date_range_start), date_range_end: day(run.date_range_end) })
      : '';
</script>

<svelte:head><title>{t('Runs')} · Immich Memories</title></svelte:head>

<div class="flex flex-col gap-6">
  <div class="flex flex-col gap-1">
    <Heading size="large" tag="h1">{t('Runs')}</Heading>
    <Text color="muted">{t('Manual and automatic runs, including failures. Open a run to read its cut and timings.')}</Text>
  </div>

  <div class="flex flex-wrap gap-2" role="radiogroup" aria-label={t('Status')}>
    {#each ['all', ...RUN_STATUSES] as const as value (value)}
      <Button size="small" shape="round" variant={status === value ? 'filled' : 'outline'}
        color={status === value ? 'primary' : 'secondary'} role="radio" aria-checked={status === value} class="capitalize"
        onclick={() => choose(value)}>{t(value)}</Button>
    {/each}
  </div>

  {#if runs.length}
    <ul class="grid grid-cols-[repeat(auto-fill,minmax(min(100%,15rem),1fr))] gap-x-5 gap-y-8" aria-label={t('Runs')}>
      {#each runs as run (run.run_id)}
        <li>
          <a href={`/app/runs/${encodeURIComponent(run.run_id)}`} class="group flex flex-col gap-2 rounded-2xl outline-offset-4 focus-visible:outline-2 focus-visible:outline-primary">
            <div class="grid aspect-square grid-cols-2 grid-rows-2 gap-0.5 overflow-hidden rounded-2xl bg-gray-100 dark:bg-gray-900 transition group-hover:brightness-90">
              {#each run.preview_asset_ids.slice(0, 4) as asset, index (asset)}
                <img src={thumbnail(asset)} alt="" loading="lazy" decoding="async"
                  class={['size-full object-cover', run.preview_asset_ids.length === 1 && 'col-span-2 row-span-2', (run.preview_asset_ids.length === 2 || (run.preview_asset_ids.length === 3 && index === 0)) && 'row-span-2']} />
              {:else}
                <div class="col-span-2 row-span-2 flex items-center justify-center text-gray-400 dark:text-gray-600">
                  <svg viewBox="0 0 24 24" class="size-12 fill-current opacity-60" aria-hidden="true"><path d={mdiImageOffOutline} /></svg>
                  <span class="sr-only">{t('No saved cut is available for this run.')}</span>
                </div>
              {/each}
            </div>
            <div class="flex items-start justify-between gap-2 px-1">
              <div class="min-w-0">
                <p class="truncate font-medium">{memoryTypeLabel(run.memory_type)}</p>
                <p class="truncate text-sm text-gray-600 dark:text-gray-400">{span(run) || run.run_id}</p>
              </div>
              <Badge size="tiny" class="shrink-0 capitalize" color={STATUS_COLOR[run.status] ?? 'secondary'}>{t(run.status)}</Badge>
            </div>
            <p class="px-1 text-xs text-gray-600 dark:text-gray-400"><time datetime={run.created_at}>{when(run.created_at)}</time> · {sourceLabel(run.source)}</p>
          </a>
        </li>
      {/each}
    </ul>
  {:else if !loading && nextOffset === null}
    <Text color="muted">{t('No runs match this view. Make a memory from Memory or Suggestions.')}</Text>
  {/if}

  {#if failed}
    <div class="flex items-center gap-3">
      <Text color="danger">{t('The runs could not be loaded.')}</Text>
      <Button size="small" variant="outline" onclick={more}>{t('Try again')}</Button>
    </div>
  {/if}
  <div bind:this={sentinel} class="flex h-12 items-center justify-center">
    {#if loading}<LoadingSpinner />{/if}
  </div>
</div>
