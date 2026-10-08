import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import sharp from 'sharp';
import {socialPreviewPath} from '../src/social-preview';
import {readPageMetadata, renderSocialCard} from './social-preview.mjs';

const siteDir = process.cwd();

test('release and candidate routes each point to their own local card', () => {
  assert.equal(socialPreviewPath('/immich-memories/', '/immich-memories/'), 'img/social/index.png');
  assert.equal(socialPreviewPath('/immich-memories/docs/run/docker/', '/immich-memories/'), 'img/social/docs/run/docker.png');
  assert.equal(socialPreviewPath('/immich-memories/next/docs/run/docker/', '/immich-memories/next/'), 'img/social/docs/run/docker.png');
  assert.throws(() => socialPreviewPath('/elsewhere/', '/immich-memories/'));
});

test('page content keeps punctuation and Unicode, without interpreting markup', () => {
  const metadata = readPageMetadata(`<head>
    <meta property="og:title" content="Titles &amp; music | Immich Memories">
    <meta name="description" content="Read &quot;été&quot;, &#39;music&#39;, and &lt;sample&gt;.">
    <meta property="og:image" content="https://example.test/img/social/music.png">
    </head>`);
  assert.equal(metadata.title, 'Titles & music');
  assert.equal(metadata.description, `Read "été", 'music', and <sample>.`);
  assert.equal(readPageMetadata('<meta http-equiv="refresh" content="0; url=/docs/">'), null);
});

test('different topics produce complete, distinct 1200 by 630 PNG cards', async () => {
  const first = await renderSocialCard({title: 'Can I run this?', description: 'Verified installs on Linux, Synology, Kubernetes and Apple Silicon.', route: 'docs/run/tested-deployments/'}, siteDir);
  const second = await renderSocialCard({title: 'Configure authentication and network access for a shared household library', description: 'Use an API key with read permissions. Keep <private> values private & share only the finished film.', route: 'docs/run/network-security/'}, siteDir);
  for (const png of [first, second]) {
    const metadata = await sharp(png).metadata();
    assert.equal(metadata.format, 'png');
    assert.equal(metadata.width, 1200);
    assert.equal(metadata.height, 630);
    assert.ok(png.length > 10000);
    assert.ok(png.length < 500000);
  }
  assert.notEqual(createHash('sha256').update(first).digest('hex'), createHash('sha256').update(second).digest('hex'));
});
