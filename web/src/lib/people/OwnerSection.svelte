<script lang="ts">
  import { Heading, Text } from '@immich/ui';
  import { api } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { AccountOwner } from './types';

  // The sentinel for "Nobody in this library"; a person id is never this.
  const NOBODY = '__nobody__';

  let { refresh = 0 }: { refresh?: number } = $props();
  let owners = $state<AccountOwner[]>([]);
  let problem = $state('');

  let loadVersion = 0;
  $effect(() => {
    refresh;
    const version = ++loadVersion;
    void api<AccountOwner[]>('/roster/owners')
      .then((found) => { if (version === loadVersion) owners = found; })
      .catch(() => { if (version === loadVersion) owners = []; });
  });

  function how(owner: AccountOwner): string {
    if (owner.how === 'confirmed') return t('you confirmed it');
    if (owner.how === 'told') return t('you told the scan');
    if (owner.how === 'account') return t('it matches the Immich account name');
    if (owner.how === 'inferred') return t('a guess: the longest span and the most pictures');
    return t('not known yet');
  }

  async function choose(owner: AccountOwner, value: string) {
    if (!value) return;
    problem = '';
    const response = await fetch(`/api/v1/roster/owners/${encodeURIComponent(owner.account)}`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ person_id: value === NOBODY ? null : value }),
    });
    if (!response.ok) {
      problem = ((await response.json().catch(() => ({}))) as { detail?: string }).detail ?? t('That could not be saved.');
      return;
    }
    const saved = (await response.json()) as AccountOwner;
    // A scan read started before this save must not replace the confirmed answer.
    loadVersion += 1;
    owners = owners.map((o) => (o.account === saved.account ? saved : o));
  }
</script>

<section class="flex flex-col gap-2 rounded-2xl border border-gray-200 p-4 dark:border-gray-800" aria-label={t('Account owner')} data-testid="owners">
  <Heading size="tiny" tag="h2">{t('Account owner')}</Heading>
  <Text size="small" color="muted">{t('Whose library is this? Relationships to the library owner, the family seat and the titles depend on it. A scan only guesses; what you pick here stays.')}</Text>
  {#each owners as owner (owner.account)}
    <div class="flex flex-wrap items-center gap-2 text-sm" data-testid="owner-row" data-account={owner.account}>
      {#if owners.length > 1}<span class="text-gray-600 dark:text-gray-400">{owner.account}</span>{/if}
      <span class="font-medium" data-testid="owner-name">{owner.nobody ? t('Nobody in this library') : (owner.name ?? t('not known yet'))}</span>
      <span class="text-xs text-gray-600 dark:text-gray-400">({how(owner)})</span>
      <select class="rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm dark:border-gray-700" aria-label={owners.length > 1 ? t('Owner of {account}', { account: owner.account }) : t('Choose the owner')}
        value="" onchange={(event) => choose(owner, event.currentTarget.value)}>
        <option value="">{t('Choose the owner')}</option>
        {#each owner.choices as choice (choice.person_id)}<option value={choice.person_id}>{choice.name}</option>{/each}
        <option value={NOBODY}>{t('Nobody in this library')}</option>
      </select>
      {#if !owner.nobody && !owner.person_id}
        <p class="basis-full text-xs text-gray-600 dark:text-gray-400">{t('The API key\'s account name has not been matched to a named person. Choose the owner, or name people in Immich and rescan.')}</p>
      {/if}
    </div>
  {/each}
  {#if problem}<p class="text-xs text-danger" role="alert">{problem}</p>{/if}
</section>
