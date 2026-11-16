<script lang="ts">
  import { Button } from '@immich/ui';
  import { mdiTagOutline } from '@mdi/js';
  import { post } from '#lib/api.ts';
  import type { components } from '#lib/api-types.ts';
  import { t } from '#lib/i18n.svelte.ts';

  type Relabelled = components['schemas']['RelabelAnswer'];

  let { runId }: { runId: string } = $props();

  let sending = $state(false);
  let problem = $state('');
  let done = $state<Relabelled | null>(null);

  async function relabel() {
    sending = true;
    problem = '';
    const { status, body } = await post<Relabelled>(`/runs/${encodeURIComponent(runId)}/label`, {});
    sending = false;
    if (status >= 400) {
      problem = body.detail ?? t('The label could not be updated.');
      return;
    }
    done = body;
  }
</script>

<div class="flex flex-col items-start gap-2" data-testid="relabel-film">
  <Button size="small" variant="outline" leadingIcon={mdiTagOutline} disabled={sending} onclick={() => void relabel()}>{t('Update the Immich label')}</Button>
  {#if problem}<p class="text-sm text-danger" role="alert">{problem}</p>{/if}
  {#if done}
    <p class="text-sm" role="status">{done.status === 'unchanged' ? t('The Immich label was already up to date.') : t('The Immich label was updated.')}</p>
    {#each done.warnings as warning, index (index)}<p class="text-sm text-danger" role="alert">{warning}</p>{/each}
  {/if}
</div>
