import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import sharp from 'sharp';
import {readPageMetadata} from './social-preview.mjs';

const next = process.env.DOCS_NEXT === 'true';
const base = `https://sam-dumont.github.io/immich-memories/${next ? 'next/' : ''}`;
const build = 'build';

function attributes(tag) {
  return Object.fromEntries([...tag.matchAll(/([\w:-]+)="([^"]*)"/g)].map(([, name, value]) => [name, value]));
}

function checkPage(url) {
  const relative = url.slice(base.length);
  const html = readFileSync(join(build, relative, 'index.html'), 'utf8');
  const tags = [...html.matchAll(/<(?:meta|link)\s[^>]*>/g)].map(([tag]) => attributes(tag));
  const canonical = tags.filter(tag => tag.rel === 'canonical');
  assert.equal(canonical.length, 1, `${url}: needs one canonical URL`);
  assert.equal(canonical[0].href, url, `${url}: canonical must match the public address`);
  const description = tags.find(tag => tag.name === 'description')?.content;
  assert.ok(description?.trim(), `${url}: missing search description`);
  const noindex = tags.some(tag => tag.name === 'robots' && /noindex/i.test(tag.content));
  assert.equal(noindex, next, `${url}: wrong indexing policy`);
  const version = tags.find(tag => tag.name === 'application-version')?.content;
  assert.ok(version, `${url}: missing build version`);
  if (process.env.DOCS_VERSION) assert.equal(version, process.env.DOCS_VERSION, `${url}: wrong build version`);
  assert.ok(html.includes(`Docs ${version}`), `${url}: build version missing from navigation`);
  return tags;
}

const home = checkPage(base);
assert.ok(home.some(tag => tag.property === 'og:image' && tag.content === `${base}img/social-card.jpg`), 'Homepage must keep its photographic preview');
if (process.env.GOOGLE_SITE_VERIFICATION) {
  assert.ok(home.some(tag => tag.name === 'google-site-verification' && tag.content === process.env.GOOGLE_SITE_VERIFICATION), 'Missing Search Console verification');
}

if (next) {
  assert.ok(!existsSync(join(build, 'sitemap.xml')), 'Candidate docs must not advertise a duplicate sitemap');
  checkPage(`${base}docs/get-started/quick-start/`);
  console.log('Candidate docs: noindex, canonical URLs, and verification checked.');
} else {
  const sitemap = readFileSync(join(build, 'sitemap.xml'), 'utf8');
  const urls = [...sitemap.matchAll(/<loc>(.*?)<\/loc>/g)].map(([, url]) => url);
  assert.ok(urls.includes(base), 'Homepage missing from sitemap');
  assert.ok(urls.includes(`${base}docs/get-started/quick-start/`), 'Quick start missing from sitemap');
  for (const url of urls) {
    assert.ok(url.startsWith(base) && !url.startsWith(`${base}next/`), `Wrong sitemap address: ${url}`);
    checkPage(url);
  }
  console.log(`Search checks passed for ${urls.length} sitemap pages.`);
}

// Check actual generated files: a distinct URL alone can still serve a shared card.
const previews = JSON.parse(readFileSync(join(build, 'social-previews.json'), 'utf8'));
const hashes = new Set();
for (const preview of previews) {
  const html = readFileSync(join(build, preview.file), 'utf8');
  const metadata = readPageMetadata(html);
  assert.equal(metadata.image, preview.image, `${preview.file}: social image drifted`);
  assert.ok(metadata.title.trim(), `${preview.file}: missing social title`);
  const tags = [...html.matchAll(/<meta\s[^>]*>/g)].map(([tag]) => attributes(tag));
  assert.equal(tags.filter(tag => tag.property === 'og:image').length, 1, `${preview.file}: duplicate Open Graph image`);
  assert.equal(tags.find(tag => tag.name === 'twitter:image')?.content, preview.image, `${preview.file}: Twitter image differs`);
  assert.ok(preview.image.startsWith(base), `${preview.file}: wrong image base`);
  const png = readFileSync(join(build, preview.image.slice(base.length)));
  const image = await sharp(png).metadata();
  assert.ok(['png', 'jpeg'].includes(image.format));
  assert.equal(tags.find(tag => tag.property === 'og:image:type')?.content, `image/${image.format}`);
  assert.equal(image.width, 1200);
  assert.equal(image.height, 630);
  const hash = createHash('sha256').update(png).digest('hex');
  if (preview.image.startsWith(`${base}img/social/`)) {
    assert.ok(!hashes.has(hash), `${preview.file}: duplicates another generated card`);
  }
  hashes.add(hash);
}
assert.ok(previews.some(page => page.file === 'index.html'), 'Homepage social preview missing');
assert.ok(previews.some(page => page.file === 'docs/run/tested-deployments/index.html'), 'Deployment social preview missing');
console.log(`Social previews checked for ${previews.length} pages.`);
