<script lang="ts">
  import { Button, Heading, LoadingSpinner, Text } from '@immich/ui';
  import { mdiAccountGroupOutline, mdiCheckCircleOutline, mdiContentSaveOutline, mdiDeleteOutline, mdiRefresh, mdiWifi } from '@mdi/js';
  import { onMount } from 'svelte';
  import { api, post } from '$lib/api';
  import type { components } from '$lib/api-types';
  import { N_, t } from '$lib/i18n.svelte';

  type ActiveConfig = components['schemas']['ActiveConfig'];
  type CacheStats = components['schemas']['CacheStats'];
  type Connection = components['schemas']['Connection'];

  let config = $state<ActiveConfig | null>(null);
  let caches = $state<CacheStats[]>([]);
  let note = $state('');

  let connection = $state<Connection | null>(null);
  let url = $state('');
  let key = $state('');
  let greeting = $state('');
  let refusal = $state('');
  let checking = $state(false);

  const CACHE_LABELS: Record<string, string> = {
    analysis: N_('Analysis cache'),
    video: N_('Video cache'),
    thumbnail: N_('Thumbnail cache'),
    preview: N_('Preview cache'),
  };

  async function load() {
    [config, caches] = await Promise.all([api<ActiveConfig>('/config'), api<CacheStats[]>('/caches')]);
  }
  onMount(() => {
    void load();
    void api<Connection>('/connection').then((found) => {
      connection = found;
      // Someone who started typing before the answer came keeps what they typed.
      if (!url) url = found.url;
    });
  });

  // The key field always loads empty: the stored key never comes to the browser. Empty means keep it.
  async function send(method: 'POST' | 'PUT') {
    checking = true;
    greeting = '';
    refusal = '';
    const response = await fetch(method === 'POST' ? '/api/v1/connection/test' : '/api/v1/connection', {
      method,
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ url, api_key: key }),
    });
    const body = await response.json().catch(() => ({}));
    checking = false;
    if (!response.ok) {
      refusal = typeof body.detail === 'string' ? t(body.detail) : t('The connection could not be checked.');
      return;
    }
    if (method === 'POST') {
      greeting = t('Connected as: {name}', { name: body.user });
      return;
    }
    connection = body;
    key = '';
    greeting = t('Configuration saved!');
    await load();
  }

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

  <section class="flex max-w-3xl flex-col gap-3" aria-label={t('Immich Connection')}>
    <Heading size="small" tag="h2">{t('Immich Connection')}</Heading>
    <form class="grid gap-3 sm:grid-cols-2" onsubmit={(event) => { event.preventDefault(); void send('POST'); }}>
      <label class="flex flex-col gap-1 text-sm font-medium">{t('Immich Server URL')}
        <input class="rounded-lg border border-gray-300 bg-light px-3 py-2 dark:border-gray-700" type="url" bind:value={url} placeholder="https://photos.example.com" autocomplete="url" />
      </label>
      <label class="flex flex-col gap-1 text-sm font-medium">{t('API Key')}
        <input class="rounded-lg border border-gray-300 bg-light px-3 py-2 dark:border-gray-700" type="password" bind:value={key} autocomplete="off"
          placeholder={connection?.has_key ? t('Saved - type a new key to replace it') : ''} />
      </label>
      <div class="flex flex-wrap items-center gap-2 sm:col-span-2">
        <Button type="submit" size="small" variant="outline" leadingIcon={mdiWifi} loading={checking}>{t('Test Connection')}</Button>
        <Button size="small" leadingIcon={mdiContentSaveOutline} disabled={checking} onclick={() => send('PUT')}>{t('Save Config')}</Button>
        {#if greeting}<span class="flex items-center gap-1 text-sm text-success" role="status"><svg viewBox="0 0 24 24" class="size-4 fill-current" aria-hidden="true"><path d={mdiCheckCircleOutline} /></svg>{greeting}</span>{/if}
        {#if refusal}<span class="text-sm text-danger" role="alert">{refusal}</span>{/if}
      </div>
    </form>
  </section>

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
