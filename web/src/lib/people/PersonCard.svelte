<script lang="ts">
  import { type AccountChoice } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import AccountLinks from './AccountLinks.svelte';
  import RelationshipRows from './RelationshipRows.svelte';
  import { savePerson } from './rosterApi';
  import type { AccountPerson, Person, Roster } from './types';

  let { person, roster, accounts, known, onSaved }: { person: Person; roster: Roster; accounts: AccountChoice[]; known: Record<string, AccountPerson[]>; onSaved: (saved: Person) => void } = $props();

  async function save(changes: Partial<Person>) {
    const saved = await savePerson(person, changes);
    if (saved) onSaved(saved);
  }
</script>

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
        onchange={(event) => save({ role: event.currentTarget.value || null })} />
    </label>
    <label class="flex flex-col gap-1 text-xs font-medium">{t('Notes')}
      <input class="rounded-lg border border-gray-300 bg-light px-2 py-1.5 text-sm dark:border-gray-700" value={person.notes ?? ''}
        onchange={(event) => save({ notes: event.currentTarget.value || null })} />
    </label>
  </div>
  <RelationshipRows {person} {roster} {onSaved} />
  {#if accounts.length > 1}<AccountLinks {person} {accounts} {known} {onSaved} />{/if}
</li>
