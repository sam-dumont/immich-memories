<script lang="ts">
  import { Button, Heading, Text } from '@immich/ui';
  import { api, post, type SavedGroup } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import { onMount } from 'svelte';
  import type { Person } from './types';

  let { people }: { people: Person[] } = $props();

  let groups = $state<SavedGroup[]>([]);
  let label = $state('');
  let chosen = $state<string[]>([]);
  let how = $state<'OR' | 'AND'>('OR');
  let advanced = $state(false);
  let typed = $state('');
  let problem = $state('');

  const load = async () => (groups = await api<SavedGroup[]>('/roster/groups'));
  onMount(() => void load());

  // A saved expression speaks person ids; the page shows the names they stand for.
  const names = $derived(new Map(people.flatMap((p) => Object.values(p.aliases).flat().map((id) => [id, p.name] as const)).concat(people.map((p) => [p.person_id, p.name] as const))));
  const readable = (expression: string) => expression.replace(/"([^"]+)"/g, (whole, id: string) => names.get(id) ?? whole);

  const built = $derived(chosen.map((id) => `"${id}"`).join(` ${how} `));

  async function add() {
    const expression = advanced ? typed.trim() : built;
    if (!label.trim() || !expression) return;
    problem = '';
    const { status, body } = await post<SavedGroup>('/roster/groups', { label: label.trim(), expression });
    if (status >= 400) {
      problem = (body as { detail?: string }).detail ?? t('That expression could not be saved.');
      return;
    }
    label = '';
    typed = '';
    chosen = [];
    await load();
  }

  async function remove(name: string) {
    await fetch(`/api/v1/roster/groups/${encodeURIComponent(name)}`, { method: 'DELETE' });
    await load();
  }
</script>

<section class="flex flex-col gap-2 rounded-2xl border border-gray-200 p-4 dark:border-gray-800" aria-label={t('Saved groups')}>
  <Heading size="tiny" tag="h2">{t('Saved groups')}</Heading>
  <Text size="small" color="muted">{t('A label for a people condition. Pick it on the New memory page, or with generate --group.')}</Text>
  {#if groups.length}
    <ul class="flex flex-col gap-1">
      {#each groups as group (group.label)}
        <li class="flex flex-wrap items-center gap-2 text-sm">
          <span class="font-medium">{group.label}</span>
          <span class="text-gray-600 dark:text-gray-400">{readable(group.expression)}</span>
          <Button size="tiny" variant="ghost" onclick={() => remove(group.label)}>{t('Remove')}</Button>
        </li>
      {/each}
    </ul>
  {:else}
    <Text size="small" color="muted">{t('No saved groups yet.')}</Text>
  {/if}
  <form class="mt-1 flex flex-col gap-2" onsubmit={(event) => { event.preventDefault(); void add(); }}>
    <input class="w-48 rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm dark:border-gray-700" placeholder={t('Label')} aria-label={t('Label')} bind:value={label} />
    {#if advanced}
      <input class="w-full max-w-lg rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm dark:border-gray-700" placeholder={'("id-a" OR "id-b") AND "id-c"'} aria-label={t('Expression')} bind:value={typed} />
    {:else}
      <div class="flex flex-wrap items-start gap-3">
        <select multiple size="5" class="min-w-48 rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm dark:border-gray-700" aria-label={t('Pick the people')} bind:value={chosen}>
          {#each people as person (person.person_id)}<option value={person.person_id}>{person.name}</option>{/each}
        </select>
        <fieldset class="flex flex-col gap-1 text-sm">
          <label class="flex items-center gap-1"><input type="radio" bind:group={how} value="OR" />{t('Any of them')}</label>
          <label class="flex items-center gap-1"><input type="radio" bind:group={how} value="AND" />{t('All of them')}</label>
        </fieldset>
      </div>
    {/if}
    <div class="flex flex-wrap items-center gap-2">
      <Button type="submit" size="tiny" variant="outline">{t('Save group')}</Button>
      <label class="flex items-center gap-1 text-xs"><input type="checkbox" bind:checked={advanced} />{t('Advanced: type the expression')}</label>
    </div>
  </form>
  {#if problem}<p class="text-xs text-danger" role="alert">{problem}</p>{/if}
</section>
