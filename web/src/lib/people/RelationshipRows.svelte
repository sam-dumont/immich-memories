<script lang="ts">
  import { Button } from '@immich/ui';
  import { mdiClose } from '@mdi/js';
  import { t } from '$lib/i18n.svelte';
  import { personPath, savePerson, sendPerson } from './rosterApi';
  import type { Link, Person, Roster } from './types';

  let { person, roster, onSaved }: { person: Person; roster: Roster; onSaved: (saved: Person) => void } = $props();

  let kind = $state('');
  let target = $state('');

  const label = (value: string) => roster.relationships.find((c) => c.kind === value)?.label ?? value.replaceAll('-', ' ');

  async function relate(withId: string, relation: string) {
    const saved = await sendPerson('POST', personPath(person, '/relationships'), { kind: relation, target_id: withId });
    if (saved) onSaved(saved);
  }

  async function remove(link: Link) {
    const saved = await sendPerson('DELETE', personPath(person, '/relationships'), { kind: link.kind, target_id: link.target_id });
    if (saved) onSaved(saved);
  }

  // Pressing the answer already given takes it back: undecided is a real state.
  async function reject(link: Link) {
    const saved = await savePerson(person, {}, [{ kind: link.kind, target_id: link.target_id, decision: link.decision === 'rejected' ? null : 'rejected' }]);
    if (saved) onSaved(saved);
  }
</script>

<div class="flex flex-col gap-1" data-testid="relationships">
  <p class="text-xs font-medium">{t('Relationships')}</p>
  {#each person.links as link (`${link.kind}:${link.target_id}`)}
    <div class="flex flex-wrap items-center gap-2 text-sm" data-testid="relationship-row" data-status={link.status}>
      {#if link.status === 'named'}
        <span>{label(link.kind)} <span class="font-medium">{link.target_name}</span></span>
        <Button size="tiny" variant="ghost" onclick={() => remove(link)}>{t('Remove this relationship')}</Button>
      {:else if link.status === 'rejected'}
        <span class="text-gray-600 dark:text-gray-400">{t('Not related to')} <span class="font-medium">{link.target_name}</span></span>
        <button type="button" aria-label={t('No, they are not')} aria-pressed="true" onclick={() => reject(link)} class="rounded-full bg-danger/20 p-1 text-danger"><svg viewBox="0 0 24 24" class="size-4 fill-current"><path d={mdiClose} /></svg></button>
      {:else}
        <span>
          {link.status === 'unnamed' ? t('Linked to') : t('Looks linked to')} <span class="font-medium">{link.target_name}</span>
        </span>
        {#if link.status === 'unnamed'}
          <span class="text-xs text-gray-600 dark:text-gray-400">({t('relationship not named')})</span>
        {:else}
          <span class="text-xs text-gray-600 dark:text-gray-400">({link.via}, {Math.round(link.confidence * 100)}%)</span>
        {/if}
        <span class="inline-flex items-center gap-1">
          <select class="rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm dark:border-gray-700" aria-label={t('What is {name} to {other}?', { name: person.name, other: link.target_name })}
            onchange={(event) => event.currentTarget.value && relate(link.target_id, event.currentTarget.value)}>
            <option value="">{t('What is {name} to {other}?', { name: person.name, other: link.target_name })}</option>
            {#each roster.relationships as choice (choice.kind)}<option value={choice.kind}>{choice.label}</option>{/each}
          </select>
          <button type="button" aria-label={t('No, they are not')} aria-pressed="false" onclick={() => reject(link)} class="rounded-full p-1 text-gray-500"><svg viewBox="0 0 24 24" class="size-4 fill-current"><path d={mdiClose} /></svg></button>
        </span>
      {/if}
    </div>
  {:else}
    <p class="text-xs text-gray-600 dark:text-gray-400">{t('Nothing recorded yet.')}</p>
  {/each}
  <form class="mt-1 flex flex-wrap gap-2" onsubmit={(event) => { event.preventDefault(); if (kind && target) void relate(target, kind); }}>
    <select class="rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm dark:border-gray-700" aria-label={t('Relationship')} bind:value={kind}>
      <option value="">{t('Add a relationship')}</option>
      {#each roster.relationships as choice (choice.kind)}<option value={choice.kind}>{choice.label}</option>{/each}
    </select>
    <select class="rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm dark:border-gray-700" aria-label={t('With')} bind:value={target}>
      <option value="">{t('With')}</option>
      {#each roster.people.filter((p) => p.person_id !== person.person_id) as other (other.person_id)}<option value={other.person_id}>{other.name}</option>{/each}
    </select>
    <Button type="submit" size="tiny" variant="outline">{t('Add')}</Button>
  </form>
</div>
