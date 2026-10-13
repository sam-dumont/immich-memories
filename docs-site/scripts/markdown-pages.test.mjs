import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import test from 'node:test';
import {graphFromSvg, mermaidText, svgDiagramText} from '../plugins/diagram-text.mjs';
import {buildComponents, linkResolver} from '../plugins/markdown-pages.mjs';
import {mp4Seconds, pageMarkdown, siteComponents} from '../plugins/page-markdown.mjs';

const siteDir = resolve('.');
const origin = 'https://sam-dumont.github.io';
const base = '/immich-memories/next/';
const docs = [
  {file: join(siteDir, 'docs/run/nas.md'), permalink: `${base}docs/run/nas/`, title: 'On a NAS'},
  {file: join(siteDir, 'docs/run/docker.md'), permalink: `${base}docs/run/docker/`, title: 'Docker'},
];
const routes = new Set([...docs.map(doc => doc.permalink), `${base}setup/`]);

/** A one-second MP4 movie header: just enough of the file for its duration. */
function mp4(seconds) {
  const bytes = new Uint8Array(32);
  bytes.set([...'mvhd'].map(char => char.charCodeAt(0)), 0);
  const view = new DataView(bytes.buffer);
  view.setUint32(16, 1000);
  view.setUint32(20, seconds * 1000);
  return Buffer.from(bytes);
}

function render(source, components = siteComponents({siteDir, version: 'development'})) {
  const {resolveLink, staticUrl} = linkResolver({siteDir, origin, baseUrl: base, routes, docs, sharedMedia: ['img/shared.png'], stableBaseUrl: '/immich-memories/'});
  return pageMarkdown(source, {
    file: docs[0].file, title: 'On a NAS', htmlUrl: `${origin}${base}docs/run/nas/`, resolveLink, staticUrl,
    readStatic: path => (path.endsWith('.mp4') ? mp4(12) : undefined), components,
  });
}

test('tabs become labelled sections, every one of them', () => {
  const text = render(`import Tabs from '@theme/Tabs';\nimport TabItem from '@theme/TabItem';\n\n# Page\n\n<Tabs>\n<TabItem value="basic" label="Basic">\n\nOne app.\n\n</TabItem>\n<TabItem value="gpu" label="GPU">\n\nApp and services.\n\n</TabItem>\n</Tabs>\n`);
  assert.match(text, /\*\*Basic tab:\*\*\n\nOne app\.\n\n\*\*GPU tab:\*\*\n\nApp and services\./);
  assert.doesNotMatch(text, /import|<Tab/);
});

test('admonitions become blockquotes with their label or title', () => {
  const text = render('# Page\n\n:::warning\n\nKeep the key private.\n\n:::\n\n:::tip Config tiers\n\nTier 2 goes under `advanced:`.\n\n:::\n');
  assert.match(text, /> \*\*Warning:\*\* Keep the key private\./);
  assert.match(text, /> \*\*Config tiers:\*\* Tier 2 goes under `advanced:`\./);
  assert.doesNotMatch(text, /:::/);
});

test('a Mermaid flowchart is drawn as text, with its source below', () => {
  const text = render('# Page\n\n```mermaid\nflowchart TD\n  A[Selected Live Photo] --> B{Useful motion?}\n  B -- Yes --> C[Play the clip]\n  B -- No --> D[Animate the still]\n```\n');
  const [drawing, source] = [text.match(/```text\n([\s\S]*?)```/)[1], text.match(/```mermaid\n([\s\S]*?)```/)[1]];
  for (const label of ['Selected Live Photo', 'Useful motion?', 'Play the clip', 'Animate the still', 'Yes', 'No']) assert.ok(drawing.includes(label), label);
  assert.match(drawing, /[▼►]/);
  assert.ok(text.indexOf('```text') < text.indexOf('```mermaid'));
  assert.match(source, /^flowchart TD/);
});

test('sequence and state diagrams draw as text with their labels and arrows', () => {
  const sequence = mermaidText('sequenceDiagram\n  Browser->>App: Cut\n  App-->>Browser: Contact sheet');
  assert.equal(sequence.kind, 'drawing');
  for (const label of ['Browser', 'App', 'Cut', 'Contact sheet']) assert.ok(sequence.text.includes(label), label);
  assert.match(sequence.text, /[▶◀]/);
  const state = mermaidText('stateDiagram-v2\n  [*] --> Queued\n  Queued --> Running: start\n  Running --> Done');
  assert.equal(state.kind, 'drawing');
  for (const label of ['Queued', 'Running', 'Done', 'start']) assert.ok(state.text.includes(label), label);
  assert.match(state.text, /▼/);
});

test('a diagram type the renderer can\'t draw becomes an outline, never nothing', () => {
  const gantt = mermaidText('gantt\n  title Release\n  section Build\n  Candidate :a1, 2026-01-01, 3d');
  assert.equal(gantt.kind, 'outline');
  assert.match(gantt.text, /- title Release\n- section Build\n- Candidate/);
  const text = render('# Page\n\n```mermaid\npie title Pets\n  "Dogs" : 386\n  "Cats" : 85\n```\n');
  assert.match(text, /Diagram outline:\n\n- title Pets|Diagram outline:\n\n- "Dogs" : 386/);
  assert.match(text, /```mermaid\npie title Pets/);
});

test('tables stay Markdown tables', () => {
  const text = render('# Page\n\n| Tier | Needs |\n|---|---|\n| **Basic** | 2 CPU cores |\n');
  assert.match(text, /\| Tier \| Needs \|\n\| - \| - \|\n\| \*\*Basic\*\* \| 2 CPU cores \|/);
});

test('images, screenshots and videos keep their alt text, caption, duration and full URLs', () => {
  const text = render(`import ThemedScreenshot from '@site/src/components/ThemedScreenshot';\nimport Video from '@site/src/components/Video';\n\n# Page\n\n![The Download models card](/img/model-setup.png)\n\n![Shared](/img/shared.png)\n\n<ThemedScreenshot name="memory-brief" alt="The memory brief with its Cut button" />\n\n<Video title="A sample trip film" src="/demo/trip.mp4" poster="/img/trip.jpg" controls />\n`);
  assert.match(text, /!\[The Download models card\]\(https:\/\/sam-dumont\.github\.io\/immich-memories\/next\/img\/model-setup\.png\)/);
  assert.match(text, /!\[Shared\]\(https:\/\/sam-dumont\.github\.io\/immich-memories\/img\/shared\.png\)/);
  assert.match(text, /!\[The memory brief with its Cut button\]\(https:\/\/sam-dumont\.github\.io\/immich-memories\/next\/img\/screenshots\/memory-brief\.png\)/);
  assert.match(text, /\*\*Video: A sample trip film \(12 s\)\*\* \[trip\.mp4\]\(https:\/\/sam-dumont\.github\.io\/immich-memories\/next\/demo\/trip\.mp4\)/);
  assert.match(text, /!\[Poster frame: A sample trip film\]\(https:\/\/sam-dumont\.github\.io\/immich-memories\/next\/img\/trip\.jpg\)/);
  assert.equal(mp4Seconds(mp4(45)), 45);
});

test('the site\'s components render as their text; an unknown one points at the HTML page', async () => {
  const components = await buildComponents(siteDir, 'v1.0.0-rc.10');
  const text = render(`import DeploymentDiagram from '@site/src/components/DeploymentDiagram';\nimport InstallationFiles from '@site/src/components/InstallationFiles';\nimport Widget from '@site/src/components/Widget';\n\n# Page\n\n<DeploymentDiagram topology="worker" />\n\n<InstallationFiles kind="compose" tier="gpu" />\n\n<Widget mode="x" />\n\n<Diagram name="seq-generate" headline="From your library to a finished film." />\n`, components);
  assert.match(text, /\*\*Deployment: App \+ one GPU service\*\*/);
  assert.match(text, /Prepare a cut:[\s\S]*Render a film:[\s\S]*Open the app:/);
  assert.match(text, /\*\*Render worker\*\*, Port 8092 · \/render: Receives the cut/);
  assert.match(text, /\*\*Download GPU installation files \(v1\.0\.0-rc\.10\):\*\*\n\n```bash\nmkdir -p immich-memories/);
  assert.match(text, /This part of the page is interactive; see it on \[the HTML page\]\(https:\/\/sam-dumont\.github\.io\/immich-memories\/next\/docs\/run\/nas\/\)/);
  assert.match(text, /\*\*Diagram: From your library to a finished film\.\*\* \[\(image\)\]\(https:\/\/sam-dumont\.github\.io\/immich-memories\/next\/diagrams\/seq-generate\.svg\)/);
  assert.match(text, /```text\n[\s\S]*1 Read[\s\S]*5 Render[\s\S]*```/);
  assert.match(text, /- 1 Read → 2 Look/);
  assert.doesNotMatch(text.replace(/```[\s\S]*?```/g, ''), /<\/?[A-Z]/);
});

test('the Compose host port renders as text for the release being built', async () => {
  const page = `import ComposePort from '@site/src/components/ComposePort';\n\n# Page\n\nThe mapping is <code>127.0.0.1:<ComposePort />:8080</code>. Open <ComposePort host="localhost" link /> or <code><ComposePort host="your-server" /></code>.\n`;
  for (const [version, port] of [['v1.0.0-rc.9', 8080], ['v1.0.0-rc.10', 22830], ['development', 22830]]) {
    const text = render(page, await buildComponents(siteDir, version));
    assert.match(text, new RegExp(`\`127\\.0\\.0\\.1:${port}:8080\``), version);
    assert.match(text, new RegExp(`<http://localhost:${port}>`), version);
    assert.match(text, new RegExp(`\`http://your-server:${port}\``), version);
    assert.doesNotMatch(text, /interactive/, version);
  }
});

test('links are absolute in the track being built, and docs links go to Markdown', () => {
  const text = render('# Page\n\n[Docker](./docker.md#the-api-key), [builder](/setup), [credits](/demo/credits.txt), [index](pathname:///llms.txt), [Immich](https://immich.app), [below](#later)\n');
  assert.match(text, /\[Docker\]\(https:\/\/sam-dumont\.github\.io\/immich-memories\/next\/docs\/run\/docker\.md#the-api-key\)/);
  assert.match(text, /\[builder\]\(https:\/\/sam-dumont\.github\.io\/immich-memories\/next\/setup\/\)/);
  assert.match(text, /\[credits\]\(https:\/\/sam-dumont\.github\.io\/immich-memories\/next\/demo\/credits\.txt\)/);
  assert.match(text, /\[index\]\(https:\/\/sam-dumont\.github\.io\/immich-memories\/next\/llms\.txt\)/);
  assert.match(text, /\[Immich\]\(https:\/\/immich\.app\)/);
  assert.match(text, /\[below\]\(#later\)/);
  assert.match(text, /^# Page\n\nMarkdown version of <https:\/\/sam-dumont\.github\.io\/immich-memories\/next\/docs\/run\/nas\/>\./);
});

test('a rendered diagram SVG reads back into its boxes, groups and arrows', () => {
  const graph = graphFromSvg(readFileSync('static/diagrams/architecture-detailed.svg', 'utf8'));
  const names = graph.nodes.map(node => node.name);
  for (const name of ['Browser', 'FastAPI', 'Job runner', 'Film run']) assert.ok(names.includes(name), name);
  const fastApi = graph.nodes.find(node => node.name === 'FastAPI');
  assert.match(fastApi.group.label, /^Web server process/);
  assert.equal(fastApi.group.parent.label, 'Your app host');
  assert.equal(graph.nodes.find(node => node.name === 'Browser').group, undefined);
  const rendered = svgDiagramText(readFileSync('static/diagrams/architecture-detailed.svg', 'utf8'));
  assert.equal(rendered.kind, 'drawing');
  assert.match(rendered.outline, /- Browser → FastAPI/);
});
