import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import test from 'node:test';
import {runInNewContext} from 'node:vm';
import {analyticsHeadTags} from '../build-analytics.ts';

const base = `/immich-memories/${process.env.DOCS_NEXT === 'true' ? 'next/' : ''}`;
const origin = 'https://sam-dumont.github.io';
const siteId = 'docs.example.com';
const collector = 'https://metrics.example.com/api/event';
const fixture = {DOCS_ANALYTICS_DOMAIN: siteId, DOCS_ANALYTICS_ENDPOINT: collector};

function scriptsOn(page) {
  const html = readFileSync(join('build', page, 'index.html'), 'utf8');
  return [...html.matchAll(/<script\b[^>]*>/g)]
    .map(([tag]) => Object.fromEntries([...tag.matchAll(/([\w:-]+)="([^"]*)"/g)]
      .map(([, name, value]) => [name, value])))
    .filter(attributes => attributes['data-domain']);
}

test('unconfigured builds have no analytics; partial configuration is rejected', () => {
  assert.deepEqual(analyticsHeadTags(base, {}), []);
  for (const env of [{DOCS_ANALYTICS_DOMAIN: siteId}, {DOCS_ANALYTICS_ENDPOINT: collector}]) {
    assert.throws(() => analyticsHeadTags(base, env), /DOCS_ANALYTICS_DOMAIN.*DOCS_ANALYTICS_ENDPOINT/);
  }
});

test('build variables select the collector and identifier for either documentation base', () => {
  for (const path of ['/immich-memories/', '/immich-memories/next/']) {
    const tags = analyticsHeadTags(path, fixture);
    assert.equal(tags.length, 1);
    assert.equal(tags[0].attributes.src, `${path}js/app.js`);
    assert.equal(tags[0].attributes['data-domain'], siteId);
    assert.equal(tags[0].attributes['data-api'], collector);
  }
});

test('built home and nested pages load one local tracker only when configured', () => {
  const domain = process.env.DOCS_ANALYTICS_DOMAIN?.trim();
  const endpoint = process.env.DOCS_ANALYTICS_ENDPOINT?.trim();
  for (const page of ['', 'docs/get-started/quick-start']) {
    const scripts = scriptsOn(page);
    assert.equal(scripts.length, domain && endpoint ? 1 : 0);
    if (scripts.length) {
      assert.equal(scripts[0].src, `${base}js/app.js`);
      assert.equal(scripts[0]['data-domain'], domain);
      assert.equal(scripts[0]['data-api'], endpoint);
    }
  }
});

// WHY: replace only browser APIs and the network boundary. Execute the complete built
// tracker unchanged, with every event captured locally rather than sent to production.
function browser({ignore = false} = {}) {
  const {attributes} = analyticsHeadTags(base, fixture)[0];
  const code = readFileSync(join('build', 'js', 'app.js'), 'utf8');
  const events = [];
  const listeners = {window: {}, document: {}};
  const listen = target => (name, callback) => (listeners[target][name] ||= []).push(callback);
  const dispatch = (target, name, event = {}) => {
    for (const callback of listeners[target][name] || []) callback(event);
  };
  const location = new URL(base, origin);
  const fetch = async (url, options) => {
    events.push({url, ...JSON.parse(options.body)});
    return {status: 202};
  };
  const window = {
    location, fetch, navigator: {}, innerHeight: 800, scrollY: 0,
    localStorage: {plausible_ignore: String(ignore)},
    addEventListener: listen('window'),
    history: {pushState(_state, _title, path) { location.href = new URL(path, location).href; }},
  };
  const document = {
    currentScript: {
      src: new URL(attributes.src, origin).href,
      getAttribute: name => attributes[name] || null,
      getAttributeNames: () => Object.keys(attributes),
    },
    body: {scrollHeight: 2000}, documentElement: {clientHeight: 800},
    visibilityState: 'visible', referrer: '', hasFocus: () => true,
    addEventListener: listen('document'),
  };
  runInNewContext(code, {window, document, location, fetch, URL, console}, {timeout: 1000});
  const click = href => {
    const url = new URL(href, location);
    const target = {tagName: 'A', href: url.href, host: url.host, parentNode: null, classList: {length: 0}};
    dispatch('document', 'click', {type: 'click', target});
  };
  return {window, location, events, dispatch, click};
}

test('client-side navigation and back record one pageview each; anchors do not', () => {
  const {window, location, events, dispatch} = browser();
  const pageviews = () => events.filter(event => event.n === 'pageview');
  assert.equal(pageviews().length, 1);
  window.history.pushState({}, '', `${base}docs/get-started/quick-start/`);
  assert.equal(pageviews().length, 2);
  window.history.pushState({}, '', '#installation');
  dispatch('window', 'hashchange');
  assert.equal(pageviews().length, 2, 'Headings are not separate pages');
  location.href = new URL(base, origin).href;
  dispatch('window', 'popstate');
  assert.deepEqual(pageviews().map(event => event.u), [
    `${origin}${base}`, `${origin}${base}docs/get-started/quick-start/`, `${origin}${base}`,
  ]);
  assert.ok(events.every(event => event.url === collector && event.d === siteId));
});

test('outbound clicks, local downloads and custom properties reach the masked collector', () => {
  const {window, events, click} = browser();
  click('https://example.org/releases/');
  click(`${base}example.zip`);
  window.plausible('Section Viewed', {props: {section: 'installation'}});
  assert.deepEqual(events.filter(event => !['pageview', 'engagement'].includes(event.n))
    .map(({n, p, url}) => ({name: n, props: p, url})), [
    {name: 'Outbound Link: Click', props: {url: 'https://example.org/releases/'}, url: collector},
    {name: 'File Download', props: {url: `${origin}${base}example.zip`}, url: collector},
    {name: 'Section Viewed', props: {section: 'installation'}, url: collector},
  ]);
});

test('the tracker keeps the Plausible local opt-out', () => {
  const {window, events, click} = browser({ignore: true});
  window.history.pushState({}, '', `${base}docs/get-started/quick-start/`);
  click('https://example.org/');
  assert.deepEqual(events, []);
});
