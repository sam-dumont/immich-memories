<script lang="ts">
  import { Alert, Button } from '@immich/ui';
  import { mdiContentCopy } from '@mdi/js';
  import { api } from './api';
  import { t } from './i18n.svelte';

  let { runId }: { runId: string } = $props();
  let markdown = $state('');
  let loading = $state(false);
  let copied = $state(false);
  let problem = $state('');
  let hasFlaggedPhotos = $state(false);
  let includeCaptions = $state(false);
  let requestNumber = 0;

  $effect(() => {
    void runId;
    markdown = '';
    loading = false;
    copied = false;
    problem = '';
    hasFlaggedPhotos = false;
    includeCaptions = false;
    requestNumber += 1;
  });

  async function preview() {
    loading = true;
    problem = '';
    const requested = runId;
    const request = ++requestNumber;
    copied = false;
    try {
      const query = includeCaptions ? '?include_flagged_captions=true' : '';
      const report = await api<{ markdown: string; has_flagged_photos: boolean }>(`/runs/${encodeURIComponent(requested)}/report${query}`);
      if (requested === runId && request === requestNumber) {
        markdown = report.markdown;
        hasFlaggedPhotos = report.has_flagged_photos;
      }
    } catch {
      if (request === requestNumber) {
        markdown = '';
        problem = t('The report could not be loaded.');
      }
    } finally {
      if (request === requestNumber) loading = false;
    }
  }

  async function copy() {
    problem = '';
    try {
      await navigator.clipboard.writeText(markdown);
      copied = true;
    } catch {
      problem = t('Clipboard unavailable. Select the report below and copy it.');
    }
  }
</script>

<div class="flex flex-col items-start gap-3">
  {#if markdown}
    <p class="text-sm text-gray-600 dark:text-gray-400">{t('Review the report, then copy it. Nothing is sent automatically.')}</p>
    {#if hasFlaggedPhotos}
      <label class="flex items-center gap-2 text-sm"><input type="checkbox" bind:checked={includeCaptions} onchange={preview} disabled={loading} />{t('Include captions of flagged photos')}</label>
    {/if}
    <pre aria-label={t('Report preview')} class="max-h-80 w-full overflow-auto rounded-lg bg-gray-100 p-3 text-xs whitespace-pre-wrap select-text dark:bg-gray-900">{markdown}</pre>
    <Button size="small" variant="outline" leadingIcon={mdiContentCopy} disabled={loading} onclick={copy}>{copied ? t('Copied') : t('Copy report')}</Button>
  {:else}
    <Button size="small" variant="outline" leadingIcon={mdiContentCopy} disabled={loading} onclick={preview}>{t('Copy report')}</Button>
  {/if}
  {#if problem}<Alert color="warning" size="small">{problem}</Alert>{/if}
</div>
