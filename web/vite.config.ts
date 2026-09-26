import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, type Plugin } from 'vite';

// @immich/ui's index imports its logos and store badges, and Vite emits every imported asset
// even when nothing uses it. They are Immich's trademarks, outside the package's MIT grant, so
// they resolve to nothing and never reach the bundle (`make web-check` verifies).
const BRAND_ASSET = /@immich\/ui\/dist\/assets\/(immich-logo|appstore-badge|fdroid-badge|playstore-badge|obtainium-badge)/;
const withoutImmichBrand = (): Plugin => ({
  name: 'without-immich-brand',
  enforce: 'pre',
  async resolveId(source, importer, options) {
    const resolved = await this.resolve(source, importer, { ...options, skipSelf: true });
    return resolved && BRAND_ASSET.test(resolved.id) ? '\0immich-brand-asset' : null;
  },
  load: (id) => (id === '\0immich-brand-asset' ? 'export default "";' : null),
});

// `npm run dev` proxies the API to a running `immich-memories ui` on :8080.
export default defineConfig({
  plugins: [withoutImmichBrand(), tailwindcss(), sveltekit()],
  server: { proxy: { '/api': 'http://127.0.0.1:8080' } },
  // MIT and Apache-2.0 ask for their notices to travel with the bundled code.
  build: { license: { fileName: 'licenses.md' } },
});
