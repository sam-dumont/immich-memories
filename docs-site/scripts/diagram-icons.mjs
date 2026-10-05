import {readFileSync, readdirSync, writeFileSync} from 'node:fs';
import {createRequire} from 'node:module';

// Mermaid architecture diagrams name icons as pack:name. The packs are megabytes of JSON, so
// the site ships only the icons the docs use, bundled: no icon CDN call from a reader's browser.
const root = new URL('../', import.meta.url);
const require = createRequire(root);
const packs = ['logos', 'mdi', 'simple-icons'];
// Architecture services write (pack:name); flowchart icon nodes write icon: "pack:name".
const pattern = new RegExp(`[("](${packs.join('|')}):([a-z0-9-]+)[)"]`, 'g');

const files = (dir) => readdirSync(dir, {withFileTypes: true}).flatMap((entry) => {
  const path = new URL(entry.name + (entry.isDirectory() ? '/' : ''), dir);
  if (entry.isDirectory()) return files(path);
  return /\.mdx?$/.test(entry.name) ? [path] : [];
});
const wanted = new Map(packs.map((pack) => [pack, new Set()]));
for (const file of files(new URL('docs/', root))) {
  for (const [, pack, name] of readFileSync(file, 'utf8').matchAll(pattern)) wanted.get(pack).add(name);
}

const subset = packs.filter((pack) => wanted.get(pack).size).map((pack) => {
  const source = require(`@iconify-json/${pack}/icons.json`);
  const icons = {};
  for (const name of [...wanted.get(pack)].sort()) {
    const alias = source.aliases?.[name];
    const icon = source.icons[name] ?? (alias && {...source.icons[alias.parent], ...alias, parent: undefined});
    if (!icon) throw new Error(`Diagram icon ${pack}:${name} does not exist in @iconify-json/${pack}`);
    icons[name] = icon;
  }
  return {prefix: pack, width: source.width ?? 24, height: source.height ?? 24, icons};
});

const target = new URL('src/theme/Mermaid/diagram-icons.json', root);
const json = `${JSON.stringify(subset, null, 1)}\n`;
const count = subset.reduce((sum, pack) => sum + Object.keys(pack.icons).length, 0);
if (process.argv.includes('--check')) {
  if (readFileSync(target, 'utf8') !== json) throw new Error('Diagram icons are stale; run npm run diagram-icons');
} else writeFileSync(target, json);
console.log(`Diagram icons: ${count} ${process.argv.includes('--check') ? 'verified' : 'bundled'}`);
