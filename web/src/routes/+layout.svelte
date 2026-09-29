<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import { AppShell, AppShellHeader, AppShellSidebar, NavbarItem, ThemeSwitcher, TooltipProvider } from '@immich/ui';
  import { mdiCogOutline, mdiHistory, mdiLightbulbOutline, mdiMovieOpenStarOutline } from '@mdi/js';
  import { chooseLanguage, chosenLanguage, languages, t } from '$lib/i18n.svelte';
  import { demoMode } from '$lib/demo-mode.svelte';
  import { mdiEyeOffOutline, mdiEyeOutline } from '@mdi/js';

  let { children, data } = $props();
  const bare = $derived(page.url.pathname.startsWith('/app/login'));

  // WHY an effect: a class directive on <svelte:body> is not applied in Svelte 5.
  $effect(() => {
    // `server.enable_demo_mode` offers the switch; without it nothing is ever blurred.
    document.body.classList.toggle('demo-mode', !!data.session?.demo_mode_offered && demoMode.on);
  });

  // Pages not yet moved to this client open the server pages; each slice of #1395 moves one.
  const navigation = $derived([
    { title: t('Memory'), href: '/app/create', icon: mdiMovieOpenStarOutline },
    { title: t('Suggestions'), href: '/app/suggestions', icon: mdiLightbulbOutline },
    { title: t('Runs'), href: '/app/runs', icon: mdiHistory },
    { title: t('Settings'), href: '/app/settings', icon: mdiCogOutline },
  ]);
</script>

<TooltipProvider>
{#if bare}
  <main class="mx-auto w-full max-w-7xl px-4 py-6">{@render children()}</main>
{:else}
<AppShell>
  <AppShellHeader>
    <header class="flex h-16 w-full items-center justify-between gap-2 px-4">
      <!-- A phone keeps the icon: the wordmark, the language and the theme toggle do not fit 390 px. -->
      <a href="/" class="flex shrink-0 items-center gap-2 text-lg font-semibold text-primary" aria-label="Immich Memories">
        <svg viewBox="0 0 24 24" class="size-7 fill-current" aria-hidden="true"><path d={mdiMovieOpenStarOutline} /></svg>
        <span class="max-sm:hidden">Immich Memories</span>
      </a>
      <div class="flex min-w-0 items-center gap-2">
        <select class="min-w-0 max-w-40 rounded-lg border border-gray-300 bg-light px-2 py-1 text-sm sm:max-w-none dark:border-gray-700" aria-label={t('Interface language')}
          value={chosenLanguage()} onchange={(event) => chooseLanguage(event.currentTarget.value)}>
          <option value="auto">{t('Automatic (browser)')}</option>
          {#each languages() as language (language.code)}<option value={language.code}>{language.name}</option>{/each}
        </select>
{#if data.session?.demo_mode_offered}
        <button type="button" class="rounded-full p-2 text-primary hover:bg-primary/10" aria-pressed={demoMode.on} aria-label={t('Demo mode')}
          title={t('Demo mode')} onclick={() => demoMode.toggle()}>
          <svg viewBox="0 0 24 24" class="size-5 fill-current" aria-hidden="true"><path d={demoMode.on ? mdiEyeOffOutline : mdiEyeOutline} /></svg>
        </button>
        {/if}
        <ThemeSwitcher />
        {#if data.session?.auth_enabled && data.session?.signed_in}
          {#if data.session.username}<span class="text-sm font-medium max-sm:hidden">{data.session.username}</span>{/if}
          <a href="/logout" class="rounded-lg px-2 py-1 text-sm text-gray-600 hover:text-primary dark:text-gray-400">{t('Sign out')}</a>
        {/if}
      </div>
    </header>
  </AppShellHeader>
  <!-- Below md the shell draws its sidebar as an overlay, open by default: on a phone it covered
       the page and took every click. Phones navigate from the bar at the bottom instead. -->
  <AppShellSidebar class="max-md:hidden">
    <nav class="flex w-64 flex-col gap-1 p-3" aria-label={t('Main navigation')}>
      {#each navigation as item (item.href)}
        <NavbarItem {...item} active={page.url.pathname.startsWith(item.href)} />
      {/each}
    </nav>
  </AppShellSidebar>
  <main class="mx-auto w-full max-w-7xl px-4 pt-6 pb-24 md:px-8 md:pb-6">
    {@render children()}
  </main>
</AppShell>

<nav class="fixed inset-x-0 bottom-0 z-10 flex justify-around border-t border-gray-200 bg-light/95 dark:border-gray-800 py-1 backdrop-blur md:hidden" aria-label={t('Main navigation')}>
  {#each navigation as item (item.href)}
    <a href={item.href} class={['flex min-w-0 flex-1 flex-col items-center gap-0.5 rounded-lg py-1 text-[11px]', page.url.pathname.startsWith(item.href) ? 'text-primary' : 'text-gray-600 dark:text-gray-400']}>
      <svg viewBox="0 0 24 24" class="size-6 fill-current" aria-hidden="true"><path d={item.icon} /></svg>
      <span class="w-full truncate text-center">{item.title}</span>
    </a>
  {/each}
</nav>
{/if}
</TooltipProvider>
