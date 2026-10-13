import {existsSync, readFileSync} from 'node:fs';
import {dirname, join, resolve} from 'node:path';
import {unified} from 'unified';
import remarkParse from 'remark-parse';
import remarkMdx from 'remark-mdx';
import remarkGfm from 'remark-gfm';
import remarkDirective from 'remark-directive';
import remarkFrontmatter from 'remark-frontmatter';
import remarkStringify from 'remark-stringify';
import {mermaidText, svgDiagramText} from './diagram-text.mjs';

/**
 * The Markdown version of a docs page, built from its MDX source: what a reader sees on the
 * HTML page, as plain Markdown. Tabs become labelled sections, admonitions blockquotes, and
 * diagrams, screenshots, videos and the site's own components their text. Links are absolute
 * and stay in the track being built; links to other docs pages go to their Markdown version.
 *
 * Working from the source rather than the built HTML keeps code blocks, tables and Mermaid
 * source exactly as written, and the hidden tabs and diagram text that the HTML only holds
 * as markup or draws in the browser.
 */

const parser = unified().use(remarkParse).use(remarkFrontmatter).use(remarkGfm).use(remarkDirective).use(remarkMdx);
// Outlines are plain Markdown: a brace or angle bracket in a label is text.
const plainParser = unified().use(remarkParse);
const printer = unified().use(remarkStringify, {bullet: '-', fences: true, rule: '-', emphasis: '*', strong: '*', listItemIndent: 'one'}).use(remarkGfm, {tablePipeAlign: false});

/**
 * Parse MDX the way Docusaurus does: a heading's `{#id}` is its anchor, not an expression, and
 * `:::tip Title` is the admonition `:::tip[Title]`.
 */
function parse(source, file) {
  try {
    return parser.parse(source
      .replace(/^(#{1,6} .*?)\s*\{#[\w-]+\}\s*$/gm, '$1')
      .replace(/^(\s*:{3,})(\w+)[ \t]+([^[\n{].*?)\s*$/gm, (_, fence, name, title) => `${fence}${name}[${title.replace(/[[\]]/g, '\\$&')}]`));
  } catch (error) {
    throw new Error(`Markdown version of ${file}: ${error.message}`, {cause: error});
  }
}

const text = value => ({type: 'text', value});
const strong = value => ({type: 'strong', children: [text(value)]});
const paragraph = (...children) => ({type: 'paragraph', children});
const link = (url, label) => ({type: 'link', url, children: [text(label)]});
const code = (lang, value) => ({type: 'code', lang, value});

const attribute = (node, name) => {
  const found = node.attributes?.find(item => item.type === 'mdxJsxAttribute' && item.name === name);
  if (!found) return undefined;
  if (found.value === null) return true;
  if (typeof found.value === 'string') return found.value;
  const expression = found.value.value.trim();
  const literal = expression.match(/^(['"`])([\s\S]*)\1$/);
  if (literal) return literal[2];
  if (/^(true|false)$/.test(expression)) return expression === 'true';
  return /^-?\d+(\.\d+)?$/.test(expression) ? Number(expression) : expression;
};

const plain = nodes => nodes.map(node => (node.type === 'text' || node.type === 'inlineCode' ? node.value : plain(node.children ?? []))).join('');

const admonitionLabels = {note: 'Note', tip: 'Tip', info: 'Info', warning: 'Warning', caution: 'Caution', danger: 'Danger', important: 'Important'};

/** Duration in whole seconds from an MP4's movie header, or undefined when it can't be read. */
export function mp4Seconds(bytes) {
  const at = bytes.indexOf('mvhd');
  if (at < 0) return undefined;
  const version = bytes[at + 4];
  const view = new DataView(bytes.buffer, bytes.byteOffset + at + 8);
  const [scale, duration] = version === 1
    ? [view.getUint32(16), Number(view.getBigUint64(20))]
    : [view.getUint32(8), view.getUint32(12)];
  return scale ? Math.round(duration / scale) : undefined;
}

/**
 * @param {string} source the page's MDX
 * @param {object} page
 * @param {string} page.file absolute path of the source file
 * @param {string} page.title the page title, used when the source has no H1
 * @param {string} page.htmlUrl absolute URL of the HTML page
 * @param {(href: string, fromFile: string) => string} page.resolveLink absolute URL for a link
 * @param {(path: string) => string} page.staticUrl absolute URL for a file under static/
 * @param {(path: string) => Buffer | undefined} page.readStatic bytes of a file under static/
 * @param {Record<string, (node: object, page: object) => object[]>} [page.components] text for the site's components
 */
export function pageMarkdown(source, page) {
  const tree = parse(source, page.file);
  const body = convert(tree.children, page, page.file, imports(tree.children, page.file));
  if (!body.some(node => node.type === 'heading' && node.depth === 1)) body.unshift({type: 'heading', depth: 1, children: [text(page.title)]});
  const h1 = body.findIndex(node => node.type === 'heading' && node.depth === 1);
  body.splice(h1 + 1, 0, paragraph(text('Markdown version of '), link(page.htmlUrl, page.htmlUrl), text('.')));
  return printer.stringify({type: 'root', children: body});
}

/** Partials a page imports (`import Part from './_part.mdx'`), rendered in place. */
function imports(nodes, file) {
  const found = new Map();
  for (const node of nodes.filter(item => item.type === 'mdxjsEsm')) {
    for (const [, name, path] of node.value.matchAll(/import\s+(\w+)\s+from\s+['"](\.{1,2}\/[^'"]+\.mdx?)['"]/g)) {
      found.set(name, resolve(dirname(file), path));
    }
  }
  return found;
}

function convert(nodes, page, file, partials) {
  return nodes.flatMap(node => convertNode(node, page, file, partials));
}

function convertNode(node, page, file, partials) {
  const inner = () => convert(node.children ?? [], page, file, partials);
  switch (node.type) {
    case 'yaml':
    case 'mdxjsEsm':
    case 'mdxFlowExpression':
      return [];
    case 'mdxTextExpression': {
      const literal = node.value.trim().match(/^(['"`])([\s\S]*)\1$/);
      return literal ? [text(literal[2])] : [];
    }
    case 'link':
    case 'definition':
      return [{...node, url: page.resolveLink(node.url, file), children: node.children && inner()}];
    case 'image':
      return [{...node, url: page.resolveLink(node.url, file)}];
    case 'code':
      return node.lang === 'mermaid' ? mermaidBlock(node.value) : [node];
    case 'containerDirective':
      return admonition(node, inner);
    case 'leafDirective':
    case 'textDirective':
      // Not an admonition: the text as written (`10:30`, `:name[label]`).
      return [text(`${node.type === 'leafDirective' ? '::' : ':'}${node.name}`), ...inner()];
    case 'mdxJsxFlowElement':
      return element(node, page, file, partials, inner);
    case 'mdxJsxTextElement':
      // Inside a paragraph, a component's blocks give up their paragraphs.
      return element(node, page, file, partials, inner)
        .flatMap(item => (item.type === 'paragraph' ? [...item.children, {type: 'break'}] : [item]));
    default:
      return node.children ? [{...node, children: inner()}] : [node];
  }
}

function mermaidBlock(source) {
  const rendered = mermaidText(source);
  return rendered.kind === 'drawing'
    ? [code('text', rendered.text), code('mermaid', source)]
    : [paragraph(text('Diagram outline:')), ...plainParser.parse(rendered.text).children, code('mermaid', source)];
}

function admonition(node, inner) {
  const label = admonitionLabels[node.name];
  if (!label) return inner();
  const children = inner();
  const titled = children[0]?.data?.directiveLabel;
  const title = titled ? plain(children.shift().children) : label;
  const lead = paragraph(strong(`${title}:`));
  if (children[0]?.type === 'paragraph') children[0] = {...children[0], children: [strong(`${title}:`), text(' '), ...children[0].children]};
  else children.unshift(lead);
  return [{type: 'blockquote', children}];
}

function block(node, nodes) {
  // Phrasing content inside a flow element still needs a paragraph around it.
  return node.type === 'mdxJsxFlowElement' && nodes.length && nodes.every(item => !['paragraph', 'heading', 'list', 'code', 'table', 'blockquote', 'thematicBreak', 'html'].includes(item.type))
    ? [paragraph(...nodes)]
    : nodes;
}

function element(node, page, file, partials, inner) {
  const name = node.name ?? '';
  const flow = node.type === 'mdxJsxFlowElement';
  if (partials.has(name)) {
    const partial = partials.get(name);
    const tree = parse(readFileSync(partial, 'utf8'), partial);
    return convert(tree.children, page, partial, imports(tree.children, partial));
  }
  const custom = page.components?.[name];
  if (custom) return block(node, custom(node, {...page, attribute, inner, file}));
  switch (name) {
    case 'Tabs':
      return inner();
    case 'TabItem': {
      const label = attribute(node, 'label') ?? attribute(node, 'value') ?? 'Tab';
      return [paragraph(strong(`${label} tab:`)), ...inner()];
    }
    case 'details':
      return inner();
    case 'summary':
      return [paragraph(strong(plain(inner())))];
    case 'br':
      return flow ? [] : [{type: 'break'}];
    case 'a':
      return [{type: 'link', url: page.resolveLink(String(attribute(node, 'href') ?? ''), file), children: inner()}];
    case 'img':
      return block(node, [{type: 'image', url: page.resolveLink(String(attribute(node, 'src') ?? ''), file), alt: String(attribute(node, 'alt') ?? '')}]);
    case 'code':
      return [{type: 'inlineCode', value: plain(inner())}];
    case 'strong':
    case 'b':
      return [{type: 'strong', children: inner()}];
    case 'em':
    case 'i':
      return [{type: 'emphasis', children: inner()}];
    default:
      if (/^[a-z]/.test(name) || name === '') return block(node, inner());
      // A component this converter does not know: say so, and point at the page that shows it.
      return block(node, [text('This part of the page is interactive; see it on '), link(page.htmlUrl, 'the HTML page'), text('.')]);
  }
}

/** Text renderings of the site's own components, keyed by component name. */
export function siteComponents({siteDir, version, deployment, installation, composeHostPort}) {
  const diagramSvg = name => {
    const path = join(siteDir, 'static', 'diagrams', `${name}.svg`);
    return existsSync(path) ? readFileSync(path, 'utf8') : '';
  };
  const image = (page, path, alt, caption) => {
    const nodes = [{type: 'image', url: page.staticUrl(path), alt}];
    if (caption) nodes.push({type: 'break'}, {type: 'emphasis', children: [text(caption)]});
    return nodes;
  };
  return {
    Diagram(node, page) {
      const name = String(page.attribute(node, 'name'));
      const headline = String(page.attribute(node, 'headline') ?? '');
      const rendered = svgDiagramText(diagramSvg(name));
      const out = [paragraph(strong(`Diagram: ${headline}`), text(' '), link(page.staticUrl(`/diagrams/${name}.svg`), '(image)'))];
      if (rendered.kind === 'drawing') out.push(code('text', rendered.text));
      const outline = rendered.outline ?? rendered.text;
      if (outline) out.push(...plainParser.parse(outline).children);
      else out.push(paragraph(text(headline)));
      return out;
    },
    ThemedScreenshot(node, page) {
      const alt = String(page.attribute(node, 'alt') ?? '');
      return [paragraph(...image(page, `/img/screenshots/${page.attribute(node, 'name')}.png`, alt, page.attribute(node, 'caption')))];
    },
    Screenshot(node, page) {
      const alt = String(page.attribute(node, 'alt') ?? '');
      return [paragraph(...image(page, String(page.attribute(node, 'src')), alt, page.attribute(node, 'caption')))];
    },
    Video(node, page) {
      const src = String(page.attribute(node, 'src'));
      const poster = page.attribute(node, 'poster');
      const title = page.attribute(node, 'title');
      const bytes = page.readStatic(src);
      const seconds = bytes && mp4Seconds(bytes);
      const label = `Video${title ? `: ${title}` : ''}${seconds ? ` (${seconds} s)` : ''}`;
      const out = [strong(label), text(' '), link(page.staticUrl(src), src.split('/').pop())];
      if (poster) out.push({type: 'break'}, {type: 'image', url: page.staticUrl(String(poster)), alt: `Poster frame${title ? `: ${title}` : ''}`});
      return [paragraph(...out)];
    },
    StaticFile(node, page) {
      return [{type: 'link', url: page.staticUrl(String(page.attribute(node, 'href'))), children: page.inner()}];
    },
    InstallationFiles(node, page) {
      const kind = String(page.attribute(node, 'kind') ?? 'compose');
      const tier = String(page.attribute(node, 'tier') ?? 'basic');
      const files = installation?.(kind, tier, version);
      if (!files) {
        return [{type: 'blockquote', children: [paragraph(strong('Warning:'), text(' Prebuilt installation for this preview is not published. This page describes development code; check the '), link('https://github.com/sam-dumont/immich-memories/releases', 'application releases'), text(' for an installable version and its matching documentation.'))]}];
      }
      return [paragraph(strong(`${files.title}:`)), code('bash', files.commands)];
    },
    ComposePort(node, page) {
      if (!composeHostPort) return [link(page.htmlUrl, 'the host port on the HTML page')];
      const port = String(composeHostPort(version));
      const host = page.attribute(node, 'host');
      if (!host) return [text(port)];
      const url = `http://${host}:${port}`;
      return [page.attribute(node, 'link') ? link(url, url) : text(url)];
    },
    SetupBuilder(node, page) {
      return [paragraph(text('The setup builder on '), link(page.htmlUrl, 'the HTML page'), text(' generates the setup files for your choices in the browser. Pick a platform, a tier and the options there; nothing is sent anywhere.'))];
    },
    DeploymentDiagram(node, page) {
      if (!deployment) return [paragraph(text('A deployment explorer; see it on '), link(page.htmlUrl, 'the HTML page'), text('.'))];
      const chosen = page.attribute(node, 'chooseTopology') ? Object.keys(deployment.titles) : [String(page.attribute(node, 'topology') ?? 'basic')];
      return chosen.flatMap(topology => deploymentText(deployment, topology));
    },
  };
}

function deploymentText({model, phases, titles}, topology) {
  const out = [paragraph(strong(`Deployment: ${titles[topology]}`))];
  for (const phase of phases) {
    const {groups, flows, note} = model(topology, phase.id);
    const items = groups.map(group => ({type: 'listItem', spread: false, children: [paragraph(strong(group.title), text(` (${group.boundary})`)), {type: 'list', ordered: false, spread: false, children: [
      ...group.nodes.map(node => ({type: 'listItem', spread: false, children: [paragraph(strong(node.name), text(`, ${node.sub}: ${node.detail}`))]})),
      ...(group.storage ? [{type: 'listItem', spread: false, children: [paragraph(text(`Storage: ${group.storage}`))]}] : []),
    ]}]}));
    const steps = flows.map(flow => ({type: 'listItem', spread: false, children: [paragraph(strong(flow.label), text(`: ${flow.detail}`))]}));
    out.push(paragraph(text(`${phase.label}:`)), {type: 'list', ordered: false, spread: false, children: items},
      {type: 'list', ordered: true, start: 1, spread: false, children: steps}, paragraph(text(note)));
  }
  return out;
}
