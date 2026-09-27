<script lang="ts">
  import { Badge, Button, Heading } from '@immich/ui';
  import { mdiArrowULeftTop, mdiContentCut, mdiDeleteOutline, mdiSwapHorizontal } from '@mdi/js';
  import { thumbnail, video, type CutShot } from './api';
  import type { CutEditor } from './cut-edits.svelte';
  import { t } from './i18n.svelte';
  import { clock, seatLabel } from './labels';

  let { shot, modelPolish, editor }: { shot: CutShot; modelPolish: boolean; editor: CutEditor } = $props();

  let player = $state<HTMLVideoElement>();
  let comparing = $state<string | null>(null);
  const compared = $derived(shot.alternatives.find((alternative) => alternative.asset_id === comparing));
  const playing = $derived(editor.playing(shot));
  const swapped = $derived(playing !== shot.asset_id);
  const interval = $derived(swapped ? null : editor.interval(shot));
  const removed = $derived(editor.isRemoved(shot));

  function mark(edge: 0 | 1) {
    if (!player || !interval) return;
    const next: [number, number] = [...interval];
    next[edge] = player.currentTime;
    if (next[1] > next[0]) editor.trim(shot, next);
  }

  // The preview plays the stretch the film plays, and loops it: the rest of the clip is not the cut.
  function hold() {
    if (!player || !interval) return;
    if (player.currentTime < interval[0] || player.currentTime >= interval[1]) player.currentTime = interval[0];
  }
</script>

<article class="flex flex-col gap-5" aria-label={t('Picture review')}>
  <div class="overflow-hidden rounded-2xl bg-gray-100 dark:bg-gray-900">
    {#if shot.motion && interval}
      {#key shot.asset_id}
        <video bind:this={player} class="aspect-[4/3] w-full object-contain" controls muted playsinline autoplay
          preload="metadata" poster={thumbnail(shot.asset_id, 'preview')}
          src={`${video(shot.asset_id)}#t=${interval[0]},${interval[1]}`}
          ontimeupdate={hold} onloadedmetadata={hold}></video>
      {/key}
    {:else}
      <img class={['aspect-[4/3] w-full object-contain', removed && 'opacity-40']} src={thumbnail(playing, 'preview')} alt={shot.reason || shot.story_title} />
    {/if}
  </div>

  <section class="flex flex-col gap-2" aria-label={t('Edit this shot')}>
    <div class="flex flex-wrap gap-2">
      <Button size="small" variant="outline" color={removed ? 'primary' : 'danger'} leadingIcon={removed ? mdiArrowULeftTop : mdiDeleteOutline}
        onclick={() => editor.toggleRemoved(shot)}>{removed ? t('Put it back') : t('Remove from this cut')}</Button>
      {#if swapped}
        <Button size="small" variant="outline" leadingIcon={mdiArrowULeftTop} onclick={() => editor.swap(shot, null)}>{t('Keep the original')}</Button>
      {/if}
    </div>
    {#if !removed && interval && shot.motion && !swapped}
      <div class="flex flex-wrap items-center gap-2 text-sm tabular-nums">
        <Button size="small" variant="ghost" leadingIcon={mdiContentCut} onclick={() => mark(0)}>{t('Start here')}</Button>
        <Button size="small" variant="ghost" leadingIcon={mdiContentCut} onclick={() => mark(1)}>{t('End here')}</Button>
        <span>{interval[0].toFixed(1)}–{interval[1].toFixed(1)} s</span>
      </div>
    {:else if !removed && !shot.motion}
      <label class="flex items-center gap-2 text-sm">{t('Screen time (seconds)')}
        <input type="number" min="0.5" step="0.5" value={editor.seconds(shot).toFixed(1)}
          class="w-20 rounded-md border border-gray-300 bg-light px-2 py-1 tabular-nums dark:border-gray-700"
          onchange={(event) => { const value = Number(event.currentTarget.value); if (value > 0) editor.hold(shot, value); }} />
      </label>
    {/if}
  </section>

  <div class="flex flex-col gap-1">
    <p class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-gray-600 tabular-nums dark:text-gray-400">
      <span class="font-semibold text-dark">#{shot.position}</span>
      <span>{clock(shot.start)}</span>
      <span>{shot.day}</span>
      <span>{t('{seconds} s on screen', { seconds: shot.seconds.toFixed(1) })}</span>
      <Badge size="tiny" color={shot.motion ? 'info' : 'secondary'}>{shot.motion ? t('Video') : t('Still')}</Badge>
    </p>
    <Heading size="small" tag="h2">{shot.story_title}</Heading>
  </div>

  <section class="flex flex-col gap-1">
    <h3 class="text-xs font-semibold tracking-wide text-gray-600 uppercase dark:text-gray-400">{t('Why this picture')}</h3>
    <p>{shot.reason || t('No reason recorded for this picture.')}</p>
  </section>

  {#if shot.selection}
    <section class="flex flex-col gap-1">
      <h3 class="text-xs font-semibold tracking-wide text-gray-600 uppercase dark:text-gray-400">{t('How the rules got here')}</h3>
      <ul class="flex flex-col gap-1 text-sm">
        {#if shot.selection.passed.length}<li>{t('Passed {stages}', { stages: shot.selection.passed.join(', ') })}</li>{/if}
        {#if shot.selection.kept_at}<li>{t('Kept at {stage}', { stage: shot.selection.kept_at })}</li>{/if}
        {#if shot.selection.facts}<li class="text-gray-600 dark:text-gray-400">{shot.selection.facts}</li>{/if}
      </ul>
    </section>
  {/if}

  {#if shot.alternatives.length}
    <section class="flex flex-col gap-2">
      <h3 class="text-xs font-semibold tracking-wide text-gray-600 uppercase dark:text-gray-400">{t('Other pictures of this moment')}</h3>
      <p class="text-xs text-gray-600 dark:text-gray-400">{t('Eligible when this shot was chosen. Open one to compare.')}</p>
      <ul class="flex gap-2 overflow-x-auto pb-1" aria-label={t('Other pictures of this moment')}>
        {#each shot.alternatives as alternative (alternative.asset_id)}
          <li class="shrink-0">
            <button type="button" aria-pressed={comparing === alternative.asset_id}
              onclick={() => (comparing = comparing === alternative.asset_id ? null : alternative.asset_id)}
              class={['block rounded-lg outline-offset-2 focus-visible:outline-2 focus-visible:outline-primary', comparing === alternative.asset_id && 'ring-2 ring-primary']}>
              <img class="h-20 w-24 rounded-lg bg-gray-100 object-contain dark:bg-gray-900" src={thumbnail(alternative.asset_id)} alt={alternative.facts || t('Other picture of this moment')} loading="lazy" />
            </button>
          </li>
        {/each}
      </ul>
      {#if compared}
        <div class="grid grid-cols-2 gap-2">
          <figure class="flex flex-col gap-1">
            <img class="aspect-[4/3] w-full rounded-lg bg-gray-100 object-contain dark:bg-gray-900" src={thumbnail(shot.asset_id, 'preview')} alt={shot.reason || shot.story_title} />
            <figcaption class="text-xs font-medium">{t('In the cut')}</figcaption>
          </figure>
          <figure class="flex flex-col gap-1">
            <img class="aspect-[4/3] w-full rounded-lg bg-gray-100 object-contain dark:bg-gray-900" src={thumbnail(compared.asset_id, 'preview')} alt={compared.facts || t('Other picture of this moment')} />
            <figcaption class="text-xs"><span class="font-medium">{compared.facts}</span> {compared.fate}</figcaption>
          </figure>
        </div>
        {#if playing !== compared.asset_id}
          <Button size="small" variant="outline" leadingIcon={mdiSwapHorizontal} class="w-fit" onclick={() => editor.swap(shot, compared.asset_id)}>{t('Use this picture instead')}</Button>
        {/if}
      {/if}
      <a class="w-fit text-sm text-primary hover:underline" href="/step2">{t('Browse the whole pool')}</a>
    </section>
  {/if}

  <section class="flex flex-col gap-2">
    <h3 class="text-xs font-semibold tracking-wide text-gray-600 uppercase dark:text-gray-400">{t('Model polish')}</h3>
    {#if !modelPolish}
      <p class="text-sm text-gray-600 dark:text-gray-400">{t('No model read this cut: the rules chose every picture.')}</p>
    {:else if !shot.model}
      <p class="text-sm text-gray-600 dark:text-gray-400">{t('The model had nothing to say about this picture.')}</p>
    {:else}
      {#if shot.model.seat}<p>{seatLabel(shot.model.seat)}</p>{/if}
      {#if shot.model.replaced_asset_id}
        <img class="h-28 w-fit rounded-lg object-contain" src={thumbnail(shot.model.replaced_asset_id)} alt={t('The picture it replaced')} loading="lazy" />
      {/if}
      {#if shot.model.model_reason}
        <p class="text-sm"><span class="font-medium">{shot.model.replaced_asset_id ? t('Why the model replaced the other picture') : t('Model suggestion')}:</span> {shot.model.model_reason}</p>
      {/if}
      {#if shot.model.kept_reason}
        <p class="text-sm"><span class="font-medium">{t('Kept because')}:</span> {shot.model.kept_reason}</p>
      {/if}
      {#if shot.model.proposed_asset_id}
        <div class="flex items-center gap-3">
          <img class="h-20 w-fit rounded-lg object-contain" src={thumbnail(shot.model.proposed_asset_id)} alt={t('Recorded alternative')} title={t('Considered by the model')} loading="lazy" />
          <p class="text-sm">{shot.model.replacement_outcome || t('No outcome recorded.')}</p>
        </div>
      {/if}
      {#if shot.model.offered_count > 0}
        <p class="text-sm text-gray-600 dark:text-gray-400">{t('Alternatives considered')}: {shot.model.offered_count}</p>
      {/if}
    {/if}
  </section>
</article>
