<script lang="ts">
  import { Button, ProgressBar } from '@immich/ui';
  import { mdiContentCopy, mdiStop } from '@mdi/js';
  import { thumbnail, type JobView } from './api';
  import { t } from './i18n.svelte';
  import { stageLabel } from './labels';

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
      .then((body) => (output = String(body.output ?? '').split('\n').slice(-25).join('\n')));
  });

  const elapsed = $derived.by(() => {
    const seconds = Math.max(0, Math.round(((job.finished_at ?? now / 1000) - job.started_at)));
    const minutes = Math.floor(seconds / 60);
    return minutes ? `${minutes}m ${String(seconds % 60).padStart(2, '0')}s` : `${seconds}s`;
  });
  const fraction = $derived(job.progress.fraction ?? null);
  const heading = $derived(
    job.progress.stage_name && stageLabel(job.progress.stage_name) !== job.progress.stage_name
      ? stageLabel(job.progress.stage_name)
      : job.progress.label,
  );
  const clockText = (seconds: number) => (seconds < 60 ? `${Math.ceil(seconds)}s` : `${Math.ceil(seconds / 60)} min`);
  // Rounded on purpose, as the terminal rounds it: a stage estimate, not a countdown.
  const remaining = $derived.by(() => {
    const seconds = job.progress.remaining_seconds;
    return seconds == null ? '' : t('~{amount} left in this stage', { amount: clockText(seconds) });
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
      {:else if job.status === 'succeeded'}{job.kind === 'cut' ? t('The cut is ready.') : t('The film is ready.')}
      {:else if job.status === 'cancelled'}{t('Stopped.')}
      {:else}{t('It did not finish.')}{/if}
    </p>
    <span class="text-sm text-gray-600 tabular-nums dark:text-gray-400">{elapsed}</span>
  </div>

  {#if job.status === 'running'}
    <ProgressBar value={fraction ?? 0} valueLabel={fraction == null ? heading : `${Math.round(fraction * 100)}%`} aria-label={t('Progress')} />
    <p class="text-sm text-gray-600 tabular-nums dark:text-gray-400">
      {#if job.progress.total}{t('{done} of {total}', { done: job.progress.done ?? 0, total: job.progress.total })}{#if remaining} · {remaining}{/if}{/if}
    </p>
    {#if job.progress.recent_asset_ids.length}
      <ul class="flex gap-2 overflow-hidden" aria-label={t('Pictures just read')}>
        {#each job.progress.recent_asset_ids.slice(-8) as asset (asset)}
          <li class="shrink-0"><img src={thumbnail(asset)} alt="" class="h-16 w-16 rounded-lg object-cover" /></li>
        {/each}
      </ul>
    {/if}
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
