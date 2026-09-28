<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { Button, Heading, LoadingSpinner, Modal, ModalBody, ModalFooter, Text } from '@immich/ui';
  import { mdiArrowLeft, mdiEyeOutline, mdiShieldCheckOutline } from '@mdi/js';
  import { api, ApiError, post, thumbnail } from '$lib/api';
  import type { components } from '$lib/api-types';
  import { N_, t } from '$lib/i18n.svelte';

  type Pool = components['schemas']['Pool'];
  type Item = components['schemas']['PoolItem'];
  type Hold = components['schemas']['Hold'];
  type Revision = components['schemas']['Revision'];

  const runId = $derived(page.params.run_id ?? '');
  let items = $state<Item[]>([]);
  let total = $state<number | null>(null);
  let outside = $state(0);
  // This memory's own pictures by default; the rest can still be ticked into the film.
  let showOutside = $state(false);
  let loading = $state(false);
  let missing = $state(false);
  let ticks = $state<Record<string, boolean>>({});
  let clearing = $state<Item | null>(null);
  let level = $state<'anyone' | 'family' | 'just-us'>('family');
  let previewing = $state(false);
  let refusal = $state('');
  let sentinel = $state<HTMLElement>();

  async function more() {
    if (loading || (total !== null && items.length >= total)) return;
    loading = true;
    try {
      const pool = await api<Pool>(`/runs/${encodeURIComponent(runId)}/pool?offset=${items.length}&limit=120&reachable_only=${!showOutside}`);
      items = [...items, ...pool.items];
      total = pool.total;
      if (!showOutside) outside = pool.outside ?? 0;
    } catch (reason) {
      // A run from before cuts recorded their pool has none to show; that is an answer, not a crash.
      if (reason instanceof ApiError && reason.status === 404) {
        missing = true;
        total = 0;
      } else throw reason;
    } finally {
      loading = false;
    }
  }

  function toggleOutside() {
    showOutside = !showOutside;
    items = [];
    total = null;
    void more();
  }

  $effect(() => {
    if (!sentinel) return;
    const observer = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && void more(), { rootMargin: '800px' });
    observer.observe(sentinel);
    return () => observer.disconnect();
  });

  const ticked = (item: Item) => ticks[item.asset_id] ?? item.in_cut;
  const include = $derived(items.filter((item) => !item.in_cut && ticks[item.asset_id] === true).map((i) => i.asset_id));
  const exclude = $derived(items.filter((item) => item.in_cut && ticks[item.asset_id] === false).map((i) => i.asset_id));

  async function decide(item: Item, action: 'never_use' | 'clear' | 'forget') {
    const { body } = await post<Hold>(`/pictures/${encodeURIComponent(item.asset_id)}/decision`, { action, level });
    items = items.map((row) => (row.asset_id === item.asset_id ? { ...row, hold: body } : row));
    if (action === 'never_use' && item.in_cut) ticks = { ...ticks, [item.asset_id]: false };
    clearing = null;
  }

  // The ticks are the owner's last pass over this cut: saved as a revision, never a recut.
  async function preview() {
    previewing = true;
    refusal = '';
    const { status, body } = await post<Revision>(`/runs/${encodeURIComponent(runId)}/revisions`, { added: include, removed: exclude });
    previewing = false;
    if (status !== 201) {
      refusal = body.detail ?? t('The revision could not be saved.');
      return;
    }
    void goto(`/app/runs/${encodeURIComponent(runId)}?revision=${body.number}`);
  }

  const LEVELS: Record<string, string> = { 'just-us': N_('Just us'), family: N_('Family'), anyone: N_('Anyone') };

  const holdLine = (hold: Hold) =>
    hold.decision === 'never_use'
      ? t("You'll never use this picture.")
      : hold.decision?.startsWith('cleared:')
        ? t('You cleared its hold for {level}.', { level: t(LEVELS[hold.decision.slice('cleared:'.length)] ?? 'Family').toLowerCase() })
        : hold.reasons.length
          ? t('Held: {reasons}.', { reasons: hold.reasons.join('; ') })
          : '';
</script>

<svelte:head><title>{t('Pool')} · Immich Memories</title></svelte:head>

<div class="flex flex-col gap-6">
  <div class="flex flex-col gap-2">
    <a href={`/app/runs/${encodeURIComponent(runId)}`} class="flex w-fit items-center gap-1 text-sm text-gray-600 hover:text-primary dark:text-gray-400">
      <svg viewBox="0 0 24 24" class="size-4 fill-current" aria-hidden="true"><path d={mdiArrowLeft} /></svg>{t('Back to the cut')}
    </a>
    <Heading size="large" tag="h1">{t('Pool')}</Heading>
    <Text color="muted">{t('Every picture this cut saw, in the order they were taken. Tick or untick, then preview: your ticks go into the film as they are, with nothing chosen again. Never use and Clear hold last across every run.')}</Text>
  </div>

  {#if outside}
    <label class="flex w-fit items-center gap-2 text-sm">
      <input type="checkbox" checked={showOutside} onchange={toggleOutside} />
      {t('Also show the {count} pictures outside this memory', { count: outside })}
    </label>
  {/if}

  {#if missing}
    <Text color="muted">{t('This run kept no record of its pool. Cut again to see one.')}</Text>
  {:else}
    <ul class="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-x-3 gap-y-5" aria-label={t('Pool')}>
      {#each items as item (item.asset_id)}
        <li class="flex flex-col gap-1.5">
          <label class={['relative block cursor-pointer overflow-hidden rounded-xl bg-gray-100 dark:bg-gray-900', ticked(item) ? 'ring-2 ring-primary' : 'opacity-70']}>
            <img src={thumbnail(item.asset_id)} alt={item.fate} loading="lazy" decoding="async" class="aspect-[4/3] w-full object-contain" />
            <input type="checkbox" class="absolute top-2 left-2 size-5 accent-[var(--color-primary)]" checked={ticked(item)}
              aria-label={t('In the film')} onchange={(event) => (ticks = { ...ticks, [item.asset_id]: event.currentTarget.checked })} />
            {#if item.kind !== 'photo'}<span class="absolute right-1 bottom-1 rounded bg-black/60 px-1.5 text-[11px] text-white">{item.kind === 'video' ? t('Video') : t('Live')}</span>{/if}
          </label>
          <p class="text-[11px] text-gray-600 tabular-nums dark:text-gray-400">{item.taken.slice(0, 10)}{item.favourite ? ' ★' : ''}</p>
          <p class="line-clamp-3 text-xs">{item.fate}</p>
          {#if holdLine(item.hold)}<p class="text-xs text-warning">{holdLine(item.hold)}</p>{/if}
          <div class="flex flex-wrap gap-1">
            {#if item.hold.decision}
              <Button size="tiny" variant="ghost" onclick={() => decide(item, 'forget')}>{t('Undo')}</Button>
            {:else}
              <Button size="tiny" variant="ghost" color="danger" onclick={() => decide(item, 'never_use')}>{t('Never use')}</Button>
              {#if item.hold.can_clear}<Button size="tiny" variant="ghost" onclick={() => (clearing = item)}>{t('Clear hold')}</Button>{/if}
            {/if}
          </div>
        </li>
      {/each}
    </ul>
    <div bind:this={sentinel} class="flex h-12 items-center justify-center">{#if loading}<LoadingSpinner />{/if}</div>

    {#if include.length || exclude.length}
      <div class="sticky bottom-20 z-10 flex flex-wrap items-center gap-3 rounded-2xl border border-gray-200 bg-light/95 p-3 shadow-lg backdrop-blur md:bottom-4 dark:border-gray-800">
        <p class="text-sm">{t('Add: {include} · Take out: {exclude}', { include: include.length, exclude: exclude.length })}</p>
        <Button size="small" class="ml-auto" leadingIcon={mdiEyeOutline} loading={previewing} onclick={preview}>{t('Preview with these choices')}</Button>
        {#if refusal}<p class="w-full text-sm text-danger" role="alert">{refusal}</p>{/if}
      </div>
    {/if}
  {/if}
</div>

{#if clearing}
  <Modal title={t('Clear this hold?')} icon={mdiShieldCheckOutline} onClose={() => (clearing = null)}>
    <ModalBody>
      <div class="flex flex-col gap-3">
        <img src={thumbnail(clearing.asset_id, 'preview')} alt="" class="max-h-80 w-full rounded-lg object-contain" />
        <p class="text-sm">{holdLine(clearing.hold)}</p>
        <label class="flex flex-col gap-1 text-sm font-medium">{t('Films that may use it')}
          <select class="rounded-lg border border-gray-300 bg-light px-3 py-2 dark:border-gray-700" bind:value={level}>
            <option value="just-us">{t('Just us')}</option><option value="family">{t('Family')}</option><option value="anyone">{t('Anyone')}</option>
          </select>
        </label>
      </div>
    </ModalBody>
    <ModalFooter>
      <Button variant="ghost" onclick={() => (clearing = null)}>{t('Cancel')}</Button>
      <Button onclick={() => clearing && decide(clearing, 'clear')}>{t('Clear hold')}</Button>
    </ModalFooter>
  </Modal>
{/if}
