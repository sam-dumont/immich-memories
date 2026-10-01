import {readFileSync, writeFileSync} from 'node:fs';

// Share the app's pinned @immich/ui palette without its Svelte/Tailwind runtime.
const root = new URL('../', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');
const version = JSON.parse(read('node_modules/@immich/ui/package.json')).version;
const appVersion = JSON.parse(read('../web/package.json')).devDependencies['@immich/ui'];
if (version !== appVersion) throw new Error(`Immich UI versions differ: docs ${version}, app ${appVersion}`);
const source = read('node_modules/@immich/ui/dist/theme/default.css');
const palette = (selector) => {
  const block = source.match(selector)?.[1];
  if (!block) throw new Error('Immich UI theme structure changed');
  return [...block.matchAll(/(--immich-ui-[\w-]+):\s*([^;]+);/g)]
    .filter(([, , value]) => !value.includes('var('))
    .map(([, name, value]) => `  ${name}: ${value};`).join('\n');
};
const css = `/* Generated from @immich/ui ${version} (MIT). Run npm run ui-theme. */\n:root, [data-theme='light'] {\n${palette(/:root,\s*\.light\s*\{([\s\S]*?)\n\s*\}/)}\n}\n[data-theme='dark'] {\n${palette(/\.dark\s*\{([\s\S]*?)\n\s*\}/)}\n}\n`;
const target = new URL('src/css/immich-ui-tokens.css', root);
if (process.argv.includes('--check')) {
  if (readFileSync(target, 'utf8') !== css) throw new Error('Immich UI tokens are stale; run npm run ui-theme');
} else writeFileSync(target, css);
console.log(`Immich UI ${version}: shared light/dark tokens ${process.argv.includes('--check') ? 'verified' : 'generated'}`);
