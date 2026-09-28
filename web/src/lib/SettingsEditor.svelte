<script lang="ts">
  import { Alert, Button, Heading, LoadingSpinner } from '@immich/ui';
  import { mdiContentSaveOutline, mdiRefresh } from '@mdi/js';
  import { api, post } from '$lib/api';
  import type { components } from '$lib/api-types';
  import { t } from '$lib/i18n.svelte';

  type SettingsView = components['schemas']['SettingsView'];
  type SettingRow = components['schemas']['SettingRow'];

  // Bumped by the page when something else (the connection form) saved a setting.
  let { reloads = 0 }: { reloads?: number } = $props();

  const SECRET_KEY_ENV = 'IMMICH_MEMORIES_SECRET_KEY';
  const OPEN_SECTIONS = new Set(['immich', 'defaults', 'output']);

  let view = $state<SettingsView | null>(null);
  // What the owner typed, by key; only these are sent, and only for the section being saved.
  let drafts = $state<Record<string, unknown>>({});
  let saving = $state('');
  let answers = $state<Record<string, { ok: boolean; text: string }>>({});

  async function load() {
    view = await api<SettingsView>('/settings');
    drafts = {};
  }

  $effect(() => {
    void reloads;
    void load();
  });

  const asText = (value: unknown) =>
    value === null || value === undefined ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);

  function origin(row: SettingRow): string {
    if (row.source === 'env') return t('Set by {name} (environment)', { name: row.override ?? '' });
    if (row.source === 'file') return t('Set in config.yaml as {key}', { key: row.override ?? '' });
    if (row.unreadable) return t('Saved here, but {name} cannot decrypt it: the default is in use', { name: SECRET_KEY_ENV });
    if (row.source === 'database') return t('Saved here');
    return t('Default');
  }

  const edited = (section: string) => Object.keys(drafts).filter((key) => key.startsWith(`${section}.`));

  async function save(section: string) {
    saving = section;
    const values = Object.fromEntries(edited(section).map((key) => [key, drafts[key]]));
    const { status, body } = await post<SettingsView>('/settings', { values });
    saving = '';
    if (status !== 200) {
      answers = { ...answers, [section]: { ok: false, text: body.detail ?? t('The settings could not be saved.') } };
      return;
    }
    view = body;
    drafts = Object.fromEntries(Object.entries(drafts).filter(([key]) => !key.startsWith(`${section}.`)));
    answers = { ...answers, [section]: { ok: true, text: t('Saved to the database') } };
  }

  const field = 'w-full rounded-lg border border-gray-300 bg-light px-3 py-1.5 disabled:opacity-60 dark:border-gray-700';
</script>

<section class="flex flex-col gap-3" aria-label={t('Configuration')}>
  <div class="flex flex-wrap items-center justify-between gap-2">
    <Heading size="small" tag="h2">{t('Configuration')}</Heading>
    <Button size="small" variant="outline" leadingIcon={mdiRefresh} onclick={load}>{t('Reload from Disk')}</Button>
  </div>
  {#if !view}
    <LoadingSpinner />
  {:else}
    <p class="text-sm text-gray-600 dark:text-gray-400">
      {t('Config file: {config_path}', { config_path: view.config_path })} ·
      {t('The environment wins, then config.yaml, then what is saved here, then the default. A setting either of the first two sets is greyed out: change it where its label says.')}
    </p>
    {#if !view.can_store_secrets}
      <Alert color="warning" size="small">{t('Secrets cannot be saved here until {name} is set. Set it, or keep them in the environment or config.yaml.', { name: SECRET_KEY_ENV })}</Alert>
    {/if}
    {#each view.sections as section (section.name)}
      <details class="rounded-xl border border-gray-200 dark:border-gray-800" open={OPEN_SECTIONS.has(section.name)}>
        <summary class="cursor-pointer px-4 py-2 font-medium capitalize">{section.name.replaceAll('_', ' ')}</summary>
        <div class="flex flex-col divide-y divide-gray-200 dark:divide-gray-800">
          {#each section.settings as row (row.key)}
            {@const name = row.key.slice(section.name.length + 1)}
            <div class="grid gap-1 px-4 py-2 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)] sm:items-center sm:gap-4">
              <div class="min-w-0">
                <span class="block text-sm break-all">{name}</span>
                <span class="block text-xs text-gray-600 dark:text-gray-400">{origin(row)}</span>
              </div>
              {#if typeof row.value === 'boolean'}
                <input type="checkbox" class="size-5 justify-self-start" aria-label={row.key} disabled={!row.editable}
                  checked={(drafts[row.key] ?? row.value) as boolean} onchange={(event) => (drafts[row.key] = event.currentTarget.checked)} />
              {:else if row.secret}
                <input class={field} type="password" autocomplete="off" aria-label={row.key} disabled={!row.editable}
                  placeholder={row.value ? t('Saved - type a new key to replace it') : ''} oninput={(event) => (drafts[row.key] = event.currentTarget.value)} />
              {:else}
                <input class={field} aria-label={row.key} disabled={!row.editable}
                  value={asText(drafts[row.key] ?? row.value)} oninput={(event) => (drafts[row.key] = event.currentTarget.value)} />
              {/if}
            </div>
          {/each}
        </div>
        <div class="flex flex-wrap items-center gap-3 border-t border-gray-200 px-4 py-2 dark:border-gray-800">
          <Button size="small" leadingIcon={mdiContentSaveOutline} loading={saving === section.name} disabled={!edited(section.name).length}
            onclick={() => save(section.name)}>{t('Save')}</Button>
          {#if answers[section.name]}
            <span class={['text-sm', answers[section.name].ok ? 'text-success' : 'text-danger']} role={answers[section.name].ok ? 'status' : 'alert'}>{answers[section.name].text}</span>
          {/if}
        </div>
      </details>
    {/each}
  {/if}
</section>
