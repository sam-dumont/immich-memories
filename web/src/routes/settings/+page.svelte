<script lang="ts">
  import { Button, Heading, LoadingSpinner, Text } from '@immich/ui';
  import { mdiAccountGroupOutline, mdiDeleteOutline, mdiRefresh } from '@mdi/js';
  import { onMount } from 'svelte';
  import { api, post } from '$lib/api';
  import type { components } from '$lib/api-types';
  import { t } from '$lib/i18n.svelte';

  type ActiveConfig = components['schemas']['ActiveConfig'];
  type CacheStats = components['schemas']['CacheStats'];

  let config = $state<ActiveConfig | null>(null);
  let caches = $state<CacheStats[]>([]);
  let note = $state('');

  const CACHE_LABELS: Record<string, string> = {
    analysis: 'Analysis cache',
    video: 'Video cache',
    thumbnail: 'Thumbnail cache',
    preview: 'Preview cache',
  };

  async function load() {
    [config, caches] = await Promise.all([api<ActiveConfig>('/config'), api<CacheStats[]>('/caches')]);
  }
  onMount(() => void load());

  async function clear(name: string) {
    const { body } = await post<{ removed: number }>(`/caches/${name}/clear`, {});
    note = t('Cleared {count} entries from the {cache}.', { count: body.removed, cache: t(CACHE_LABELS[name]).toLowerCase() });
    caches = await api<CacheStats[]>('/caches');
  }

  const size = (bytes: number) =>
    bytes < 1024 ** 2 ? `${(bytes / 1024).toFixed(1)} KB` : bytes < 1024 ** 3 ? `${(bytes / 1024 ** 2).toFixed(1)} MB` : `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  const show = (value: unknown) =>
    Array.isArray(value) ? (value.length ? value.join(', ') : '—') : value === null || value === '' ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value);
</script>

<svelte:head><title>{t('Settings')} · Immich Memories</title></svelte:head>

<div class="flex flex-col gap-8">
  <div class="flex flex-col gap-1">
    <Heading size="large" tag="h1">{t('Settings')}</Heading>
    <Text color="muted">{t('What this server runs with. The file is the source; environment overrides apply; secrets are masked.')}</Text>
  </div>

  <a href="/app/settings/people" class="flex w-fit items-center gap-3 rounded-2xl border border-gray-200 px-4 py-3 hover:border-primary dark:border-gray-800">
    <svg viewBox="0 0 24 24" class="size-6 fill-current text-primary" aria-hidden="true"><path d={mdiAccountGroupOutline} /></svg>
    <span><span class="block font-medium">{t('People')}</span><span class="text-sm text-gray-600 dark:text-gray-400">{t('Who is who, their roles and relationships.')}</span></span>
  </a>

  <section class="flex flex-col gap-3" aria-label={t('Configuration')}>
    <div class="flex flex-wrap items-center justify-between gap-2">
      <Heading size="small" tag="h2">{t('Configuration')}</Heading>
      <Button size="small" variant="outline" leadingIcon={mdiRefresh} onclick={load}>{t('Reload from Disk')}</Button>
    </div>
    {#if !config}
      <LoadingSpinner />
    {:else}
      <p class="text-sm text-gray-600 dark:text-gray-400">
        {t('Config file: {config_path}', { config_path: config.path })}{config.preset ? ` · ${t('Preset: {preset}', { preset: config.preset })}` : ''}
      </p>
      {#each Object.entries(config.sections).filter(([, v]) => v && typeof v === 'object' && !Array.isArray(v)) as [section, values] (section)}
        <details class="rounded-xl border border-gray-200 dark:border-gray-800">
          <summary class="cursor-pointer px-4 py-2 font-medium capitalize">{section.replaceAll('_', ' ')}</summary>
          <table class="w-full text-sm">
            <tbody>
              {#each Object.entries(values as Record<string, unknown>) as [key, value] (key)}
                <tr class="border-t border-gray-200 dark:border-gray-800">
                  <th class="w-1/3 px-4 py-1.5 text-left font-normal text-gray-600 dark:text-gray-400">{key}</th>
                  <td class="px-4 py-1.5 break-all">{show(value)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </details>
      {/each}
    {/if}
  </section>

  <section class="flex flex-col gap-3" aria-label={t('Caches')}>
    <Heading size="small" tag="h2">{t('Caches')}</Heading>
    <ul class="flex flex-col divide-y divide-gray-200 rounded-xl border border-gray-200 dark:divide-gray-800 dark:border-gray-800">
      {#each caches as cache (cache.name)}
        <li class="flex flex-wrap items-center justify-between gap-2 px-4 py-2">
          <span><span class="font-medium">{t(CACHE_LABELS[cache.name])}</span> <span class="text-sm text-gray-600 tabular-nums dark:text-gray-400">{t('Entries: {count}', { count: cache.items })} · {size(cache.bytes)}</span></span>
          <Button size="small" variant="ghost" color="danger" leadingIcon={mdiDeleteOutline} disabled={!cache.items} onclick={() => clear(cache.name)}>{t('Clear')}</Button>
        </li>
      {/each}
    </ul>
    {#if note}<p class="text-sm" role="status">{note}</p>{/if}
  </section>
</div>
