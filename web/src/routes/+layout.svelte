<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import { AppShell, AppShellHeader, AppShellSidebar, NavbarItem, ThemeSwitcher, TooltipProvider } from '@immich/ui';
  import { mdiCogOutline, mdiHistory, mdiImageMultipleOutline, mdiLightbulbOutline, mdiMovieOpenStarOutline } from '@mdi/js';
  import { t } from '$lib/i18n.svelte';

  let { children } = $props();

  // Pages not yet moved to this client open the server pages; each slice of #1395 moves one.
  const navigation = $derived([
    { title: t('Memory'), href: '/', icon: mdiMovieOpenStarOutline },
    { title: t('Suggestions'), href: '/suggestions', icon: mdiLightbulbOutline },
    { title: t('Runs'), href: '/app/runs', icon: mdiHistory },
    { title: t('Media pool'), href: '/step2', icon: mdiImageMultipleOutline },
    { title: t('Settings'), href: '/settings/config', icon: mdiCogOutline },
  ]);
</script>

<TooltipProvider>
<AppShell>
  <AppShellHeader>
    <header class="flex h-16 w-full items-center justify-between px-4">
      <a href="/" class="flex items-center gap-2 text-lg font-semibold text-primary">
        <svg viewBox="0 0 24 24" class="size-7 fill-current" aria-hidden="true"><path d={mdiMovieOpenStarOutline} /></svg>
        Immich Memories
      </a>
      <ThemeSwitcher />
    </header>
  </AppShellHeader>
  <AppShellSidebar>
    <nav class="flex w-64 flex-col gap-1 p-3 max-md:hidden" aria-label={t('Main navigation')}>
      {#each navigation as item (item.href)}
        <NavbarItem {...item} active={page.url.pathname.startsWith(item.href) && item.href !== '/'} />
      {/each}
    </nav>
  </AppShellSidebar>
  <main class="mx-auto w-full max-w-7xl px-4 pt-6 pb-24 md:px-8 md:pb-6">
    {@render children()}
  </main>
</AppShell>

<nav class="fixed inset-x-0 bottom-0 z-10 flex justify-around border-t border-gray-200 bg-light/95 dark:border-gray-800 py-1 backdrop-blur md:hidden" aria-label={t('Main navigation')}>
  {#each navigation as item (item.href)}
    <a href={item.href} class={['flex min-w-0 flex-1 flex-col items-center gap-0.5 rounded-lg py-1 text-[11px]', page.url.pathname.startsWith(item.href) && item.href !== '/' ? 'text-primary' : 'text-gray-600 dark:text-gray-400']}>
      <svg viewBox="0 0 24 24" class="size-6 fill-current" aria-hidden="true"><path d={item.icon} /></svg>
      <span class="w-full truncate text-center">{item.title}</span>
    </a>
  {/each}
</nav>
</TooltipProvider>
