<script lang="ts">
  import type { components } from './api-types';
  import { N_, t } from './i18n.svelte';

  let { forecast }: { forecast: components['schemas']['JobForecast'] } = $props();
  const names: Record<string, string> = {
    analysis: N_('Prepare pictures'), selection: N_('Select pictures'), download: N_('Prepare selected clips'),
    assembly: N_('Render film'), music: N_('Music'), check: N_('Check playback'), upload: N_('Upload film'),
  };
  const states: Record<string, string> = {
    pending: N_('Pending'), running: N_('Running'), completed: N_('Completed'), skipped: N_('Skipped'),
  };
  const duration = (seconds: number) => seconds < 60 ? `${Math.ceil(seconds)}s` : `${Math.ceil(seconds / 60)} min`;
  const label = (key: string) => t(names[key] ?? key);
</script>

<div class="space-y-3">
  {#if forecast.remaining_seconds != null}
    <p class="font-medium">{forecast.target === 'film'
      ? t('About {amount} until the film is ready', { amount: duration(forecast.remaining_seconds) })
      : t('About {amount} until the cut is ready', { amount: duration(forecast.remaining_seconds) })}</p>
    <p class="text-sm text-gray-600 dark:text-gray-400">{t('Estimate based on available measurements. It can change as work progresses.')}</p>
  {:else}
    <p class="font-medium">{forecast.known_remaining_seconds > 0
      ? t('About {amount} of estimated work left', { amount: duration(forecast.known_remaining_seconds) })
      : t('Overall time remaining is not known yet.')}</p>
    <p class="text-sm text-gray-600 dark:text-gray-400">{t('Additional time not estimated: {phases}.', { phases: forecast.unknown_phases.map(label).join(', ') })}
    </p>
  {/if}
  <ol aria-label={t('Phases')} class="divide-y divide-gray-200 rounded-lg border border-gray-200 px-3 dark:divide-gray-800 dark:border-gray-800">
    {#each forecast.phases as phase}
      <li class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 py-2 text-sm" aria-current={phase.state === 'running' ? 'step' : undefined}>
        <span class:font-semibold={phase.state === 'running'}>{label(phase.key)}</span>
        <span class="text-gray-600 tabular-nums dark:text-gray-400">
          <span>{t(states[phase.state])}</span>
          {#if phase.elapsed_seconds > 0} · {t('{amount} elapsed', { amount: duration(phase.elapsed_seconds) })}{/if}
          {#if phase.state === 'running' || phase.state === 'pending'}
            · {#if phase.remaining_seconds != null}
              {t('~{amount} left', { amount: duration(phase.remaining_seconds) })}
            {:else if (phase.known_remaining_seconds ?? 0) > 0}
              {t('~{amount} estimated, plus unmeasured work', { amount: duration(phase.known_remaining_seconds!) })}
            {:else}{t('Time not known yet')}{/if}
          {/if}
        </span>
      </li>
    {/each}
  </ol>
  {#if forecast.revision > 0}
    <p class="text-sm text-gray-600 dark:text-gray-400">{t('The remaining work changed. The estimate has been revised.')}</p>
  {/if}
</div>
