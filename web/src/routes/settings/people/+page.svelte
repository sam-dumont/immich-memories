<script lang="ts">
  import { Button, Heading, LoadingSpinner, Text } from '@immich/ui';
  import { mdiAccountPlusOutline, mdiRefresh } from '@mdi/js';
  import { onMount } from 'svelte';
  import { api, post, type AccountChoice, type JobView } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import { followJob } from '$lib/job.svelte';
  import JobPanel from '$lib/JobPanel.svelte';
  import GroupsSection from '$lib/people/GroupsSection.svelte';
  import OwnerSection from '$lib/people/OwnerSection.svelte';
  import PersonCard from '$lib/people/PersonCard.svelte';
  import type { AccountPerson, Flag, Person, Roster } from '$lib/people/types';

  const PAGE = 30;
  let roster = $state<Roster | null>(null);
  let query = $state('');
  let shown = $state(PAGE);
  let newName = $state('');
  let scan = $state<JobView | null>(null);
  let accounts = $state<AccountChoice[]>([]);
  // Who each other account holds, so a linked id reads as a name.
  let known = $state<Record<string, AccountPerson[]>>({});

  async function load() {
    roster = await api<Roster>('/roster');
  }
  onMount(() => {
    void load();
    void api<AccountChoice[]>('/accounts')
      .then(async (found) => {
        accounts = found;
        for (const account of found.filter((a) => !a.primary)) {
          known = { ...known, [account.name]: await api<AccountPerson[]>(`/accounts/${encodeURIComponent(account.name)}/people`).catch(() => []) };
        }
      })
      .catch(() => (accounts = []));
  });

  const people = $derived((roster?.people ?? []).filter((p) => p.name.toLowerCase().includes(query.trim().toLowerCase())));

  function saved(person: Person) {
    if (roster) roster = { ...roster, people: roster.people.map((p) => (p.person_id === person.person_id ? person : p)) };
  }

  // The server sends a stable kind; the sentence is the catalogue's, in the reader's language.
  function flagText(kind: string): string {
    if (kind === 'twin')
      return t('Face recognition merges identical faces, so one of these records holds nearly all the pictures and the other almost none. Neither count means anything on its own. Merge them in Immich or keep them apart.');
    if (kind === 'duplicate')
      return t('One name on two person records: a split face cluster. Merge these records in Immich, the only place it can be fixed.');
    return kind.replaceAll('-', ' ');
  }

  async function keepApart(flag: Flag) {
    const response = await fetch('/api/v1/roster/flags/keep-apart', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ kind: flag.kind, person_ids: flag.person_ids }),
    });
    if (response.ok && roster) roster = { ...roster, flags: roster.flags.filter((f) => f !== flag) };
  }

  async function addPerson() {
    if (!newName.trim()) return;
    await post<Person>('/roster', { name: newName.trim() });
    newName = '';
    await load();
  }

  async function rescan() {
    const { status, body } = await post<JobView>('/roster/scan', {});
    const started = status === 202 ? body : status === 409 ? body.job : null;
    if (!started) return;
    scan = started;
    followJob(started.id, (update) => {
      scan = update;
      if (update.status === 'succeeded') void load();
    });
  }
</script>

<svelte:head><title>{t('People')} · Immich Memories</title></svelte:head>

<div class="flex flex-col gap-6">
  <div class="flex flex-wrap items-end justify-between gap-3">
    <div class="flex flex-col gap-1">
      <a href="/app/settings" class="text-sm text-gray-600 hover:text-primary dark:text-gray-400">{t('Settings')}</a>
      <Heading size="large" tag="h1">{t('People')}</Heading>
      <Text color="muted">{t('The people registry: who is close, their roles, and how they relate.')} <code>people scan</code> {t('writes the guesses; your answers stay across scans.')} <code>people export</code> {t('writes it out as YAML.')}</Text>
    </div>
    <Button size="small" variant="outline" leadingIcon={mdiRefresh} onclick={rescan} disabled={scan?.status === 'running'}>{t('Rescan the library')}</Button>
  </div>

  {#if scan}<JobPanel job={scan} onCancel={async () => scan && (scan = (await post<JobView>(`/jobs/${scan.id}/cancel`, {})).body)} />{/if}

  {#if !roster}
    <LoadingSpinner />
  {:else}
    {#if roster.flags.length}
      <section class="flex flex-col gap-2 rounded-2xl border border-warning p-4" aria-label={t('Curation')}>
        <Heading size="tiny" tag="h2">{t('Curation')}</Heading>
        {#each roster.flags as flag (flag.person_ids.join(':'))}
          <div class="flex flex-col gap-1 text-sm" data-testid="curation-flag">
            <p class="font-medium">
              {#each flag.names as name, index (index)}{#if index}{' · '}{/if}{name}{#if flag.person_urls[index] && /^https?:\/\//i.test(flag.person_urls[index])}
                {' '}<a href={flag.person_urls[index]} target="_blank" rel="noreferrer" class="font-normal text-primary underline" aria-label={t('Open {name} in Immich', { name })}>{t('Open in Immich')}</a>{/if}{/each}
            </p>
            <p>{flagText(flag.kind)}</p>
            <Button size="tiny" variant="outline" class="w-fit" onclick={() => keepApart(flag)}>{t('Keep apart')}</Button>
          </div>
        {/each}
      </section>
    {/if}

    <OwnerSection />

    {#if accounts.length > 1}
      <Text size="small" color="muted">{t('Each Immich account gives the same person its own id. Under a person, pick who they are in the other account. Nothing is matched for you: the same name only comes first in the list.')}</Text>
    {/if}

    <GroupsSection people={roster.people} />

    <div class="flex flex-wrap items-center gap-3">
      <input class="w-64 rounded-lg border border-gray-300 bg-light px-3 py-2 dark:border-gray-700" placeholder={t('Find a name')} aria-label={t('Find a name')} bind:value={query} />
      <form class="flex gap-2" onsubmit={(event) => { event.preventDefault(); void addPerson(); }}>
        <input class="w-56 rounded-lg border border-gray-300 bg-light px-3 py-2 dark:border-gray-700" placeholder={t('Full name')} aria-label={t('Full name')} bind:value={newName} />
        <Button type="submit" size="small" leadingIcon={mdiAccountPlusOutline}>{t('Add someone not in Immich')}</Button>
      </form>
    </div>

    {#if !roster.people.length}
      <div class="flex flex-col items-start gap-2" data-testid="nobody-yet">
        <Text color="muted">{t('Nobody yet. This list is filled the first time a library is prepared, or when you rescan it. The person picker on New memory reads Immich directly, so it can show names before this page does.')}</Text>
        <Button size="small" variant="outline" leadingIcon={mdiRefresh} onclick={rescan} disabled={scan?.status === 'running'}>{t('Rescan now')}</Button>
      </div>
    {/if}

    <ul class="grid gap-4 lg:grid-cols-2">
      {#each people.slice(0, shown) as person (person.person_id)}
        <PersonCard {person} {roster} {accounts} {known} onSaved={saved} />
      {/each}
    </ul>
    {#if people.length > shown}<Button variant="ghost" class="w-fit" onclick={() => (shown += PAGE)}>{t('Show more')}</Button>{/if}
    <datalist id="roles">{#each roster.roles as role (role)}<option value={role}></option>{/each}</datalist>
  {/if}
</div>
