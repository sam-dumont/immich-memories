import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// A static client served by Python under /app: no Node process at runtime.
export default {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      pages: '../src/immich_memories/web/client',
      assets: '../src/immich_memories/web/client',
      fallback: 'index.html',
      strict: true,
    }),
    paths: { base: '/app', relative: false },
    version: { name: 'immich-memories' },
  },
};
