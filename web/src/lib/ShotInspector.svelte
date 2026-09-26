<script lang="ts">
  import { Badge, Heading } from '@immich/ui';
  import { thumbnail, video, type CutShot } from './api';
  import { t } from './i18n.svelte';
  import { clock, seatLabel } from './labels';

  let { shot, modelPolish }: { shot: CutShot; modelPolish: boolean } = $props();

  let player = $state<HTMLVideoElement>();
  const interval = $derived(shot.source_interval);

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
      <img class="aspect-[4/3] w-full object-contain" src={thumbnail(shot.asset_id, 'preview')} alt={shot.reason || shot.story_title} />
    {/if}
  </div>

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
          <img class="h-20 w-fit rounded-lg object-contain" src={thumbnail(shot.model.proposed_asset_id)} alt={t('Recorded alternative')} loading="lazy" />
          <p class="text-sm">{shot.model.replacement_outcome || t('No outcome recorded.')}</p>
        </div>
      {/if}
      {#if shot.model.offered_count > 0}
        <p class="text-sm text-gray-600 dark:text-gray-400">{t('Alternatives considered')}: {shot.model.offered_count}</p>
      {/if}
    {/if}
  </section>
</article>
