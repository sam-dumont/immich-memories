<script lang="ts">
  import { Button, Heading } from '@immich/ui';
  import { mdiMusicNote, mdiUpload } from '@mdi/js';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { api, post, type JobView } from './api';
  import type { components } from './api-types';
  import { t } from './i18n.svelte';
  import { followJob } from './job.svelte';
  import JobPanel from './JobPanel.svelte';

  type Revision = components['schemas']['Revision'];

  let { runId, revisions, current = null }: { runId: string; revisions: Revision[]; current?: number | null } = $props();

  let from = $state<number | null>(null);
  // The revision just saved or opened is the one the owner means to render.
  $effect(() => {
    if (current != null) from = current;
  });
  let title = $state('');
  let subtitle = $state('');
  let transition = $state('');
  let orientation = $state('');
  let resolution = $state('');
  let format = $state('');
  let quality = $state('');
  let scaleMode = $state('');
  // On unless the owner unticks them: a film reads better with its dates and places (owner, 28 Sep).
  let addDate = $state(true);
  let addPlace = $state(true);
  let privacy = $state(false);
  let naming = $state<'' | 'model' | 'rules'>('');
  let music = $state<string>('auto');
  let volume = $state(0.5);
  let upload = $state(false);
  let album = $state('');

  let job = $state<JobView | null>(null);
  let preview = $state<JobView | null>(null);
  let uploaded = $state<{ id: string; name: string } | null>(null);
  let problem = $state('');

  const previewTrack = $derived((preview?.meta?.music_id as string | undefined) ?? null);
  const field = 'rounded-lg border border-gray-300 bg-light px-3 py-2 dark:border-gray-700';
  const label = 'flex flex-col gap-1 text-sm font-medium';
  const orNull = (value: string) => value || null;

  // A reload mid-render comes back to the job still running for this cut, not to an empty form.
  onMount(() => {
    void api<JobView | null>('/jobs/active').then((running) => {
      if (!running || running.meta?.run_id !== runId) return;
      if (running.kind === 'render') follow(running, (update) => (job = update));
      if (running.kind === 'music') follow(running, (update) => (preview = update));
    });
    return () => streams.forEach((stop) => stop());
  });

  const streams: (() => void)[] = [];

  function follow(started: JobView, onUpdate: (update: JobView) => void) {
    onUpdate(started);
    streams.push(followJob(started.id, onUpdate));
  }

  async function render() {
    problem = '';
    const { status, body } = await post<JobView>(`/runs/${encodeURIComponent(runId)}/renders`, {
      revision: from,
      title: orNull(title),
      subtitle: orNull(subtitle),
      transition: orNull(transition),
      orientation: orNull(orientation),
      resolution: orNull(resolution),
      format: orNull(format),
      quality: orNull(quality),
      scale_mode: orNull(scaleMode),
      add_date: addDate,
      add_place: addPlace,
      privacy_mode: privacy,
      llm_title: naming === '' ? null : naming === 'model',
      music,
      music_volume: music === 'none' ? null : volume,
      upload_to_immich: upload,
      album: upload ? orNull(album) : null,
    });
    const started = status === 202 ? body : status === 409 ? body.job : null;
    if (!started) {
      problem = body.detail ?? t('The render could not start.');
      return;
    }
    follow(started, (update) => (job = update));
  }

  async function makePreview() {
    const { status, body } = await post<JobView>(`/runs/${encodeURIComponent(runId)}/music-preview`, {});
    const started = status === 202 ? body : status === 409 ? body.job : null;
    if (!started) return;
    follow(started, (update) => (preview = update));
  }

  async function sendFile(event: Event) {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (!file) return;
    const body = new FormData();
    body.append('file', file);
    const response = await fetch('/api/v1/music', { method: 'POST', body });
    const answer = await response.json();
    if (!response.ok) {
      problem = answer.detail ? t(answer.detail) : t('That file is not an MP3, M4A or WAV');
      return;
    }
    uploaded = answer;
    music = answer.id;
  }

  async function cancel(target: JobView) {
    const stopped = (await post<JobView>(`/jobs/${encodeURIComponent(target.id)}/cancel`, {})).body;
    if (job?.id === stopped.id) job = stopped;
    if (preview?.id === stopped.id) preview = stopped;
  }
</script>

<section class="flex flex-col gap-4 border-t border-gray-200 pt-6 dark:border-gray-800" aria-label={t('Render')}>
  <Heading size="tiny" tag="h2">{t('Render')}</Heading>
  {#if job}
    <JobPanel {job} onCancel={() => job && cancel(job)} />
    {#if job.status === 'succeeded' && job.result_run_id}
      <!-- svelte-ignore a11y_media_has_caption -->
      <video class="w-full max-w-3xl rounded-2xl bg-black" controls preload="metadata" src={`/api/v1/runs/${encodeURIComponent(job.result_run_id)}/film`}></video>
      <a class="w-fit text-sm text-primary hover:underline" href={`/app/runs/${encodeURIComponent(job.result_run_id)}`}>{t('Open the film run')}</a>
    {/if}
  {/if}
  {#if !job || job.status !== 'running'}
    <form class="grid max-w-3xl gap-4 sm:grid-cols-2" onsubmit={(event) => { event.preventDefault(); void render(); }}>
      <label class={label}>{t('What to render')}
        <select class={field} bind:value={from}>
          <option value={null}>{t('The cut as chosen')}</option>
          {#each revisions as revision (revision.number)}<option value={revision.number}>{t('Revision {number}', { number: revision.number })}</option>{/each}
        </select>
      </label>
      <label class={label}>{t('Transition Style')}
        <select class={field} bind:value={transition}>
          <option value="">{t('As configured')}</option><option value="smart">{t('Smart (fades and cuts)')}</option>
          <option value="crossfade">{t('Crossfade')}</option><option value="cut">{t('Cut')}</option><option value="none">{t('None')}</option>
        </select>
      </label>
      <label class={label}>{t('Title (decided as generate decides when empty)')}<input class={field} bind:value={title} /></label>
      <label class={label}>{t('Subtitle')}<input class={field} bind:value={subtitle} /></label>
      {#if !title}
        <label class={label}>{t('Who names the film')}
          <select class={field} bind:value={naming}>
            <option value="">{t('As generate decides')}</option>
            <option value="model">{t('The model, when one is configured')}</option>
            <option value="rules">{t('The dates and places, never a model')}</option>
          </select>
        </label>
      {/if}
      <label class={label}>{t('Orientation')}
        <select class={field} bind:value={orientation}>
          <option value="">{t('Automatic')}</option><option value="landscape">{t('Landscape')}</option>
          <option value="portrait">{t('Portrait')}</option><option value="square">{t('Square')}</option>
        </select>
      </label>
      <label class={label}>{t('Resolution')}
        <select class={field} bind:value={resolution}>
          <option value="">{t('As configured')}</option><option value="auto">{t('Match the sources')}</option>
          <option value="4k">4K</option><option value="1080p">1080p</option><option value="720p">720p</option>
        </select>
      </label>
      <label class={label}>{t('Format')}
        <select class={field} bind:value={format}>
          <option value="">{t('As configured')}</option><option value="mp4">MP4 (H.264)</option>
          <option value="h265">MP4 (H.265)</option><option value="prores">MOV (ProRes)</option>
        </select>
      </label>
      <label class={label}>{t('Quality')}
        <select class={field} bind:value={quality}>
          <option value="">{t('As configured')}</option><option value="high">{t('High')}</option>
          <option value="medium">{t('Medium')}</option><option value="low">{t('Low')}</option>
        </select>
      </label>
      <label class={label}>{t('Scaling Mode')}
        <select class={field} bind:value={scaleMode}>
          <option value="">{t('As configured')}</option><option value="blur">{t('Blurred background')}</option><option value="fit">{t('Fit with bars')}</option>
        </select>
      </label>
      <div class="flex flex-col gap-2 text-sm">
        <label class="flex items-center gap-2"><input type="checkbox" bind:checked={addDate} />{t('Add date overlay')}</label>
        <label class="flex items-center gap-2"><input type="checkbox" bind:checked={addPlace} />{t('Caption clips with their place')}</label>
        {#if addPlace}
          <p class="-mt-1 ml-6 text-xs text-gray-600 dark:text-gray-400">
            {t("The place is Immich's. With geocoding on (Settings, network), it names the district in the film's language, through the public Nominatim or network.geocoding_url.")}
          </p>
        {/if}
        <label class="flex items-center gap-2"><input type="checkbox" bind:checked={privacy} />{t('Privacy mode: blur every picture and scramble names')}</label>
      </div>

      <fieldset class="flex flex-col gap-3 sm:col-span-2">
        <legend class="mb-1 text-sm font-semibold">{t('Music')}</legend>
        <div class="flex flex-wrap gap-2 text-sm">
          <label class="flex items-center gap-2"><input type="radio" bind:group={music} value="auto" />{t('Automatic (as configured)')}</label>
          <label class="flex items-center gap-2"><input type="radio" bind:group={music} value="none" />{t('No music')}</label>
          {#if previewTrack}<label class="flex items-center gap-2"><input type="radio" bind:group={music} value={previewTrack} />{t('The previewed track')}</label>{/if}
          {#if uploaded}<label class="flex items-center gap-2"><input type="radio" bind:group={music} value={uploaded.id} />{uploaded.name}</label>{/if}
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <!-- A preview is generated; with no generator configured there is nothing to ask. -->
          {#if page.data.session?.music_preview_offered}
            <Button size="small" variant="outline" leadingIcon={mdiMusicNote} disabled={preview?.status === 'running'} onclick={makePreview}>{t('Preview a track')}</Button>
          {/if}
          <label class="relative inline-flex cursor-pointer items-center gap-2 rounded-lg border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-700">
            <svg viewBox="0 0 24 24" class="size-4 fill-current" aria-hidden="true"><path d={mdiUpload} /></svg>{t('Upload a track')}
            <input type="file" accept=".mp3,.m4a,.wav,audio/*" class="sr-only" onchange={sendFile} />
          </label>
        </div>
        {#if preview}
          {#if preview.status === 'running'}<JobPanel job={preview} onCancel={() => preview && cancel(preview)} />{/if}
          {#if previewTrack}<audio controls src={`/api/v1/music/${previewTrack}`} class="w-full max-w-md"></audio>{/if}
          {#if preview.status !== 'running' && !previewTrack}<JobPanel job={preview} onCancel={() => {}} />{/if}
        {/if}
        {#if music !== 'none'}
          <label class="flex items-center gap-3 text-sm">{t('Music volume:')}
            <input type="range" min="0" max="1" step="0.05" bind:value={volume} class="w-48" /><span class="tabular-nums">{Math.round(volume * 100)}%</span>
          </label>
        {/if}
      </fieldset>

      <div class="flex flex-col gap-2 sm:col-span-2">
        <label class="flex items-center gap-2 text-sm"><input type="checkbox" bind:checked={upload} />{t('Upload the film to Immich')}</label>
        {#if upload}<label class={label}>{t('Album name')}<input class={field} bind:value={album} placeholder={t('As configured')} /></label>{/if}
      </div>
      {#if problem}<p class="text-sm text-danger sm:col-span-2" role="alert">{problem}</p>{/if}
      <Button type="submit" class="w-fit">{t('Render')}</Button>
    </form>
  {/if}
</section>
