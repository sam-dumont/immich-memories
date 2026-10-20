<script lang="ts">
  import { Button, Heading, Text } from '@immich/ui';
  import { mdiUpdate } from '@mdi/js';
  import { api } from './api';
  import type { components } from './api-types';
  import { docsPage } from './docs';
  import { t } from './i18n.svelte';

  type UpdateStatus = components['schemas']['UpdateStatus'];

  let status = $state<UpdateStatus | null>(null);
  let checking = $state(false);
  let failed = $state(false);

  // Nothing goes out until this is clicked: it is the one request, made on demand.
  async function check() {
    checking = true;
    failed = false;
    try { status = await api<UpdateStatus>('/updates'); }
    catch { failed = true; }
    finally { checking = false; }
  }
</script>

<section class="flex max-w-3xl flex-col gap-3" aria-label={t('Updates')}>
  <Heading size="small" tag="h2">{t('Updates')}</Heading>
  <Text color="muted">{t('Asks GitHub for the public list of releases. Nothing goes out until you click, and nothing about this install goes with the request.')}</Text>
  <div class="flex flex-wrap items-center gap-3">
    <Button size="small" variant="outline" leadingIcon={mdiUpdate} loading={checking} onclick={check}>{t('Check for updates')}</Button>
    <a class="text-sm text-primary underline" href={docsPage('run/maintenance/upgrading')} target="_blank" rel="noopener noreferrer">{t('Upgrading guide')}</a>
  </div>
  <div role="status" class="flex flex-col gap-1 text-sm" data-testid="update-result">
    {#if failed}
      <span class="text-danger">{t('Could not check for updates.')}</span>
    {:else if status?.status === 'failed'}
      <span class="text-danger">{t('Could not check for updates: {reason}', { reason: status.reason ?? '' })}</span>
    {:else if status?.status === 'current'}
      <span>{t("You're up to date.")}</span>
    {:else if status?.status === 'available'}
      <span class="font-medium">{t('{version} is out', { version: status.latest ?? '' })}</span>
      <a class="text-primary underline" href={status.notes_url} target="_blank" rel="noopener noreferrer">{t('Release notes')}</a>
      {#if status.command}
        <span>{t('Update with:')}</span>
        <code class="w-fit max-w-full overflow-x-auto rounded-lg bg-gray-100 px-3 py-2 dark:bg-gray-900">{status.command}</code>
      {:else}
        <a class="text-primary underline" href={status.docs_url} target="_blank" rel="noopener noreferrer">{t('How to update this install')}</a>
      {/if}
    {/if}
  </div>
</section>
