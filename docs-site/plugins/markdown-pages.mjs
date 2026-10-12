import {existsSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {dirname, join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {markdownPath} from './markdown-path.mjs';
import {pageMarkdown, siteComponents} from './page-markdown.mjs';

// Writes the Markdown version of every docs page next to its HTML. Run by the llms-txt plugin
// after the build: `node --experimental-strip-types plugins/markdown-pages.mjs build.json`.

/** The text of the InstallationFiles component, from the same recipes it renders. */
export async function installationText(siteDir) {
  const downloads = await import(pathToFileURL(join(siteDir, 'src/components/InstallationFiles/downloads.ts')).href);
  const recipes = await import(pathToFileURL(join(siteDir, 'src/components/SetupBuilder/recipes.ts')).href);
  return (kind, tier, version) => {
    if (!/^v?\d+\.\d+\.\d+(?:-rc\.\d+)?$/.test(version)) return null;
    if (kind === 'native') return {title: `Install ${version}: choose your platform`, commands: `# Linux / Intel Mac\n${recipes.nativeInstallCommand(version, 'all')}\n# Apple Silicon: use this instead\n${recipes.nativeInstallCommand(version, 'all-mac')}`};
    if (kind === 'unraid') return {title: `Install the ${version} template`, commands: downloads.unraidTemplateCommands(version)};
    if (kind === 'bundle') return {title: `Vendor ${version}`, commands: downloads.deploymentCommands(version)};
    const tierName = {basic: 'Basic', gpu: 'GPU', full: 'Full'}[tier];
    return {title: `Download ${tierName} installation files (${version})`, commands: downloads.installationCommands(version, tier)};
  };
}

/** Everything a page's Markdown needs to know about the build it belongs to. */
export function linkResolver({siteDir, origin, baseUrl, routes, docs, sharedMedia = [], stableBaseUrl = baseUrl}) {
  const docsByFile = new Map(docs.map(doc => [doc.file, doc.permalink]));
  const docPages = new Set(docs.map(doc => markdownPath(doc.permalink)));
  const staticUrl = path => {
    const key = path.replace(/^\//, '');
    return `${origin}${sharedMedia.includes(key) ? stableBaseUrl : baseUrl}${key}`;
  };
  const siteUrl = path => {
    const route = [`${baseUrl}${path.slice(1)}`, `${baseUrl}${path.slice(1)}/`].find(r => routes.has(r));
    if (route) return `${origin}${docPages.has(markdownPath(route)) ? markdownPath(route) : route}`;
    return staticUrl(path);
  };
  const resolveLink = (href, fromFile) => {
    if (!href || href.startsWith('#')) return href;
    if (href.startsWith('pathname://')) return `${origin}${baseUrl}${href.replace(/^pathname:\/\/\/?/, '')}`;
    if (/^[a-z][a-z+.-]*:/i.test(href)) return href;
    const [, path, suffix = ''] = href.match(/^([^?#]*)(.*)$/);
    if (/\.mdx?$/.test(path)) {
      const file = path.startsWith('/') ? join(siteDir, 'docs', path) : resolve(dirname(fromFile), path);
      const permalink = docsByFile.get(file);
      if (permalink) return `${origin}${markdownPath(permalink)}${suffix}`;
    }
    if (path.startsWith('/')) return `${siteUrl(path)}${suffix}`;
    const page = docs.find(doc => doc.file === fromFile)?.permalink ?? baseUrl;
    const absolute = new URL(path, `https://site${page}`).pathname;
    return `${siteUrl(`/${absolute.slice(baseUrl.length)}`)}${suffix}`;
  };
  const readStatic = path => {
    const file = join(siteDir, 'static', path);
    return existsSync(file) ? readFileSync(file) : undefined;
  };
  return {resolveLink, staticUrl, readStatic};
}

/** Write each docs page's Markdown version next to its HTML. Returns the routes written. */
export function writeMarkdownPages({outDir, origin, docs, components, ...build}) {
  const {resolveLink, staticUrl, readStatic} = linkResolver({origin, docs, ...build});
  for (const doc of docs) {
    const markdown = pageMarkdown(readFileSync(doc.file, 'utf8'), {
      file: doc.file, title: doc.title, htmlUrl: `${origin}${doc.permalink.replace(/\/?$/, '/')}`,
      resolveLink, staticUrl, readStatic, components,
    });
    const target = join(outDir, markdownPath(doc.permalink).slice(build.baseUrl.length));
    mkdirSync(dirname(target), {recursive: true});
    writeFileSync(target, markdown);
  }
  return new Set(docs.map(doc => doc.permalink));
}

/** The site's components as text, with the same data the HTML pages render. */
export async function buildComponents(siteDir, version) {
  return siteComponents({
    siteDir, version,
    deployment: await import(pathToFileURL(join(siteDir, 'src/components/deploymentModel.ts')).href),
    installation: await installationText(siteDir),
  });
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  const build = JSON.parse(readFileSync(process.argv[2], 'utf8'));
  const components = await buildComponents(build.siteDir, build.version);
  writeMarkdownPages({...build, routes: new Set(build.routes), components});
}
