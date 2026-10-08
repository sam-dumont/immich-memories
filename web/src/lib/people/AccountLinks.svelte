<script lang="ts">
  import { Button } from '@immich/ui';
  import { api, type AccountChoice } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import { personPath, sendPerson } from './rosterApi';
  import type { AccountPerson, Person } from './types';

  let { person, accounts, known, onSaved }: { person: Person; accounts: AccountChoice[]; known: Record<string, AccountPerson[]>; onSaved: (saved: Person) => void } = $props();

  const others = $derived(accounts.filter((a) => !a.primary));
  // The people one could link, with suggestions for this person; read when the card is opened.
  let found = $state<Record<string, AccountPerson[]>>({});
  let picked = $state<Record<string, string>>({});
  let problem = $state('');

  async function open(account: string) {
    found = { ...found, [account]: await api<AccountPerson[]>(`/accounts/${encodeURIComponent(account)}/people?for_person=${encodeURIComponent(person.person_id)}`) };
  }

  const body = (account: string, aliasId: string) => ({ account, alias_id: aliasId });
  const nameOf = (account: string, aliasId: string) => (found[account] ?? known[account] ?? []).find((p) => p.id === aliasId)?.name ?? aliasId;

  async function answer(method: string, path: string, account: string, aliasId: string) {
    problem = '';
    const response = await fetch(`/api/v1/roster${personPath(person, path)}`, {
      method,
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body(account, aliasId)),
    });
    if (!response.ok) {
      problem = ((await response.json().catch(() => ({}))) as { detail?: string }).detail ?? t('That id could not be bound.');
      return;
    }
    onSaved((await response.json()) as Person);
    if (found[account]) await open(account);
  }

  const link = (account: string, aliasId: string) => answer('POST', '/aliases', account, aliasId);
  const unlink = (account: string, aliasId: string) => answer('DELETE', '/aliases', account, aliasId);
  const decline = (account: string, aliasId: string) => answer('POST', '/aliases/declined', account, aliasId);

  const free = (account: string) => (found[account] ?? []).filter((p) => !p.linked_to);
</script>

<div class="flex flex-col gap-2" data-testid="account-links">
  <p class="text-xs font-medium">{t('Accounts')}</p>
  {#each others as account (account.name)}
    <div class="flex flex-col gap-1" data-testid="account-link" data-account={account.name}>
      <p class="text-xs text-gray-600 dark:text-gray-400">{account.name}</p>
      {#each person.aliases[account.name] ?? [] as aliasId (aliasId)}
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="font-medium">{nameOf(account.name, aliasId)}</span>
          {#if person.alias_urls[aliasId] && /^https?:\/\//i.test(person.alias_urls[aliasId])}<a href={person.alias_urls[aliasId]} target="_blank" rel="noreferrer" class="text-primary underline">{t('Open in Immich')}</a>{/if}
          <Button size="tiny" variant="ghost" onclick={() => unlink(account.name, aliasId)}>{t('Unlink')}</Button>
        </div>
      {/each}
      <details ontoggle={(event) => event.currentTarget.open && found[account.name] === undefined && void open(account.name)}>
      <summary class="cursor-pointer text-xs">{t('Link a person from {account}', { account: account.name })}</summary>
      {#each free(account.name).filter((p) => p.suggested) as suggestion (suggestion.id)}
        <div class="flex flex-wrap items-center gap-2 text-sm" data-testid="link-suggestion">
          <img src={`/api/v1/people/${encodeURIComponent(suggestion.id)}/face`} alt="" class="size-8 rounded-full bg-gray-100 object-cover dark:bg-gray-900" loading="lazy"
            onerror={(event) => ((event.currentTarget as HTMLImageElement).style.visibility = 'hidden')} />
          <span>{t('Same person as {name}?', { name: suggestion.name })}{suggestion.pictures != null ? ` · ${t('Pictures: {count}', { count: suggestion.pictures })}` : ''}</span>
          <Button size="tiny" variant="outline" onclick={() => link(account.name, suggestion.id)}>{t('Link')}</Button>
          <Button size="tiny" variant="ghost" onclick={() => decline(account.name, suggestion.id)}>{t('Not the same person')}</Button>
        </div>
      {/each}
      <form class="mt-1 flex flex-wrap gap-2" onsubmit={(event) => { event.preventDefault(); if (picked[account.name]) void link(account.name, picked[account.name]); }}>
        <select class="rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm dark:border-gray-700" aria-label={t('Person in {account}', { account: account.name })} bind:value={picked[account.name]}>
          <option value="">{t('Person in {account}', { account: account.name })}</option>
          {#each free(account.name).filter((p) => !p.suggested) as option (option.id)}
            <option value={option.id}>{option.name}{option.pictures != null ? ` (${option.pictures})` : ''}</option>
          {/each}
        </select>
        <Button type="submit" size="tiny" variant="outline">{t('Link')}</Button>
      </form>
      </details>
    </div>
  {/each}
  {#if problem}<p class="text-xs text-danger" role="alert">{problem}</p>{/if}
</div>
