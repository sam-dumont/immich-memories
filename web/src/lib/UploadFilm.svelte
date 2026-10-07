<script lang="ts">
  import { Button } from '@immich/ui';
  import { mdiCloudUploadOutline } from '@mdi/js';
  import { onMount } from 'svelte';
  import { api, post } from '$lib/api';
  import type { components } from '$lib/api-types';
  import { t } from '$lib/i18n.svelte';

  type RenderCapabilities = components['schemas']['RenderCapabilities'];
  type Uploaded = components['schemas']['UploadedFilm'];

  let { runId, filmAvailable }: { runId: string; filmAvailable: boolean } = $props();

  let capability = $state<RenderCapabilities | null>(null);
  let album = $state('');
  let sending = $state(false);
  let problem = $state('');
  let done = $state<Uploaded | null>(null);

  onMount(() => {
    void api<RenderCapabilities>('/render/capabilities')
      .then((found) => (capability = found))
      .catch(() => (capability = { upload_available: false, missing_upload: [], upload_reason: t('Upload availability could not be checked.') }));
  });

  // Only a web link becomes one: the URL is built from a setting.
  const link = $derived(done?.asset_url && /^https?:\/\//i.test(done.asset_url) ? done.asset_url : null);
  const reason = $derived(!filmAvailable ? t('The film file is gone, so there is nothing to upload.') : capability?.upload_available === false ? capability.upload_reason : null);
  const available = $derived(filmAvailable && !!capability?.upload_available);

  async function upload() {
    sending = true;
    problem = '';
    const { status, body } = await post<Uploaded>(`/runs/${encodeURIComponent(runId)}/upload`, { album: album.trim() || null });
    sending = false;
    if (status >= 400) {
      problem = body.detail ?? t('The upload failed.');
      return;
    }
    done = body;
  }
</script>

<div class="flex flex-col items-start gap-2" data-testid="upload-film">
  <form class="flex flex-wrap items-end gap-2" onsubmit={(event) => { event.preventDefault(); void upload(); }}>
    <label class="flex flex-col gap-1 text-xs font-medium">{t('Album name')}
      <input class="rounded-lg border border-gray-300 bg-light px-2 py-1.5 text-sm dark:border-gray-700" bind:value={album} placeholder={t('As configured')} disabled={!available} />
    </label>
    <Button type="submit" size="small" variant="outline" leadingIcon={mdiCloudUploadOutline} disabled={!available || sending} aria-describedby="upload-film-reason">{t('Upload to Immich')}</Button>
  </form>
  {#if reason}<p id="upload-film-reason" class="text-sm text-gray-600 dark:text-gray-400">{reason}</p>{/if}
  {#if problem}<p class="text-sm text-danger" role="alert">{problem}</p>{/if}
  {#if done}
    <p class="text-sm" role="status">
      {done.album ? t('Uploaded to Immich, album {album}.', { album: done.album }) : t('Uploaded to Immich.')}
      {#if link}<a href={link} target="_blank" rel="noreferrer" class="underline">{t('View in Immich')}</a>{:else}<span class="tabular-nums">{done.asset_id}</span>{/if}
    </p>
  {/if}
</div>
