import {execFileSync} from 'node:child_process';
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {docsTrack} from '../scripts/docs-track.mjs';
import {markdownPath} from './markdown-path.mjs';

/**
 * Turn the site-relative links in llms.txt into absolute links for the track being built
 * (stable, /next/ or /dev/), in the form the site serves them. A link to a docs page goes to
 * its Markdown version. A link to a page the build does not have throws, so the file cannot
 * drift from the docs. The version line goes under the summary.
 */
export function renderLlmsTxt(source, origin, baseUrl, routes, {markdownRoutes = new Set(), versionLine} = {}) {
  const missing = [];
  let text = source.replace(/\]\((\/[^)#\s]*)(#[^)\s]*)?\)/g, (_, path, hash = '') => {
    const route = [`${baseUrl}${path.slice(1)}`, `${baseUrl}${path.slice(1)}/`].find(r => routes.has(r));
    if (!route) missing.push(path);
    const isDoc = route && [...markdownRoutes].some(doc => markdownPath(doc) === markdownPath(route));
    const target = isDoc ? markdownPath(route) : route ?? path;
    return `](${origin}${target}${hash})`;
  });
  if (missing.length) throw new Error(`llms.txt links to pages that do not exist: ${missing.join(', ')}`);
  if (versionLine) text = text.replace(/^(> .*\n)/m, `$1\n${versionLine}\n`);
  return text;
}

const trackNames = {stable: 'stable', next: 'next (release candidate)', dev: 'dev (nightly build of main)'};

/** Which docs these are: track, version and source commit, or a local build. */
export function versionLine({track, version, commit, local}) {
  const parts = [`Docs track: ${trackNames[track]}`, ...(local ? ['local build'] : []), `version ${version}`, `source commit ${commit}`];
  return `${parts.join(', ')}.`;
}

function sourceCommit(siteDir) {
  try {
    return execFileSync('git', ['rev-parse', '--short=12', 'HEAD'], {cwd: siteDir, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore']}).trim();
  } catch {
    return 'unknown';
  }
}

export default function llmsTxt(context) {
  let docs = [];
  return {
    name: 'llms-txt',
    async allContentLoaded({allContent}) {
      const versions = allContent['docusaurus-plugin-content-docs']?.default?.loadedVersions ?? [];
      docs = versions.flatMap(version => version.docs).map(doc => ({
        file: join(context.siteDir, doc.source.replace(/^@site\//, '')),
        permalink: doc.permalink,
        title: doc.title,
      }));
    },
    injectHtmlTags() {
      // Every page names the index of its own track as the description of the site.
      return {headTags: [{tagName: 'link', attributes: {rel: 'describedby', type: 'text/plain', href: `${context.baseUrl}llms.txt`}}]};
    },
    async postBuild({siteConfig, routesPaths, outDir}) {
      const {siteDir} = context;
      const {version, sharedMedia = [], stableBaseUrl} = siteConfig.customFields;
      const routes = new Set(routesPaths);
      // Docusaurus loads plugins through a CommonJS loader that can't import the ESM-only
      // diagram renderer, so the Markdown pages are written by a plain Node process.
      const work = mkdtempSync(join(tmpdir(), 'docs-markdown-'));
      try {
        const build = join(work, 'build.json');
        writeFileSync(build, JSON.stringify({
          outDir, siteDir, origin: siteConfig.url, baseUrl: siteConfig.baseUrl, routes: [...routes], docs, sharedMedia, stableBaseUrl, version,
        }));
        const started = Date.now();
        execFileSync(process.execPath, ['--experimental-strip-types', '--no-warnings', join(siteDir, 'plugins/markdown-pages.mjs'), build], {stdio: 'inherit'});
        console.log(`[llms-txt] ${docs.length} Markdown pages in ${((Date.now() - started) / 1000).toFixed(1)} s`);
      } finally {
        rmSync(work, {recursive: true, force: true});
      }
      const markdownRoutes = new Set(docs.map(doc => doc.permalink));
      const source = readFileSync(join(siteDir, 'llms.txt'), 'utf8');
      const line = versionLine({track: docsTrack(), version, commit: sourceCommit(siteDir), local: process.env.GITHUB_ACTIONS !== 'true'});
      const text = renderLlmsTxt(source, siteConfig.url, siteConfig.baseUrl, routes, {markdownRoutes, versionLine: line});
      writeFileSync(join(outDir, 'llms.txt'), text);
    },
  };
}
