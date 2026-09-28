<script lang="ts">
  import { Button, Heading, LoadingSpinner, Text } from '@immich/ui';
  import { mdiAccountPlusOutline, mdiCheck, mdiClose, mdiRefresh } from '@mdi/js';
  import { onMount } from 'svelte';
  import { api, post, type JobView } from '$lib/api';
  import type { components } from '$lib/api-types';
  import { t } from '$lib/i18n.svelte';
  import { followJob } from '$lib/job.svelte';
  import JobPanel from '$lib/JobPanel.svelte';

  type Roster = components['schemas']['Roster'];
  type Person = components['schemas']['RosterPerson'];
  type Link = components['schemas']['RosterLink'];

  const PAGE = 30;
  let roster = $state<Roster | null>(null);
  let query = $state('');
  let shown = $state(PAGE);
  let newName = $state('');
  let scan = $state<JobView | null>(null);
  let adding = $state<Record<string, { kind: string; target: string }>>({});

  async function load() {
    roster = await api<Roster>('/roster');
  }
  onMount(() => void load());

  const people = $derived((roster?.people ?? []).filter((p) => p.name.toLowerCase().includes(query.trim().toLowerCase())));

  async function send(person: Person, method: string, path: string, body: unknown) {
    const response = await fetch(`/api/v1/roster${path}`, {
      method,
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok || !roster) return;
    const saved = (await response.json()) as Person;
    roster = { ...roster, people: roster.people.map((p) => (p.person_id === saved.person_id ? saved : p)) };
  }

  const save = (person: Person, changes: Partial<Person> = {}, links: { kind: string; target_id: string; decision: string | null }[] = []) =>
    send(person, 'PUT', `/${encodeURIComponent(person.person_id)}`, {
      // A change of null clears the field, so `??` would not do: it would keep the old value.
      role: 'role' in changes ? changes.role : (person.role ?? null),
      notes: 'notes' in changes ? changes.notes : (person.notes ?? null),
      links,
    });

  // Pressing the answer already given takes it back: undecided is a real state.
  const answer = (person: Person, link: Link, decision: 'confirmed' | 'rejected') =>
    save(person, {}, [{ kind: link.kind, target_id: link.target_id, decision: link.decision === decision ? null : decision }]);

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

  const label = (kind: string) => roster?.relationships.find((c) => c.kind === kind)?.label ?? kind.replaceAll('-', ' ');
</script>

<svelte:head><title>{t('People')} · Immich Memories</title></svelte:head>

<div class="flex flex-col gap-6">
  <div class="flex flex-wrap items-end justify-between gap-3">
    <div class="flex flex-col gap-1">
      <a href="/app/settings" class="text-sm text-gray-600 hover:text-primary dark:text-gray-400">{t('Settings')}</a>
      <Heading size="large" tag="h1">{t('People')}</Heading>
      <Text color="muted">{t('The people registry: who is close, their roles, and how they relate. `people scan` writes the guesses; your answers stay across scans. `people export` writes it out as YAML.')}</Text>
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
        {#each roster.flags as flag, index (index)}<p class="text-sm">{flag.message}</p>{/each}
      </section>
    {/if}

    <div class="flex flex-wrap items-center gap-3">
      <input class="w-64 rounded-lg border border-gray-300 bg-light px-3 py-2 dark:border-gray-700" placeholder={t('Find a name')} aria-label={t('Find a name')} bind:value={query} />
      <form class="flex gap-2" onsubmit={(event) => { event.preventDefault(); void addPerson(); }}>
        <input class="w-56 rounded-lg border border-gray-300 bg-light px-3 py-2 dark:border-gray-700" placeholder={t('Full name')} aria-label={t('Full name')} bind:value={newName} />
        <Button type="submit" size="small" leadingIcon={mdiAccountPlusOutline}>{t('Add someone not in Immich')}</Button>
      </form>
    </div>

    {#if !roster.people.length}
      <Text color="muted">{t('Nobody yet. Rescan the library to read who is in it.')}</Text>
    {/if}

    <ul class="grid gap-4 lg:grid-cols-2">
      {#each people.slice(0, shown) as person (person.person_id)}
        <li class="flex flex-col gap-3 rounded-2xl border border-gray-200 p-4 dark:border-gray-800">
          <div class="flex items-center gap-3">
            <img src={`/api/v1/people/${encodeURIComponent(person.person_id)}/face`} alt="" class="size-14 rounded-full bg-gray-100 object-cover dark:bg-gray-900" loading="lazy"
              onerror={(event) => ((event.currentTarget as HTMLImageElement).style.visibility = 'hidden')} />
            <div class="min-w-0">
              <p class="truncate font-semibold">{person.name}</p>
              <p class="text-xs text-gray-600 dark:text-gray-400">{person.tier.replaceAll('_', ' ')} · {t('Pictures: {count}', { count: person.count })}{person.birth_date ? ` · ${person.birth_date}` : ''}</p>
            </div>
          </div>
          {#if person.evidence}<p class="text-xs text-gray-600 dark:text-gray-400">{person.evidence}</p>{/if}
          <div class="grid gap-2 sm:grid-cols-2">
            <label class="flex flex-col gap-1 text-xs font-medium">{t('Role (suggestions; type your own)')}
              <input class="rounded-lg border border-gray-300 bg-light px-2 py-1.5 text-sm dark:border-gray-700" list="roles" value={person.role ?? ''}
                onchange={(event) => save(person, { role: event.currentTarget.value || null })} />
            </label>
            <label class="flex flex-col gap-1 text-xs font-medium">{t('Notes')}
              <input class="rounded-lg border border-gray-300 bg-light px-2 py-1.5 text-sm dark:border-gray-700" value={person.notes ?? ''}
                onchange={(event) => save(person, { notes: event.currentTarget.value || null })} />
            </label>
          </div>
          <div class="flex flex-col gap-1">
            <p class="text-xs font-medium">{t('Relationships')}</p>
            {#each person.links as link (`${link.kind}:${link.target_id}`)}
              <div class="flex flex-wrap items-center gap-2 text-sm">
                <span>{label(link.kind)} <span class="font-medium">{link.target_name}</span></span>
                {#if link.inferred}
                  <span class="text-xs text-gray-600 dark:text-gray-400">({link.via}, {Math.round(link.confidence * 100)}%)</span>
                  <button type="button" aria-label={t('Yes, that is right')} aria-pressed={link.decision === 'confirmed'} onclick={() => answer(person, link, 'confirmed')}
                    class={['rounded-full p-1', link.decision === 'confirmed' ? 'bg-success/20 text-success' : 'text-gray-500']}><svg viewBox="0 0 24 24" class="size-4 fill-current"><path d={mdiCheck} /></svg></button>
                  <button type="button" aria-label={t('No, they are not')} aria-pressed={link.decision === 'rejected'} onclick={() => answer(person, link, 'rejected')}
                    class={['rounded-full p-1', link.decision === 'rejected' ? 'bg-danger/20 text-danger' : 'text-gray-500']}><svg viewBox="0 0 24 24" class="size-4 fill-current"><path d={mdiClose} /></svg></button>
                {:else}
                  <Button size="tiny" variant="ghost" onclick={() => send(person, 'DELETE', `/${encodeURIComponent(person.person_id)}/relationships`, { kind: link.kind, target_id: link.target_id })}>{t('Remove this relationship')}</Button>
                {/if}
              </div>
            {:else}
              <p class="text-xs text-gray-600 dark:text-gray-400">{t('Nothing recorded yet.')}</p>
            {/each}
            <form class="mt-1 flex flex-wrap gap-2" onsubmit={(event) => {
              event.preventDefault();
              const choice = adding[person.person_id];
              if (choice?.kind && choice.target) void send(person, 'POST', `/${encodeURIComponent(person.person_id)}/relationships`, { kind: choice.kind, target_id: choice.target });
            }}>
              <select class="rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm dark:border-gray-700" aria-label={t('Relationship')}
                onchange={(event) => (adding = { ...adding, [person.person_id]: { kind: event.currentTarget.value, target: adding[person.person_id]?.target ?? '' } })}>
                <option value="">{t('Add a relationship')}</option>
                {#each roster.relationships as choice (choice.kind)}<option value={choice.kind}>{choice.label}</option>{/each}
              </select>
              <select class="rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm dark:border-gray-700" aria-label={t('With')}
                onchange={(event) => (adding = { ...adding, [person.person_id]: { kind: adding[person.person_id]?.kind ?? '', target: event.currentTarget.value } })}>
                <option value="">{t('With')}</option>
                {#each roster.people.filter((p) => p.person_id !== person.person_id) as other (other.person_id)}<option value={other.person_id}>{other.name}</option>{/each}
              </select>
              <Button type="submit" size="tiny" variant="outline">{t('Add')}</Button>
            </form>
          </div>
        </li>
      {/each}
    </ul>
    {#if people.length > shown}<Button variant="ghost" class="w-fit" onclick={() => (shown += PAGE)}>{t('Show more')}</Button>{/if}
    <datalist id="roles">{#each roster.roles as role (role)}<option value={role}></option>{/each}</datalist>
  {/if}
</div>
