import {renderMermaidASCII} from 'beautiful-mermaid';

/**
 * Text renderings of the docs diagrams, for the Markdown pages: a model reading a page gets
 * the boxes, arrows and labels a reader sees. Mermaid blocks draw as text; the rendered
 * diagram SVGs are read back into a graph and drawn the same way. When a diagram cannot be
 * drawn as text, an outline of its nodes and arrows stands in. A diagram never comes out
 * empty.
 */

// Wider than this and a text drawing wraps in most readers; the outline reads better.
const maxWidth = 140;
// The renderer's default vertical gap leaves room for arrow labels; less draws them over boxes.
const asciiOptions = {useAscii: false, paddingX: 2, boxBorderPadding: 0};

function trimDrawing(text) {
  const lines = text.split('\n').map(line => line.replace(/\s+$/, ''));
  while (lines.length && !lines[0]) lines.shift();
  while (lines.length && !lines.at(-1)) lines.pop();
  return lines.join('\n');
}

/** The label lines a drawing must show intact; the renderer can route an arrow through one. */
function labelLines(source) {
  return [...source.matchAll(/\["([^"]*)"\]|\[([^\]"]*)\]|\{([^}]*)\}|\|"?([^|"]*)"?\|/g)]
    .flatMap(match => (match[1] ?? match[2] ?? match[3] ?? match[4] ?? '').split(/<br\s*\/?>/i))
    .map(line => line.replace(/#quot;/g, '"').trim().replace(/^"|"$/g, '')).filter(line => line && line !== '*');
}

/**
 * The renderer draws an arrow through the spaces of a label it centres on that arrow
 * ("API│key"). Labels go in with no-break spaces and come out with plain ones.
 */
function protectLabels(source) {
  const keep = label => label.replace(/ /g, '\u00a0');
  return source
    .replace(/(\["|\[|\{|\||\()([^"\]}|)\n]+)(?=["\]}|)])/g, (_, open, label) => `${open}${keep(label)}`)
    .replace(/(--|-\.|==)\s([^-.=\n][^\n]*?)\s(-->|---|\.->|==>)/g, (_, start, label, end) => `${start} ${keep(label)} ${end}`)
    .replace(/^(\s*\S.*?(?:->>|-->>|->|-->|-x|--x|-\)|--\))\s*[^:\n]+:)(.*)$/gm, (_, head, label) => `${head}${keep(label)}`)
    .replace(/^(\s*[\w*[\]]+\s*-->\s*[\w*[\]]+\s*:)(.*)$/gm, (_, head, label) => `${head}${keep(label)}`);
}

function drawMermaid(source) {
  const drawing = trimDrawing(renderMermaidASCII(protectLabels(source), asciiOptions).replace(/\u00a0/g, ' '));
  const width = Math.max(...drawing.split('\n').map(line => [...line].length));
  if (!drawing || width > maxWidth) return null;
  if (labelLines(source).some(line => !drawing.includes(line))) return null;
  return drawing;
}

const plainLabel = label => label.replace(/<br\s*\/?>/gi, ' ').replace(/^["'`]|["'`]$/g, '').replace(/\s+/g, ' ').trim();

/** Nodes and arrows of a Mermaid diagram as an indented list, for types the renderer can't draw. */
export function mermaidOutline(source) {
  const lines = source.split('\n').map(line => line.trim()).filter(line => line && !line.startsWith('%%'));
  const [header = '', ...body] = lines;
  const out = [];
  if (/^sequenceDiagram/.test(header)) {
    let step = 0;
    for (const line of body) {
      const message = line.match(/^(.+?)\s*(-?->>?|--?[x)]|-?-\))\s*([^:]+?)\s*:\s*(.*)$/);
      if (message) out.push(`${++step}. ${message[1]} → ${message[3]}: ${message[4]}`);
      else if (/^(participant|actor)\s+/.test(line)) out.push(`- ${line}`);
      else if (/^note\s/i.test(line)) out.push(`   ${line}`);
    }
  } else if (/^(flowchart|graph|stateDiagram)/.test(header)) {
    const labels = new Map();
    const node = text => {
      const shaped = text.trim().match(/^([\w*[\]-]+?)\s*(?:\[\[|\[\(|\(\(|\[|\(|\{\{|\{|>)(.*?)(?:\]\]|\)\]|\)\)|\]|\)|\}\}|\})?$/);
      if (shaped && shaped[2]) { labels.set(shaped[1], plainLabel(shaped[2])); return shaped[1]; }
      return text.trim();
    };
    const name = id => (id === '[*]' ? '(start/end)' : labels.get(id) ?? id);
    const edges = [];
    for (const line of body) {
      if (/^(subgraph|end$|style|classDef|class |linkStyle|direction)/.test(line)) {
        if (line.startsWith('subgraph')) edges.push({group: plainLabel(line.replace(/^subgraph\s+/, '').replace(/^\w+\s*\[(.*)\]$/, '$1'))});
        continue;
      }
      const parts = line.split(/\s*(-->|---|-\.->|==>|--\s[^-]+?\s-->|--\s[^-]+?\s---)\s*/);
      if (parts.length < 3) { if (parts[0]) node(parts[0].split(':')[0]); continue; }
      for (let index = 0; index + 2 < parts.length; index += 2) {
        const [left, arrow, rightRaw] = [parts[index], parts[index + 1], parts[index + 2]];
        let right = rightRaw, label = arrow.match(/^--\s(.+?)\s--[->]$/)?.[1] ?? '';
        const piped = right.match(/^\|([^|]*)\|\s*(.*)$/);
        if (piped) [label, right] = [piped[1], piped[2]];
        const stateLabel = right.match(/^(.*?)\s*:\s*(.+)$/);
        if (stateLabel && /^stateDiagram/.test(header)) [right, label] = [stateLabel[1], stateLabel[2]];
        edges.push({from: node(left), to: node(right), label: plainLabel(label)});
      }
    }
    for (const edge of edges) {
      if (edge.group) out.push(`- Group: ${edge.group}`);
      else out.push(`- ${name(edge.from)} → ${name(edge.to)}${edge.label ? ` (${edge.label})` : ''}`);
    }
  }
  if (!out.length) for (const line of body) out.push(`- ${line}`);
  return out.join('\n');
}

/** A Mermaid block as a text drawing, or as an outline when it can't be drawn. */
export function mermaidText(source) {
  try {
    const drawing = drawMermaid(source);
    if (drawing) return {kind: 'drawing', text: drawing};
  } catch {
    // Not a type the renderer draws: the outline below stands in.
  }
  return {kind: 'outline', text: mermaidOutline(source)};
}

const entities = {amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' '};
const decode = text => text
  .replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code)))
  .replace(/&#x([0-9a-f]+);/gi, (_, code) => String.fromCodePoint(parseInt(code, 16)))
  .replace(/&(\w+);/g, (match, name) => entities[name] ?? match)
  .replace(/ /g, ' ');

function bounds(markup) {
  const numbers = [...markup.matchAll(/(?:\bd|\bpoints)="([^"]+)"/g)]
    .flatMap(([, value]) => value.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
  const xs = numbers.filter((_, index) => index % 2 === 0), ys = numbers.filter((_, index) => index % 2 === 1);
  return xs.length ? {x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys)} : null;
}

/**
 * Read a Graphviz SVG back into its graph: labelled nodes, labelled arrows, and the boxed
 * groups each node sits in (found by position, since the SVG does not nest them).
 */
export function graphFromSvg(svg) {
  const blocks = [...svg.matchAll(/<g id="[^"]+" class="(node|edge|cluster)">([\s\S]*?)(?=<g id="[^"]+" class="(?:node|edge|cluster)">|<\/svg>)/g)];
  const nodes = [], edges = [], groups = [];
  for (const [, kind, markup] of blocks) {
    const title = decode(markup.match(/<title>([\s\S]*?)<\/title>/)?.[1] ?? '');
    const texts = [...markup.matchAll(/<text\b([^>]*)>([\s\S]*?)<\/text>/g)]
      .map(([, attributes, text]) => ({
        x: Number(attributes.match(/\bx="([^"]+)"/)?.[1]),
        y: Number(attributes.match(/\by="([^"]+)"/)?.[1]),
        style: `${attributes.match(/font-size="([^"]+)"/)?.[1]}/${attributes.match(/font-weight="([^"]+)"/)?.[1]}/${attributes.match(/font-family="([^",]+)/)?.[1]}`,
        text: decode(text).replace(/\s+/g, ' ').trim(),
      }))
      .filter(text => text.text);
    if (kind === 'node') {
      const box = bounds(markup);
      const at = box ? {x: (box.x0 + box.x1) / 2, y: (box.y0 + box.y1) / 2} : texts[0];
      nodes.push({id: title, lines: texts.map(text => text.text), ...nodeText(texts), at});
    }
    else if (kind === 'edge') {
      const [from, to] = title.split(/->|--/);
      edges.push({from, to, label: texts.map(text => text.text).join(' ')});
    } else groups.push({id: title, label: texts.map(text => text.text).join(' · ') || title.replace(/^cluster_?/, ''), box: bounds(markup)});
  }
  const inside = (box, point) => box && point && point.x >= box.x0 && point.x <= box.x1 && point.y >= box.y0 && point.y <= box.y1;
  const area = box => (box.x1 - box.x0) * (box.y1 - box.y0);
  const smallestAround = (point, skip) => groups
    .filter(group => group !== skip && inside(group.box, point))
    .sort((a, b) => area(a.box) - area(b.box))[0];
  for (const group of groups) {
    const corner = group.box && {x: group.box.x0 + 0.5, y: group.box.y0 + 0.5};
    group.parent = groups
      .filter(other => other !== group && other.box && group.box && area(other.box) > area(group.box) && inside(other.box, corner))
      .sort((a, b) => area(a.box) - area(b.box))[0];
  }
  for (const node of nodes) node.group = smallestAround(node.at);
  return {nodes: nodes.filter(node => node.lines.length), edges, groups};
}

/**
 * A node's text as a reader takes it in: wrapped lines in one type style are one phrase, the
 * first style names an item, and smaller lines after it describe that item. A node drawn as
 * a grid of cards gives one item per card.
 */
export function nodeText(texts) {
  const phrases = [];
  texts.forEach((text, index) => {
    if (index && text.style === texts[index - 1].style) phrases[phrases.length - 1].text += ` ${text.text}`;
    else phrases.push({...text});
  });
  const items = [];
  for (const phrase of phrases) {
    if (!items.length || phrase.style === phrases[0].style) items.push({name: phrase.text, details: []});
    else items.at(-1).details.push(phrase.text);
  }
  return {
    name: items.map(item => item.name).join('; '),
    text: items.map(item => (item.details.length ? `${item.name} (${item.details.join('; ')})` : item.name)).join('; '),
  };
}

const quote = text => `"${text.replace(/"/g, '#quot;')}"`;

/** A graph from graphFromSvg as a Mermaid flowchart. */
export function graphToMermaid(graph, direction = 'TD', {groups = true} = {}) {
  const ids = new Map(graph.nodes.map((node, index) => [node.id, `n${index}`]));
  const groupIds = new Map(graph.groups.map((group, index) => [group, `g${index}`]));
  const lines = [`flowchart ${direction}`];
  const emit = (parent, indent) => {
    for (const group of groups ? graph.groups.filter(group => group.parent === parent) : []) {
      lines.push(`${indent}subgraph ${groupIds.get(group)}[${quote(group.label)}]`);
      emit(group, `${indent}  `);
      lines.push(`${indent}end`);
    }
    for (const node of graph.nodes.filter(node => !groups || (node.group ?? undefined) === parent)) {
      lines.push(`${indent}${ids.get(node.id)}[${quote(node.lines.join('<br/>'))}]`);
    }
  };
  emit(undefined, '  ');
  for (const edge of graph.edges) {
    if (!ids.has(edge.from) || !ids.has(edge.to)) continue;
    lines.push(`  ${ids.get(edge.from)} -->${edge.label ? `|${quote(edge.label)}|` : ''} ${ids.get(edge.to)}`);
  }
  return lines.join('\n');
}

/**
 * A graph from graphFromSvg as a Markdown outline. With a drawing beside it, the outline
 * adds what the drawing leaves out: the groups and an unambiguous list of arrows. Without
 * one, it lists every box too.
 */
export function graphOutline(graph, {drawn = false} = {}) {
  const name = id => graph.nodes.find(node => node.id === id)?.name ?? id;
  const out = [];
  const emit = (parent, indent) => {
    for (const group of graph.groups.filter(group => group.parent === parent)) {
      out.push(`${indent}- ${group.label}`);
      emit(group, `${indent}  `);
    }
    for (const node of graph.nodes.filter(node => (node.group ?? undefined) === parent)) {
      if (!drawn || parent) out.push(`${indent}- ${drawn ? node.name : node.text}`);
    }
  };
  if (!drawn || graph.groups.length) {
    out.push(drawn ? 'Groups:' : 'Boxes:', '');
    emit(undefined, '');
  }
  const arrows = graph.edges.filter(edge => graph.nodes.some(node => node.id === edge.from) && graph.nodes.some(node => node.id === edge.to));
  if (arrows.length) {
    if (out.length) out.push('');
    out.push('Arrows:', '');
    for (const edge of arrows) out.push(`- ${name(edge.from)} → ${name(edge.to)}${edge.label ? ` (${edge.label})` : ''}`);
  }
  return out.join('\n');
}

/**
 * A rendered diagram SVG as a text drawing plus its outline, or the outline alone when no
 * drawing fits. The drawing leaves out the group boxes: the renderer misplaces nodes inside
 * nested groups, and where arrows share a line the drawing alone is ambiguous. The outline
 * names the groups and every arrow.
 */
export function svgDiagramText(svg) {
  const graph = graphFromSvg(svg);
  if (!graph.nodes.length) return {kind: 'outline', text: ''};
  const drawings = [];
  for (const direction of ['TD', 'LR']) {
    try {
      const drawing = drawMermaid(graphToMermaid(graph, direction, {groups: false}));
      if (drawing) drawings.push(drawing);
    } catch {
      // Try the other direction, then the outline.
    }
  }
  drawings.sort((a, b) => a.length - b.length);
  return drawings.length ? {kind: 'drawing', text: drawings[0], outline: graphOutline(graph, {drawn: true})} : {kind: 'outline', text: graphOutline(graph)};
}
