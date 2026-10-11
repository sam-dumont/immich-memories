import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import test from 'node:test';
import {runInNewContext} from 'node:vm';
import {analyticsHeadTags} from '../build-analytics.ts';
import {installEvents} from '../src/analytics/events.ts';
import {docsTrack, trackPath} from './docs-track.mjs';

const base = `/immich-memories/${trackPath(docsTrack())}`;
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
  for (const path of ['/immich-memories/', '/immich-memories/next/', '/immich-memories/dev/']) {
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
  return {window, document, location, events, dispatch, click};
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

// WHY: the custom events run against the real bundled tracker, so a renamed event or prop
// shows up here and not in the Plausible dashboard weeks later.
function node(selectors, {parent = null, text = '', attrs = {}, children = []} = {}) {
  const element = {
    selectors, parent, parentNode: null, textContent: text, tagName: 'DIV', classList: {length: 0},
    getAttribute: name => attrs[name] ?? null,
    closest(selector) {
      for (let at = this; at; at = at.parent) if (at.selectors.includes(selector)) return at;
      return null;
    },
    querySelector(selector) {
      for (const child of children) {
        const found = child.selectors.includes(selector) ? child : child.querySelector(selector);
        if (found) return found;
      }
      return null;
    },
    ...attrs.currentSrc ? {currentSrc: attrs.currentSrc} : {},
  };
  for (const child of children) child.parent = element;
  return element;
}

function codeBlock(command, {tier} = {}) {
  const code = node(['pre code'], {text: command});
  const button = node(['button[aria-label^="Copy"]'], {attrs: {'aria-label': 'Copy code to clipboard'}});
  const block = node(['.theme-code-block'], {children: [code, button]});
  if (!tier) return {button};
  const tab = node(['[role="tab"]', '[role="tab"][aria-selected="true"]'], {text: tier, attrs: {'aria-selected': 'true'}});
  const container = node(['.tabs-container'], {children: [tab]});
  const panel = node(['[role="tabpanel"]'], {children: [block]});
  panel.parent = container;
  container.children = [tab, panel];
  return {button};
}

function withEvents(options) {
  const page = browser(options);
  const pathname = `${base}docs/get-started/quick-start/`;
  page.location.href = new URL(pathname, origin).href;
  installEvents({window: page.window, document: page.document, baseUrl: base});
  const custom = () => page.events.filter(event => !['pageview', 'engagement'].includes(event.n))
    .map(({n, p}) => ({name: n, props: p}));
  return {...page, custom};
}

test('copying an install command records the page, tier and command kind, never the command', () => {
  const page = withEvents();
  const cases = [
    ['curl -fsSL https://example.org/a.yml -o a.yml', 'curl'], ['$ docker compose up -d', 'docker'],
    ['# comment\nuv tool install immich-memories', 'uv'], ['kubectl apply -k .', 'kubectl'],
    ['helm install x y', 'helm'], ['pip install x', 'pip'], ['export SECRET=hunter2', 'other'],
  ];
  for (const [command] of cases) page.dispatch('document', 'click', {target: codeBlock(command, {tier: 'GPU'}).button});
  page.dispatch('document', 'click', {target: codeBlock('docker run x').button});
  assert.deepEqual(page.custom(), [
    ...cases.map(([, kind]) => ({name: 'Install Command Copied', props: {page: '/docs/get-started/quick-start/', tier: 'gpu', kind}})),
    {name: 'Install Command Copied', props: {page: '/docs/get-started/quick-start/', tier: 'none', kind: 'docker'}},
  ]);
  assert.ok(!JSON.stringify(page.events).includes('hunter2'));
});

test('other buttons and copy buttons outside code blocks record nothing', () => {
  const page = withEvents();
  const stray = node(['button[aria-label^="Copy"]'], {attrs: {'aria-label': 'Copy .env'}});
  page.dispatch('document', 'click', {target: stray});
  assert.deepEqual(page.custom(), []);
});

test('choosing an install tier records it once, and only for the tier tabs', () => {
  const page = withEvents();
  const tab = (label, selected) => node(['[role="tab"]'], {text: label, attrs: {'aria-selected': String(selected)},
    parent: node(['.tabs-container'])});
  page.dispatch('document', 'click', {target: tab('Full', false)});
  page.dispatch('document', 'click', {target: tab('Basic', true)});
  page.dispatch('document', 'click', {target: tab('Debian', false)});
  assert.deepEqual(page.custom(), [{name: 'Install Tier Selected', props: {tier: 'full'}}]);
});

test('a demo video counts once per page view, by file name; an autoplay start does not count', () => {
  const page = withEvents();
  const video = (src, attrs = {}) => node(['video'], {attrs: {currentSrc: src, ...attrs}});
  const demo = video(`${origin}${base}demo/demo.mp4?x=1`);
  page.dispatch('document', 'play', {target: demo});
  page.dispatch('document', 'play', {target: demo});
  const auto = video(`${origin}${base}demo/dark-demo.mp4`, {'data-autoplay': 'true'});
  page.dispatch('document', 'play', {target: auto});
  assert.deepEqual(page.custom(), [{name: 'Demo Played', props: {video: 'demo.mp4'}}]);
  page.dispatch('document', 'pause', {target: auto});
  page.dispatch('document', 'play', {target: auto});
  assert.deepEqual(page.custom().at(-1), {name: 'Demo Played', props: {video: 'dark-demo.mp4'}});
});

test('no event fires when the tracker is absent or the visitor opted out', () => {
  const absent = browser();
  delete absent.window.plausible;
  const dispatch = absent.dispatch;
  const events = installEvents({window: absent.window, document: absent.document, baseUrl: base});
  absent.events.length = 0;
  dispatch('document', 'click', {target: codeBlock('docker run x').button});
  dispatch('document', 'play', {target: node(['video'], {attrs: {currentSrc: 'https://x/y.mp4'}})});
  events.track('404', {path: '/x'});
  assert.deepEqual(absent.events, []);
  const optedOut = withEvents({ignore: true});
  optedOut.dispatch('document', 'click', {target: codeBlock('docker run x').button});
  assert.deepEqual(optedOut.events, []);
});

test('the site wires the events: client module, 404 page and setup builder', () => {
  const sources = ['src/analytics-events.ts', 'src/theme/NotFound/index.tsx', 'src/components/SetupBuilder/index.tsx']
    .map(file => readFileSync(file, 'utf8')).join('\n');
  for (const name of ['Setup Builder Downloaded', 'Setup Builder Copied', "'404'"]) assert.ok(sources.includes(name), name);
  assert.match(readFileSync('docusaurus.config.ts', 'utf8'), /clientModules:\s*\[[^\]]*analytics-events/);
});
