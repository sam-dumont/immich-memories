import assert from 'node:assert/strict';
import {mkdir, readdir, readFile, writeFile} from 'node:fs/promises';
import {dirname, join} from 'node:path';
import {readPageMetadata, renderSocialCard} from './social-preview.mjs';

const base = `https://sam-dumont.github.io/immich-memories/${process.env.DOCS_NEXT === 'true' ? 'next/' : ''}`;
const pages = [];
for (const file of await readdir('build', {recursive: true})) {
  if (!file.endsWith('.html')) continue;
  const metadata = readPageMetadata(await readFile(join('build', file), 'utf8'));
  // Redirect stubs have no page metadata and must keep their destination's preview.
  if (!metadata) continue;
  assert.ok(metadata.image.startsWith(base), `${file}: social image must be bundled locally`);
  const output = join('build', metadata.image.slice(base.length));
  const route = file.replace(/index\.html$/, '');
  // A page's explicit image (including the homepage's photo) is already copied by Docusaurus.
  if (metadata.image.startsWith(`${base}img/social/`)) {
    const mediaUrl = metadata.media && new URL(metadata.media, base).href;
    const mediaPath = mediaUrl?.startsWith(base) ? join('build', decodeURIComponent(mediaUrl.slice(base.length))) : undefined;
    const png = await renderSocialCard({...metadata, mediaPath, route: route === '404.html' ? 'Page not found' : route}, process.cwd());
    await mkdir(dirname(output), {recursive: true});
    await writeFile(output, png);
  }
  pages.push({file, image: metadata.image, title: metadata.title, description: metadata.description});
}
assert.ok(pages.length > 0, 'No social previews generated');
await writeFile('build/social-previews.json', JSON.stringify(pages, null, 2));
console.log(`Prepared ${pages.length} page social previews.`);
