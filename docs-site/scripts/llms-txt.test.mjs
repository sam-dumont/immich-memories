import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import test from 'node:test';
import {renderLlmsTxt} from '../plugins/llms-txt.mjs';
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

test('a link to a page the build does not have fails the build', () => {
  assert.throws(
    () => renderLlmsTxt('- [Gone](/docs/run/removed)\n', origin, '/immich-memories/next/', routes),
    /llms\.txt links to pages that do not exist: \/docs\/run\/removed/);
});

test('the built site publishes llms.txt with only absolute links', {skip: !existsSync('build/llms.txt')}, () => {
  const text = readFileSync('build/llms.txt', 'utf8');
  assert.match(text, /^# Immich Memories\n\n> /);
  const links = [...text.matchAll(/\]\(([^)]+)\)/g)].map(([, href]) => href);
  assert.ok(links.length > 20);
  const base = `${origin}/immich-memories/${trackPath(docsTrack())}`;
  for (const href of links) assert.ok(href.startsWith(base) || href.startsWith('https://github.com/'), href);
});
