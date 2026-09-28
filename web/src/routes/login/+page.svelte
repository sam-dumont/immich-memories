<script lang="ts">
  import { goto } from '$app/navigation';
  import { Button, Heading, Text } from '@immich/ui';
  import { mdiMovieOpenStarOutline } from '@mdi/js';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { components } from '$lib/api-types';
  import { t } from '$lib/i18n.svelte';

  type Session = components['schemas']['SessionView'];

  let session = $state<Session | null>(null);
  let username = $state('');
  let password = $state('');
  let problem = $state('');
  let busy = $state(false);

  onMount(async () => {
    session = await api<Session>('/session');
    if (session.signed_in) await goto('/app/create', { replaceState: true });
    else if (session.auto_launch) window.location.assign('/auth/authorize');
  });

  async function signIn() {
    busy = true;
    problem = '';
    const response = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    busy = false;
    if (response.ok) {
      // The layout read the session before sign-in; it must read it again to show who is in.
      await goto('/app/create', { replaceState: true, invalidateAll: true });
      return;
    }
    const body = await response.json().catch(() => ({}));
    problem = t(body.detail ?? 'Invalid username or password');
  }
</script>

<svelte:head><title>{t('Sign in')} · Immich Memories</title></svelte:head>

<div class="flex min-h-[70vh] items-center justify-center">
  <div class="flex w-full max-w-sm flex-col gap-6">
    <div class="flex flex-col items-center gap-2 text-center">
      <svg viewBox="0 0 24 24" class="size-12 fill-current text-primary" aria-hidden="true"><path d={mdiMovieOpenStarOutline} /></svg>
      <Heading size="large" tag="h1">Immich Memories</Heading>
      <Text color="muted">{t('Turn your photo library into video memories')}</Text>
    </div>
    {#if session?.provider === 'oidc'}
      <div class="flex flex-col gap-2">
        <Button href="/auth/authorize" class="w-full">{session.button_text ?? t('Sign in')}</Button>
        <Text size="small" color="muted" class="text-center">{t('You will be redirected to your identity provider')}</Text>
      </div>
    {:else if session?.provider === 'basic'}
      <form class="flex flex-col gap-3" onsubmit={(event) => { event.preventDefault(); void signIn(); }}>
        <label class="flex flex-col gap-1 text-sm font-medium">{t('Username')}
          <input class="rounded-lg border border-gray-300 bg-light px-3 py-2 dark:border-gray-700" autocomplete="username" bind:value={username} required />
        </label>
        <label class="flex flex-col gap-1 text-sm font-medium">{t('Password')}
          <input class="rounded-lg border border-gray-300 bg-light px-3 py-2 dark:border-gray-700" type="password" autocomplete="current-password" bind:value={password} required />
        </label>
        {#if problem}<p class="text-sm text-danger" role="alert">{problem}</p>{/if}
        <Button type="submit" class="w-full" loading={busy}>{t('Sign in')}</Button>
      </form>
    {:else if session?.provider === 'header'}
      <Text color="muted" class="text-center">{t('Sign in through the proxy in front of this server.')}</Text>
    {/if}
  </div>
</div>
