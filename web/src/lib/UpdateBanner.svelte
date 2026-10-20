<script lang="ts">
  import { mdiClose } from '@mdi/js';
  import { onMount } from 'svelte';
  import { api } from './api';
  import type { components } from './api-types';
  import { t } from './i18n.svelte';

  type UpdateStatus = components['schemas']['UpdateStatus'];

  const DISMISSED = 'update-dismissed';
  let status = $state<UpdateStatus | null>(null);
  let dismissed = $state('');

  // The answer is null unless `updates.check_daily` is on; this page never asks GitHub itself.
  onMount(() => {
    dismissed = localStorage.getItem(DISMISSED) ?? '';
    void api<UpdateStatus | null>('/updates/daily').then((found) => (status = found)).catch(() => (status = null));
  });

  const showing = $derived(status?.status === 'available' && status.latest !== dismissed);

  function dismiss() {
    dismissed = status?.latest ?? '';
    localStorage.setItem(DISMISSED, dismissed);
  }
</script>

{#if showing && status}
  <div class="flex items-center justify-between gap-3 bg-primary/10 px-4 py-2 text-sm" role="status" data-testid="update-banner">
    <span>
      <span class="font-medium">{t('{version} is out', { version: status.latest ?? '' })}</span>
      <a class="ml-2 text-primary underline" href={status.notes_url} target="_blank" rel="noopener noreferrer">{t('Release notes')}</a>
      <a class="ml-2 text-primary underline" href="/app/settings">{t('How to update')}</a>
    </span>
    <button type="button" class="rounded-full p-1 hover:bg-primary/10" aria-label={t('Dismiss')} onclick={dismiss}>
      <svg viewBox="0 0 24 24" class="size-4 fill-current" aria-hidden="true"><path d={mdiClose} /></svg>
    </button>
  </div>
{/if}
