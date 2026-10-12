import assert from 'node:assert/strict';
import {existsSync, readdirSync, readFileSync, statSync} from 'node:fs';
import {join} from 'node:path';
import test from 'node:test';
import {renderLlmsTxt, versionLine} from '../plugins/llms-txt.mjs';
import {markdownPath} from '../plugins/markdown-path.mjs';
import {docsTrack, trackPath} from './docs-track.mjs';

const origin = 'https://sam-dumont.github.io';
const routes = new Set(['/immich-memories/next/docs/get-started/quick-start/', '/immich-memories/next/setup/']);

test('site links point into the track being built, as the site serves them', () => {
  const text = renderLlmsTxt(
    '- [Quick start](/docs/get-started/quick-start#basic): install\n- [Builder](/setup)\n- [Repo](https://github.com/x/y)\n',
    origin, '/immich-memories/next/', routes);
  assert.equal(text,
    '- [Quick start](https://sam-dumont.github.io/immich-memories/next/docs/get-started/quick-start/#basic): install\n'
    + '- [Builder](https://sam-dumont.github.io/immich-memories/next/setup/)\n'
    + '- [Repo](https://github.com/x/y)\n');
});

test('docs links go to the Markdown version of the page; other pages stay HTML', () => {
  const text = renderLlmsTxt('- [Quick start](/docs/get-started/quick-start#basic)\n- [Builder](/setup)\n',
    origin, '/immich-memories/next/', routes, {markdownRoutes: new Set(['/immich-memories/next/docs/get-started/quick-start'])});
  assert.equal(text,
    '- [Quick start](https://sam-dumont.github.io/immich-memories/next/docs/get-started/quick-start.md#basic)\n'
    + '- [Builder](https://sam-dumont.github.io/immich-memories/next/setup/)\n');
});

test('a link to a page the build does not have fails the build', () => {
  assert.throws(
    () => renderLlmsTxt('- [Gone](/docs/run/removed)\n', origin, '/immich-memories/next/', routes),
    /llms\.txt links to pages that do not exist: \/docs\/run\/removed/);
});

test('the version line names the track, version and commit, under the summary', () => {
  assert.equal(versionLine({track: 'next', version: 'v1.0.0-rc.10', commit: 'abc123def456', local: false}),
    'Docs track: next (release candidate), version v1.0.0-rc.10, source commit abc123def456.');
  assert.equal(versionLine({track: 'dev', version: 'v1.0.0-rc.9-3-gabc123def456', commit: 'abc123def456', local: false}),
    'Docs track: dev (nightly build of main), version v1.0.0-rc.9-3-gabc123def456, source commit abc123def456.');
  assert.equal(versionLine({track: 'stable', version: 'development', commit: 'abc123def456', local: true}),
    'Docs track: stable, local build, version development, source commit abc123def456.');
  const text = renderLlmsTxt('# Immich Memories\n\n> Summary.\n\nBody.\n', origin, '/immich-memories/', new Set(), {versionLine: 'Docs track: stable.'});
  assert.equal(text, '# Immich Memories\n\n> Summary.\n\nDocs track: stable.\n\nBody.\n');
});

test('a page\'s Markdown lives at its path plus .md', () => {
  assert.equal(markdownPath('/immich-memories/dev/docs/run/nas/'), '/immich-memories/dev/docs/run/nas.md');
  assert.equal(markdownPath('/immich-memories/docs/'), '/immich-memories/docs.md');
});

test('the index sends readers to how it chooses before the optional pages', () => {
  const source = readFileSync('llms.txt', 'utf8');
  const understand = source.indexOf('## Understand the project');
  const install = source.indexOf('## Install');
  assert.ok(understand > 0 && understand < install);
  for (const page of ['/docs/how-it-chooses/overview', '/docs/contribute/architecture', '/docs/run/tested-deployments', '/docs/better/measured']) {
    const at = source.indexOf(`](${page})`);
    assert.ok(at > understand && at < install, page);
  }
  assert.ok(!source.slice(source.indexOf('## Optional')).includes('how-it-chooses'));
  assert.match(source, /exists as Markdown: add `\.md`/);
});

// The built site: these run after `npm run build` (make docs-build does).
const built = existsSync('build/llms.txt');
const base = `/immich-memories/${trackPath(docsTrack())}`;

function pages(dir) {
  return readdirSync(dir).flatMap(name => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? pages(path) : name === 'index.html' ? [path] : [];
  });
}

const isRedirect = page => readFileSync(page, 'utf8').includes('http-equiv="refresh"');

test('the built site publishes llms.txt with only absolute links and a version line', {skip: !built}, () => {
  const text = readFileSync('build/llms.txt', 'utf8');
  assert.match(text, /^# Immich Memories\n\n> .*\n\nDocs track: (stable|next|dev)\b.*, version \S+, source commit [0-9a-f]{7,}\.\n/);
  const links = [...text.matchAll(/\]\(([^)]+)\)/g)].map(([, href]) => href);
  assert.ok(links.length > 20);
  for (const href of links) assert.ok(href.startsWith(`${origin}${base}`) || href.startsWith('https://github.com/'), href);
});

test('every docs link in the built llms.txt resolves to a Markdown page of this build', {skip: !built}, () => {
  const text = readFileSync('build/llms.txt', 'utf8');
  const local = [...text.matchAll(/\]\((https:[^)#]+)/g)].map(([, href]) => href).filter(href => href.startsWith(`${origin}${base}docs/`));
  assert.ok(local.length > 20);
  for (const href of local) {
    assert.ok(href.endsWith('.md'), href);
    assert.ok(existsSync(join('build', href.slice(`${origin}${base}`.length))), href);
  }
});

test('every page names its track\'s llms.txt in its head; docs pages name their Markdown', {skip: !built}, () => {
  const all = pages('build').filter(page => !isRedirect(page));
  assert.ok(all.length > 100);
  for (const page of all) {
    const html = readFileSync(page, 'utf8');
    assert.ok(html.includes(`<link rel="describedby" type="text/plain" href="${base}llms.txt">`), page);
    if (!page.startsWith('build/docs/')) continue;
    const markdown = `${page.slice('build/'.length).replace(/\/index\.html$/, '')}.md`;
    assert.ok(html.includes(`rel="alternate" type="text/markdown" href="${base}${markdown}"`), page);
    assert.ok(existsSync(join('build', markdown)), markdown);
  }
});

test('the footer and the docs landing page link this track\'s llms.txt', {skip: !built}, () => {
  const landing = readFileSync('build/docs/index.html', 'utf8');
  assert.match(landing, new RegExp(`href="${base}llms\\.txt"[^>]*>documentation index \\(llms\\.txt\\)`));
  for (const page of ['build/index.html', 'build/docs/run/nas/index.html']) {
    assert.match(readFileSync(page, 'utf8'), new RegExp(`href="${base}llms\\.txt"[^>]*class="footer__link-item">AI documentation index`), page);
  }
});

test('the built Markdown pages hold no raw components and only absolute links', {skip: !built}, () => {
  const files = pages('build/docs').filter(page => !isRedirect(page)).map(page => `${page.replace(/\/index\.html$/, '')}.md`);
  assert.ok(files.length > 100);
  for (const file of files) {
    const text = readFileSync(file, 'utf8').replace(/```[\s\S]*?```/g, '').replace(/`[^`\n]*`/g, '');
    assert.doesNotMatch(text, /<\/?[A-Z][A-Za-z]*[\s/>]|^import \S+ from ['"]|^:::/m, file);
    for (const [, href] of text.matchAll(/\]\(([^)\s]+)/g)) assert.match(href, /^(https?:|mailto:|#)/, `${file}: ${href}`);
  }
});
