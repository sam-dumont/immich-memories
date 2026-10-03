import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {join} from 'node:path';

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
assert.ok(home.some(tag => tag.property === 'og:image' && tag.content.startsWith(base)), 'Missing local social preview');
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
