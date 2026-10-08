import {mkdirSync} from 'node:fs';
import {homedir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import sharp from 'sharp';

// The build uses the bundled Inter fonts on Linux and macOS, without system fonts.
process.env.FONTCONFIG_FILE ??= fileURLToPath(new URL('./social-fonts.conf', import.meta.url));
mkdirSync(join(process.env.XDG_CACHE_HOME || join(homedir(), '.cache'), 'fontconfig'), {recursive: true});

function decode(value) {
  const entities = {amp: '&', lt: '<', gt: '>', quot: '"', apos: "'"};
  return value.replace(/&(#x[\da-f]+|#\d+|amp|lt|gt|quot|apos);/gi, (match, name) =>
    name.startsWith('#') ? String.fromCodePoint(parseInt(name.slice(name[1] === 'x' ? 2 : 1), name[1] === 'x' ? 16 : 10)) : entities[name] ?? match);
}

export function readPageMetadata(html) {
  const tags = [...html.split('</head>')[0].matchAll(/<meta\s[^>]*>/g)]
    .map(([tag]) => Object.fromEntries([...tag.matchAll(/([\w:-]+)="([^"]*)"/g)].map(([, name, value]) => [name, decode(value)])));
  const content = name => tags.find(tag => tag.property === name || tag.name === name)?.content;
  if (!content('og:title') || !content('og:image')) return null;
  return {
    title: content('og:title').replace(/ \| Immich Memories$/, ''),
    description: content('description') || '',
    image: content('og:image'),
  };
}

function escapeMarkup(value) {
  return value.replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;'}[char]));
}

async function textImage(text, {size, weight = '', color, width, height}, siteDir) {
  for (let fontSize = size; fontSize >= 18; fontSize -= 2) {
    const rendered = await sharp({text: {
      text: `<span foreground="${color}">${escapeMarkup(text)}</span>`,
      font: `Inter ${weight} ${fontSize}`,
      // Sharp's Linux build needs TrueType, decoded from the site's Inter WOFF2.
      fontfile: join(siteDir, 'static/fonts/inter-latin.ttf'),
      width,
      spacing: 8,
      rgba: true,
    }}).png().toBuffer({resolveWithObject: true});
    if (rendered.info.height <= height) return rendered;
  }
  throw new Error('Social card text does not fit');
}

/** A readable topic card made entirely from the site's existing font and logo. */
export async function renderSocialCard({title, description, route}, siteDir) {
  const heading = await textImage(title, {size: 70, weight: 'Bold', color: '#252938', width: 980, height: 220}, siteDir);
  const summary = description && await textImage(description, {size: 30, color: '#606776', width: 980, height: 122}, siteDir);
  const brand = await textImage('Immich Memories', {size: 30, weight: 'Semi-Bold', color: '#4250af', width: 850, height: 50}, siteDir);
  const address = await textImage(route || 'sam-dumont.github.io/immich-memories', {size: 22, color: '#606776', width: 1000, height: 38}, siteDir);
  const logo = await sharp(join(siteDir, 'static/img/logo.svg')).resize(70, 70).png().toBuffer();
  const film = Buffer.from(`<svg width="1200" height="630" xmlns="http://www.w3.org/2000/svg">
    <rect x="1152" width="48" height="630" fill="#4250af"/>
    ${Array.from({length: 10}, (_, i) => `<rect x="1169" y="${23 + i * 64}" width="14" height="20" rx="3" fill="#fff"/>`).join('')}
  </svg>`);
  const layers = [
    {input: film, top: 0, left: 0},
    {input: logo, top: 48, left: 68},
    {input: brand.data, top: 69, left: 151},
    {input: heading.data, top: 164, left: 80},
    {input: address.data, top: 554, left: 80},
  ];
  if (summary) layers.push({input: summary.data, top: 190 + heading.info.height, left: 80});
  return sharp({create: {width: 1200, height: 630, channels: 3, background: '#ffffff'}})
    .composite(layers).png().toBuffer();
}
