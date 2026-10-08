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
  assert.ok(metadata.image.startsWith(`${base}img/social/`), `${file}: missing page-specific social image`);
  const output = join('build', metadata.image.slice(base.length));
  const route = file.replace(/index\.html$/, '');
  const png = await renderSocialCard({...metadata, route: route === '404.html' ? 'Page not found' : route}, process.cwd());
  await mkdir(dirname(output), {recursive: true});
  await writeFile(output, png);
  pages.push({file, image: metadata.image, title: metadata.title, description: metadata.description});
}
assert.ok(pages.length > 0, 'No social previews generated');
await writeFile('build/social-previews.json', JSON.stringify(pages, null, 2));
console.log(`Generated ${pages.length} page-specific social images.`);
