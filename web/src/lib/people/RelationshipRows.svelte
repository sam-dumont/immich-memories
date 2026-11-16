<script lang="ts">
  import { Button } from '@immich/ui';
  import { mdiCheck, mdiClose } from '@mdi/js';
  import { t } from '#lib/i18n.svelte.ts';
  import { chainStatement, kindLabel, kindStatement, viaLabel } from './relationshipLabels';
  import { personPath, savePerson, sendPerson } from './rosterApi';
  import type { Link, Person, Roster } from './types';

  let { person, roster, onSaved }: { person: Person; roster: Roster; onSaved: (saved: Person) => void } = $props();

  let kind = $state('');
  let target = $state('');

  const statement = (link: Link) => kindStatement(link.kind, person.name, link.target_name);

  async function relate(withId: string, relation: string) {
    const saved = await sendPerson('POST', personPath(person, '/relationships'), { kind: relation, target_id: withId });
    if (saved) onSaved(saved);
  }

  async function remove(link: Link) {
    const saved = await sendPerson('DELETE', personPath(person, '/relationships'), { kind: link.kind, target_id: link.target_id });
    if (saved) onSaved(saved);
  }

  // The family tree's suggestions (#2795), all recorded at once with their reciprocals.
  async function acceptAll() {
    const saved = await sendPerson('POST', personPath(person, '/suggestions/accept'), {});
    if (saved) onSaved(saved);
  }

  const suggested = $derived(person.links.filter((link) => link.status === 'suggested').length);
  // A detected pair said no to is "not related"; a named kind said no to is just that kind.
  const detected = new Set(['tight-dyad', 'twin', 'duplicate']);

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
        <span>{statement(link)}</span>
        <Button size="tiny" variant="ghost" onclick={() => remove(link)}>{t('Remove this relationship')}</Button>
      {:else if link.status === 'suggested'}
        <span><span class="text-xs text-gray-600 dark:text-gray-400">{t('Suggested')}:</span> {statement(link)}</span>
        <span class="text-xs text-gray-600 dark:text-gray-400" data-testid="suggestion-reason">({link.chain.length ? chainStatement(link.chain) : viaLabel(link.via)})</span>
        <span class="inline-flex items-center gap-1">
          <button type="button" aria-label={t('Confirm: {statement}', { statement: statement(link) })} onclick={() => relate(link.target_id, link.kind)} class="rounded-full p-1 text-gray-500 hover:text-primary"><svg viewBox="0 0 24 24" class="size-4 fill-current"><path d={mdiCheck} /></svg></button>
          <button type="button" aria-label={t('No, they are not')} aria-pressed="false" onclick={() => reject(link)} class="rounded-full p-1 text-gray-500"><svg viewBox="0 0 24 24" class="size-4 fill-current"><path d={mdiClose} /></svg></button>
        </span>
      {:else if link.status === 'rejected'}
        <span class="text-gray-600 dark:text-gray-400">{#if detected.has(link.kind)}{t('Not related to')} <span class="font-medium">{link.target_name}</span>{:else}{t('Ruled out: {statement}', { statement: statement(link) })}{/if}</span>
        <button type="button" aria-label={t('No, they are not')} aria-pressed="true" onclick={() => reject(link)} class="rounded-full bg-danger/20 p-1 text-danger"><svg viewBox="0 0 24 24" class="size-4 fill-current"><path d={mdiClose} /></svg></button>
      {:else}
        <span>
          {link.status === 'unnamed' ? t('Linked to') : t('Looks linked to')} <span class="font-medium">{link.target_name}</span>
        </span>
        {#if link.status === 'unnamed'}
          <span class="text-xs text-gray-600 dark:text-gray-400">({t('relationship not named')})</span>
        {:else}
          <span class="text-xs text-gray-600 dark:text-gray-400">({viaLabel(link.via)}, {Math.round(link.confidence * 100)}%)</span>
        {/if}
        <span class="inline-flex items-center gap-1">
          <select class="rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm dark:border-gray-700" aria-label={t('What is {name} to {other}?', { name: person.name, other: link.target_name })}
            onchange={(event) => event.currentTarget.value && relate(link.target_id, event.currentTarget.value)}>
            <option value="">{t('What is {name} to {other}?', { name: person.name, other: link.target_name })}</option>
            {#each roster.relationships as choice (choice.kind)}<option value={choice.kind}>{kindLabel(choice.kind)}</option>{/each}
          </select>
          <button type="button" aria-label={t('No, they are not')} aria-pressed="false" onclick={() => reject(link)} class="rounded-full p-1 text-gray-500"><svg viewBox="0 0 24 24" class="size-4 fill-current"><path d={mdiClose} /></svg></button>
        </span>
      {/if}
    </div>
  {:else}
    <p class="text-xs text-gray-600 dark:text-gray-400">{t('Nothing recorded yet.')}</p>
  {/each}
  {#if suggested}<Button size="tiny" variant="outline" class="w-fit" onclick={acceptAll}>{t('Accept all suggestions')}</Button>{/if}
  <form class="mt-1 flex flex-wrap gap-2" onsubmit={(event) => { event.preventDefault(); if (kind && target) void relate(target, kind); }}>
    <select class="rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm dark:border-gray-700" aria-label={t('Relationship')} bind:value={kind}>
      <option value="">{t('Add a relationship')}</option>
      {#each roster.relationships as choice (choice.kind)}<option value={choice.kind}>{kindLabel(choice.kind)}</option>{/each}
    </select>
    <select class="rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm dark:border-gray-700" aria-label={t('With')} bind:value={target}>
      <option value="">{t('With')}</option>
      {#each roster.people.filter((p) => p.person_id !== person.person_id) as other (other.person_id)}<option value={other.person_id}>{other.name}</option>{/each}
    </select>
    <Button type="submit" size="tiny" variant="outline">{t('Add')}</Button>
  </form>
</div>
