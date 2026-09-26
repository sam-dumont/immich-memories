<script lang="ts">
  import { Alert, Badge, Button, Heading, Text } from '@immich/ui';
  import { mdiArrowLeft, mdiDownload, mdiPlay } from '@mdi/js';
  import { thumbnail, type CutShot } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import { clock, memoryTypeLabel, sourceLabel } from '$lib/labels';
  import ShotInspector from '$lib/ShotInspector.svelte';

  let { data } = $props();
  const run = $derived(data.run);
  const cut = $derived(data.cut);

  let filter = $state<'all' | 'videos' | 'stills'>('all');
  let selectedId = $state<string | null>(null);
  let inspecting = $state(false);

  const shots = $derived(
    (cut?.shots ?? []).filter((shot) => filter === 'all' || (filter === 'videos') === shot.motion),
  );
  const selected = $derived(shots.find((shot) => shot.asset_id === selectedId) ?? shots[0]);
  const videos = $derived((cut?.shots ?? []).filter((shot) => shot.motion).length);

  function choose(shot: CutShot) {
    selectedId = shot.asset_id;
    inspecting = true;
  }

  // Left and right walk the sheet in playback order, the way a contact sheet is read.
  function walk(event: KeyboardEvent) {
    if (!selected || (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft')) return;
    if ((event.target as HTMLElement).closest('input, select, textarea, video')) return;
    const index = shots.indexOf(selected) + (event.key === 'ArrowRight' ? 1 : -1);
    const next = shots[Math.min(Math.max(index, 0), shots.length - 1)];
    selectedId = next.asset_id;
    document.getElementById(`shot-${next.asset_id}`)?.focus();
    event.preventDefault();
  }

  const FILTERS = [
    ['all', 'All pictures'],
    ['videos', 'Videos'],
    ['stills', 'Stills'],
  ] as const;
</script>

<svelte:head><title>{memoryTypeLabel(run.memory_type)} · {t('Runs')} · Immich Memories</title></svelte:head>
<svelte:window onkeydown={walk} />

<div class="flex flex-col gap-6">
  <div class="flex flex-col gap-3">
    <a href="/app/runs" class="flex w-fit items-center gap-1 text-sm text-gray-600 hover:text-primary dark:text-gray-400">
      <svg viewBox="0 0 24 24" class="size-4 fill-current" aria-hidden="true"><path d={mdiArrowLeft} /></svg>{t('Back to runs')}
    </a>
    <div class="flex flex-wrap items-center gap-3">
      <Heading size="large" tag="h1">{memoryTypeLabel(run.memory_type)}</Heading>
      <Badge color={run.status === 'completed' ? 'success' : run.status === 'failed' ? 'danger' : 'secondary'} class="capitalize">{t(run.status)}</Badge>
    </div>
    <p class="flex flex-wrap gap-x-3 text-sm text-gray-600 tabular-nums dark:text-gray-400">
      <span>{run.run_id}</span>
      <span>{sourceLabel(run.source)}</span>
      {#if cut}
        <span>{t('Pictures: {count}', { count: cut.shots.length })}</span>
        <span>{t('Videos: {count}', { count: videos })}</span>
        <span>{t('{content} of pictures and video', { content: clock(cut.content_seconds) })}</span>
        {#if cut.film_seconds}<span>{t('about {film} of film', { film: clock(cut.film_seconds) })}</span>{/if}
      {/if}
    </p>
    {#if cut?.thesis}<p class="max-w-4xl text-lg">{cut.thesis}</p>{/if}
    {#each run.warnings as warning, index (index)}
      <Alert color="warning" size="small">{warning}</Alert>
    {/each}
  </div>

  {#if cut}
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex flex-wrap gap-2" role="radiogroup" aria-label={t('Show')}>
        {#each FILTERS as [value, label] (value)}
          <Button size="small" shape="round" role="radio" aria-checked={filter === value}
            variant={filter === value ? 'filled' : 'outline'} color={filter === value ? 'primary' : 'secondary'}
            onclick={() => (filter = value)}>{t(label)}</Button>
        {/each}
      </div>
      <Text size="small" color="muted">{t('Order and timecodes from the saved cut.')}</Text>
    </div>

    <div class="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_24rem]">
      <ol class="grid grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))] gap-x-3 gap-y-4" aria-label={t('Cut contact sheet')}>
        {#each shots as shot (shot.asset_id)}
          {#if shot.chapter}
            <li class="col-span-full pt-2 text-sm font-semibold" aria-hidden="true">{shot.chapter}</li>
          {/if}
          <li>
            <button id={`shot-${shot.asset_id}`} type="button" onclick={() => choose(shot)} aria-pressed={selected?.asset_id === shot.asset_id}
              class={['group flex w-full flex-col gap-1.5 rounded-xl p-1 text-left outline-offset-2 focus-visible:outline-2 focus-visible:outline-primary',
                selected?.asset_id === shot.asset_id ? 'bg-primary/10 ring-2 ring-primary' : 'hover:bg-gray-100 dark:hover:bg-gray-900']}>
              <span class="relative block aspect-[4/3] overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-900">
                <img src={thumbnail(shot.asset_id)} alt={shot.reason || shot.story_title} loading="lazy" decoding="async" class="size-full object-contain" />
                <span class="absolute top-1 left-1 rounded bg-black/60 px-1.5 text-[11px] font-semibold text-white tabular-nums">{shot.position}</span>
                <span class="absolute right-1 bottom-1 flex items-center gap-0.5 rounded bg-black/60 px-1.5 text-[11px] text-white tabular-nums">
                  {#if shot.motion}<svg viewBox="0 0 24 24" class="size-3 fill-current" aria-label={t('Video')}><path d={mdiPlay} /></svg>{/if}
                  {shot.seconds.toFixed(1)} s
                </span>
              </span>
              <span class="flex justify-between gap-2 px-0.5 text-[11px] text-gray-600 tabular-nums dark:text-gray-400">
                <span class={shot.new_day ? 'font-semibold text-dark' : ''}>{shot.day}</span><span>{clock(shot.start)}</span>
              </span>
              <span class="line-clamp-2 px-0.5 text-xs">{shot.reason || shot.story_title}</span>
            </button>
          </li>
        {:else}
          <li class="col-span-full"><Text color="muted">{t('No pictures match this filter.')}</Text></li>
        {/each}
      </ol>

      {#if selected}
        <!-- Beside the sheet on a wide screen; over it, closable, on a phone. -->
        <div class={['lg:sticky lg:top-4 lg:block', inspecting ? 'fixed inset-0 z-20 overflow-y-auto bg-light p-4' : 'hidden', 'lg:static lg:z-auto lg:bg-transparent lg:p-0']}>
          <div class="mb-3 lg:hidden">
            <Button size="small" variant="ghost" leadingIcon={mdiArrowLeft} onclick={() => (inspecting = false)}>{t('Back to pictures')}</Button>
          </div>
          <ShotInspector shot={selected} modelPolish={cut.model_polish} />
        </div>
      {/if}
    </div>
  {:else}
    <Text color="muted">{t('No saved cut is available for this run.')}</Text>
  {/if}

  <section class="flex flex-col gap-3 border-t border-gray-200 pt-6 dark:border-gray-800">
    <Heading size="tiny" tag="h2">{t('Run details')}</Heading>
    {#if run.output_path}<p class="text-sm break-all">{t('Saved to: {output_path}', { output_path: run.output_path })}</p>{/if}
    <p class="text-sm">{t('Immich delivery: {value}', { value: run.delivery_status.replaceAll('_', ' ') })}</p>
    {#if run.phases.length}
      <dl class="grid w-fit grid-cols-[auto_auto] gap-x-6 gap-y-1 text-sm tabular-nums">
        {#each run.phases as phase, index (index)}
          <dt class="capitalize">{phase.name.replaceAll('_', ' ')}</dt><dd>{phase.seconds.toFixed(1)} s</dd>
          {#each phase.errors as problem, index (index)}<dd class="col-span-2 text-xs whitespace-pre-wrap text-danger">{problem}</dd>{/each}
        {/each}
      </dl>
    {/if}
    {#if run.child_output}
      <Button href={`/api/v1/runs/${encodeURIComponent(run.run_id)}/child-output`} size="small" variant="outline" leadingIcon={mdiDownload} class="w-fit">{t('Download child output')}</Button>
    {:else if run.source !== 'manual'}
      <Text size="small" color="muted">{t('No child output was retained for this run.')}</Text>
    {/if}
  </section>
</div>
