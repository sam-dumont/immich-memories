<script lang="ts">
  import { Button, ProgressBar } from '@immich/ui';
  import { mdiContentCopy, mdiStop } from '@mdi/js';
  import { thumbnail, type JobView } from './api';
  import { t } from './i18n.svelte';
  import { progressCount, stageLabel } from './labels';
  import { jobConnection } from './job.svelte';
  import PhaseTimeline from './PhaseTimeline.svelte';

  let { job, onCancel }: { job: JobView; onCancel: () => void } = $props();

  let now = $state(Date.now());
  let output = $state('');
  let copied = $state(false);

  $effect(() => {
    if (job.status !== 'running') return;
    const timer = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(timer);
  });

  // A failed job says why in the child's own words.
  $effect(() => {
    if (job.status !== 'failed' && job.status !== 'interrupted') return;
    void fetch(`/api/v1/jobs/${encodeURIComponent(job.id)}/output`)
      .then((response) => response.json())
      .then((body) => (output = String(body.output ?? '').split('\n').slice(-25).join('\n')))
      .catch(() => { output = ''; });
  });

  const elapsed = $derived.by(() => {
    const seconds = Math.max(0, Math.round(((job.finished_at ?? now / 1000) - job.started_at)));
    const minutes = Math.floor(seconds / 60);
    return minutes ? `${minutes}m ${String(seconds % 60).padStart(2, '0')}s` : `${seconds}s`;
  });
  const connection = $derived(jobConnection(job.id));
  const fraction = $derived(job.progress.fraction_scope === 'stage'
    ? job.progress.stage_fraction ?? null
    : job.progress.fraction_scope === 'job' ? job.progress.fraction ?? null : null);
  const fractionLabel = $derived(fraction == null ? '' : job.progress.fraction_scope === 'stage'
    ? t('{percent}% of this stage', { percent: Math.round(fraction * 100) })
    : t('About {percent}% overall', { percent: Math.round(fraction * 100) }));
  const stale = $derived(job.progress.updated_at != null && now / 1000 - job.progress.updated_at > 30);
  const heading = $derived(
    job.progress.stage_name && stageLabel(job.progress.stage_name) !== job.progress.stage_name
      ? stageLabel(job.progress.stage_name)
      : job.progress.label,
  );
  const clockText = (seconds: number) => (seconds < 60 ? `${Math.ceil(seconds)}s` : `${Math.ceil(seconds / 60)} min`);
  // The whole job's estimate when a finished run measured it; a first cut only has its stage's.
  // Rounded on purpose, as the terminal rounds it: an estimate, not a countdown.
  const remaining = $derived.by(() => {
    const total = job.progress.remaining_seconds;
    if (!job.progress.forecast && total != null) return t('About {amount} left overall', { amount: clockText(total) });
    const stage = job.progress.stage_remaining_seconds;
    return stage == null ? '' : t('~{amount} left in this stage', { amount: clockText(stage) });
  });


  async function copy() {
    await navigator.clipboard.writeText(job.command);
    copied = true;
    setTimeout(() => (copied = false), 1500);
  }
</script>

<section class="flex flex-col gap-4 rounded-2xl border border-gray-200 p-5 dark:border-gray-800" aria-live="polite" aria-label={t('Progress')}>
  <div class="flex flex-wrap items-center justify-between gap-3">
    <p class="font-medium">
      {#if job.status === 'running'}{heading || t('Starting')}
      {:else if job.status === 'succeeded'}{job.kind === 'cut' ? t('The cut is ready.') : job.kind === 'render' ? t('The film is ready.') : t('Done.')}
      {:else if job.status === 'cancelled'}{t('Stopped.')}
      {:else}{t('It did not finish.')}{/if}
    </p>
    <span class="text-sm text-gray-600 tabular-nums dark:text-gray-400">{elapsed}</span>
  </div>

  {#if job.status === 'running'}
    {#if job.progress.forecast}<PhaseTimeline forecast={job.progress.forecast} />{/if}
    {#if fraction != null}
      <ProgressBar value={fraction} valueLabel={fractionLabel} aria-label={t('Progress')} />
    {/if}
    <p class="text-sm text-gray-600 tabular-nums dark:text-gray-400">
      {#if job.progress.total}{progressCount(job.progress.unit ?? '', job.progress.done ?? 0, job.progress.total)}{#if remaining}{' · '}{/if}{/if}{remaining}
    </p>
    {#if !job.progress.forecast && job.kind === 'cut' && job.progress.phase === 'analysis'}
      <p class="text-sm">{t('Next: select pictures and save the cut. More checks may be needed during selection.')}</p>
    {:else if !job.progress.forecast && job.kind === 'render' && job.progress.phase !== 'check' && job.progress.phase !== 'done'}
      <p class="text-sm">{t('The film still needs its playback check before it is ready.')}</p>
    {/if}
    {#if !job.progress.forecast && job.progress.remaining_seconds == null}
      <p class="text-sm text-gray-600 dark:text-gray-400">{t('Overall time remaining is not known yet.')}</p>
    {/if}
    {#if connection === 'unauthorized'}
      <p role="status">{t('Your login expired. Sign in again to see the job’s status.')} <a class="underline" href="/app/login">{t('Sign in')}</a></p>
    {:else if connection === 'reconnecting'}
      <p role="status">{t('Live updates disconnected. Checking the saved job status.')}</p>
    {:else if stale}
      <p role="status">{t('No new progress for {amount}. The job is still running.', { amount: clockText(now / 1000 - job.progress.updated_at!) })}</p>
    {/if}
    {#if job.progress.last_completed_at != null && job.progress.total}
      <p class="text-xs text-gray-600 dark:text-gray-400">{t('Last measured progress: {amount} ago.', { amount: clockText(Math.max(0, now / 1000 - job.progress.last_completed_at)) })}</p>
    {/if}
    {#if job.progress.recent_asset_ids.length}
      <ul class="flex gap-2 overflow-hidden" aria-label={t('Pictures just read')}>
        {#each job.progress.recent_asset_ids.slice(-8) as asset (asset)}
          <!-- A preview that fails to load leaves no empty tile in the row. -->
          <li class="shrink-0"><img src={thumbnail(asset)} alt="" class="h-16 w-16 rounded-lg object-cover"
            onerror={(event) => ((event.currentTarget as HTMLImageElement).parentElement!.style.display = 'none')} /></li>
        {/each}
      </ul>
    {/if}
  {/if}

  {#if job.progress.history?.length}
    <details class="text-sm text-gray-600 dark:text-gray-400">
      <summary class="cursor-pointer">{t('Previous stages')}</summary>
      <ol class="mt-2 list-inside list-decimal space-y-1">
        {#each job.progress.history as stage}
          <li>{stageLabel(stage.label)}{#if stage.total != null}: {progressCount(stage.unit, stage.done ?? 0, stage.total)}{/if}
            {#if stage.state === 'processed'} · {t('Processed')}{:else if stage.state === 'reused'} · {t('Reused')}{/if}
          </li>
        {/each}
      </ol>
    </details>
  {/if}

  {#if job.error}
    <p role="alert" class="text-red-700 dark:text-red-300">{job.error}</p>
  {/if}

  {#if output}
    <pre class="max-h-64 overflow-auto rounded-lg bg-gray-100 p-3 text-xs whitespace-pre-wrap dark:bg-gray-900">{output}</pre>
  {/if}

  <div class="flex flex-wrap items-center gap-2">
    <code class="min-w-0 flex-1 truncate rounded-md bg-gray-100 px-2 py-1 text-xs dark:bg-gray-900" title={job.command}>{job.command}</code>
    <Button size="small" variant="ghost" leadingIcon={mdiContentCopy} onclick={copy}>{copied ? t('Copied') : t('Copy as CLI command')}</Button>
    {#if job.status === 'running'}
      <Button size="small" variant="outline" color="danger" leadingIcon={mdiStop} onclick={onCancel}>{t('Cancel')}</Button>
    {/if}
  </div>
</section>
