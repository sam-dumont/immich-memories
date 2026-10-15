<script lang="ts">
  import { Badge, Button, Heading, Text, type Color } from '@immich/ui';
  import { mdiPlayCircleOutline } from '@mdi/js';
  import { api } from './api';
  import type { components } from './api-types';
  import { N_, t } from './i18n.svelte';

  type ConfigWarnings = components['schemas']['ConfigWarnings'];
  type PreflightCheck = components['schemas']['PreflightCheck'];

  // Bumped after a save, so the config warnings follow what was saved.
  let { reloads = 0 }: { reloads?: number } = $props();
  let warnings = $state<string[]>([]);
  let checks = $state<PreflightCheck[] | null>(null);
  let checking = $state(false);
  let failed = $state(false);

  const STATUS: Record<PreflightCheck['status'], { label: string; color: Color }> = {
    ok: { label: N_('OK'), color: 'success' },
    warning: { label: N_('Warning'), color: 'warning' },
    error: { label: N_('Error'), color: 'danger' },
    skipped: { label: N_('Skipped'), color: 'secondary' },
  };

  async function loadWarnings() {
    try { warnings = (await api<ConfigWarnings>('/settings/warnings')).warnings; }
    catch { warnings = []; }
  }
  // The same checks `immich-memories preflight` runs. They ask Immich and the reader and probe the
  // encoder, so they run when asked, not on every visit.
  async function runChecks() {
    checking = true;
    failed = false;
    try { checks = await api<PreflightCheck[]>('/preflight'); }
    catch { failed = true; }
    finally { checking = false; }
  }
  $effect(() => { void reloads; void loadWarnings(); });
</script>

<section class="flex flex-col gap-3" aria-label={t('Checks')}>
  <div class="flex flex-wrap items-center justify-between gap-2">
    <Heading size="small" tag="h2">{t('Checks')}</Heading>
    <Button size="small" variant="outline" leadingIcon={mdiPlayCircleOutline} loading={checking} onclick={runChecks}>{checks ? t('Run the checks again') : t('Run the preflight checks')}</Button>
  </div>
  {#if warnings.length}
    <div class="rounded-xl border border-warning p-4" role="alert" aria-label={t('Config warnings')}>
      <p class="font-medium">{t('Loading your config warned about these keys:')}</p>
      <ul class="mt-2 flex list-disc flex-col gap-1 pl-5 text-sm">
        {#each warnings as warning (warning)}<li class="whitespace-pre-line break-words">{warning}</li>{/each}
      </ul>
    </div>
  {/if}
  {#if checks}
    <ul class="flex flex-col divide-y divide-gray-200 rounded-xl border border-gray-200 dark:divide-gray-800 dark:border-gray-800" aria-label={t('Preflight checks')}>
      {#each checks as check, index (index)}
        <li class="flex flex-col gap-1 px-4 py-2">
          <span class="flex items-center gap-2">
            <Badge size="tiny" color={STATUS[check.status].color}>{t(STATUS[check.status].label)}</Badge>
            <span class="font-medium">{check.name}</span>
          </span>
          <span class="text-sm break-words">{check.message}</span>
          {#if check.details && check.status !== 'ok'}<span class="text-xs break-words text-gray-600 dark:text-gray-400">{check.details}</span>{/if}
        </li>
      {/each}
    </ul>
  {:else if checking}
    <Text color="muted">{t('Running the preflight checks...')}</Text>
  {:else if failed}
    <Text color="danger">{t('The checks could not be run.')}</Text>
  {/if}
</section>
