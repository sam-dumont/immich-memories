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
  const article = html.match(/<article\b[^>]*>([\s\S]*?)<\/article>/)?.[1] || '';
  const poster = article.match(/<video\b[^>]*\bposter="([^"]+)"/)?.[1];
  const picture = article.match(/<img\b[^>]*\bsrc="([^"]+\.(?:png|jpe?g|webp))"/)?.[1];
  return {
    media: poster || picture ? decode(poster || picture) : undefined,
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
export async function renderSocialCard({title, description = '', route, mediaPath = ''}, siteDir) {
  if (mediaPath) return renderMediaCard({title, route, mediaPath}, siteDir);
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


/** Keep the page's actual film or UI visible behind a short, readable heading. */
async function renderMediaCard({title, route, mediaPath}, siteDir) {
  if (mediaPath.includes('/img/screenshots/')) return renderScreenshotCard({title, route, mediaPath}, siteDir);
  const picture = await sharp(mediaPath).rotate().resize(1200, 630, {fit: 'cover'}).png().toBuffer();
  const heading = await textImage(title, {size: 60, weight: 'Bold', color: '#ffffff', width: 1030, height: 150}, siteDir);
  const address = await textImage(route, {size: 22, color: '#e0e4f0', width: 1030, height: 35}, siteDir);
  const brand = await textImage('Immich Memories', {size: 26, weight: 'Semi-Bold', color: '#252938', width: 290, height: 40}, siteDir);
  const logo = await sharp(join(siteDir, 'static/img/logo.svg')).resize(44, 44).png().toBuffer();
  const shade = Buffer.from(`<svg width="1200" height="630" xmlns="http://www.w3.org/2000/svg">
    <defs><linearGradient id="shade" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0.15" stop-color="#11172b" stop-opacity="0"/>
      <stop offset="0.55" stop-color="#11172b" stop-opacity="0.7"/>
      <stop offset="1" stop-color="#11172b" stop-opacity="0.97"/>
    </linearGradient></defs>
    <rect width="1200" height="630" fill="url(#shade)"/>
    <rect x="48" y="40" width="346" height="66" rx="16" fill="white" fill-opacity="0.96"/>
  </svg>`);
  return sharp(picture).composite([
    {input: shade, top: 0, left: 0},
    {input: logo, top: 51, left: 64},
    {input: brand.data, top: 61, left: 122},
    {input: heading.data, top: 525 - heading.info.height, left: 64},
    {input: address.data, top: 569, left: 66},
  ]).png().toBuffer();
}


async function renderScreenshotCard({title, route, mediaPath}, siteDir) {
  const screenshot = await sharp(mediaPath).resize(616, 526, {fit: 'inside'}).png().toBuffer({resolveWithObject: true});
  const heading = await textImage(title, {size: 56, weight: 'Bold', color: '#252938', width: 430, height: 280}, siteDir);
  const address = await textImage(route, {size: 20, color: '#606776', width: 440, height: 70}, siteDir);
  const brand = await textImage('Immich Memories', {size: 28, weight: 'Semi-Bold', color: '#4250af', width: 360, height: 50}, siteDir);
  const logo = await sharp(join(siteDir, 'static/img/logo.svg')).resize(46, 46).png().toBuffer();
  const panel = Buffer.from(`<svg width="1200" height="630" xmlns="http://www.w3.org/2000/svg">
    <rect x="528" y="32" width="640" height="566" rx="22" fill="#dfe2eb"/>
    <rect x="529" y="33" width="638" height="564" rx="21" fill="#fff"/>
  </svg>`);
  return sharp({create: {width: 1200, height: 630, channels: 3, background: '#f5f6fa'}}).composite([
    {input: panel, top: 0, left: 0},
    {input: screenshot.data, top: 52 + Math.floor((526 - screenshot.info.height) / 2), left: 540 + Math.floor((616 - screenshot.info.width) / 2)},
    {input: logo, top: 53, left: 48},
    {input: brand.data, top: 63, left: 108},
    {input: heading.data, top: 194, left: 50},
    {input: address.data, top: 526, left: 52},
  ]).png().toBuffer();
}
