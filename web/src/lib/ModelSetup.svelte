<script lang="ts">
  import { onMount } from 'svelte';
  import { Button } from '@immich/ui';
  import { mdiDownload } from '@mdi/js';
  import { api, post, type JobView } from './api';
  import type { components } from './api-types';
  import { followJob } from './job.svelte';
  import { t } from './i18n.svelte';
  import JobPanel from './JobPanel.svelte';

  type ModelStatus = components['schemas']['ModelAcquisitionStatus'];
  let { reloads = 0 }: { reloads?: number } = $props();
  let status = $state<ModelStatus | null>(null);
  let job = $state<JobView | null>(null);
  let error = $state('');
  let starting = $state(false);
  let stop: (() => void) | undefined;
  const LAST_DOWNLOAD = 'immich-memories:last-model-download';
  function remember(id: string) { try { localStorage.setItem(LAST_DOWNLOAD, id); } catch { /* private window */ } }
  function recalled() { try { return localStorage.getItem(LAST_DOWNLOAD); } catch { return null; } }

  async function load() {
    try { status = await api<ModelStatus>('/models'); }
    catch { error = t('Model status could not be checked.'); }
  }
  function follow(started: JobView) {
    job = started;
    remember(started.id);
    stop?.();
    stop = followJob(started.id, (update) => {
      job = update;
      if (update.status !== 'running') void load();
    });
  }
  $effect(() => { void reloads; void load(); });
  onMount(() => {
    void api<JobView | null>('/jobs/active').then(async (active) => {
      if (active?.kind === 'models') return follow(active);
      const last = recalled();
      if (!last) return;
      const earlier = await api<JobView>(`/jobs/${encodeURIComponent(last)}`).catch(() => null);
      if (earlier?.kind === 'models' && ['failed', 'interrupted', 'cancelled'].includes(earlier.status)) job = earlier;
    }).catch(() => {});
    return () => stop?.();
  });
  async function download() {
    starting = true;
    error = '';
    try {
      const result = await post<JobView>('/models/fetch', { plan_id: status?.plan_id });
      if (result.status === 202) follow(result.body);
      else if (result.status === 409 && result.body.job?.kind === 'models') follow(result.body.job);
      else {
        error = result.body.detail ?? t('Model downloads failed to start.');
        if (result.status === 409) await load();
      }
    } catch { error = t('Model downloads failed to start.'); }
    finally { starting = false; }
  }
  async function cancel() {
    if (job) job = (await post<JobView>(`/jobs/${encodeURIComponent(job.id)}/cancel`, {})).body;
  }
</script>

{#if status && !status.ready}
  <section class="flex flex-col gap-4 rounded-2xl border border-gray-200 p-5 dark:border-gray-800" aria-label={t('Download models')}>
    <h2 class="font-semibold">{t('Download models')}</h2>
    <p class="text-sm text-gray-600 dark:text-gray-400">{t('Your first film needs these model files. Nothing downloads until you press the button.')}</p>
    <ul class="flex flex-col gap-3 text-sm">
      {#each status.artifacts.filter((item) => !item.ready) as item (item.label)}
        <li>
          <p class="font-medium">{item.label}</p>
          <p>{item.size} · {item.host}</p>
          <code class="block break-all text-xs text-gray-600 dark:text-gray-400">{item.sha256 ? `SHA-256: ${item.sha256}` : `Revision: ${item.revision}`}</code>
        </li>
      {/each}
    </ul>
    <p class="text-sm text-gray-600 dark:text-gray-400">{t('Download hosts can redirect to their CDNs.')}</p>
    {#if job}<JobPanel {job} onCancel={cancel} />{/if}
    {#if error}<p class="text-sm text-danger" role="alert">{error}</p>{/if}
    <Button leadingIcon={mdiDownload} disabled={starting || job?.status === 'running'} onclick={download}>{t('Download models')}</Button>
  </section>
{:else if error}
  <p class="text-sm text-danger" role="alert">{error}</p>
{/if}
