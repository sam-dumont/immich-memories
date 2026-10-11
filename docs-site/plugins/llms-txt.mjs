import {readFileSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';

/**
 * Turn the site-relative links in llms.txt into absolute links for the track being built
 * (stable, /next/ or /dev/), in the form the site serves them. A link to a page the build
 * does not have throws, so the file cannot drift from the docs.
 */
export function renderLlmsTxt(source, origin, baseUrl, routes) {
  const missing = [];
  const text = source.replace(/\]\((\/[^)#\s]*)(#[^)\s]*)?\)/g, (_, path, hash = '') => {
    const route = [`${baseUrl}${path.slice(1)}`, `${baseUrl}${path.slice(1)}/`].find(r => routes.has(r));
    if (!route) missing.push(path);
    return `](${origin}${route ?? path}${hash})`;
  });
  if (missing.length) throw new Error(`llms.txt links to pages that do not exist: ${missing.join(', ')}`);
  return text;
}

export default function llmsTxt(context) {
  return {
    name: 'llms-txt',
    async postBuild({siteConfig, routesPaths, outDir}) {
      const source = readFileSync(join(context.siteDir, 'llms.txt'), 'utf8');
      const text = renderLlmsTxt(source, siteConfig.url, siteConfig.baseUrl, new Set(routesPaths));
      writeFileSync(join(outDir, 'llms.txt'), text);
    },
  };
}
