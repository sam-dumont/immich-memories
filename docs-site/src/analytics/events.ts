// Custom conversion events for the docs tracker. Every call goes through window.plausible, which
// only exists when the build was given a tracker, so forks and local builds send nothing.
// Props carry page paths, tier names, command kinds and file names. Never typed text.

type Props = Record<string, string>;
type Tracker = (name: string, options?: {props: Props}) => void;
interface Elementish {
  closest(selector: string): Elementish | null;
  querySelector(selector: string): Elementish | null;
  getAttribute(name: string): string | null;
  textContent: string | null;
}
interface Win { plausible?: Tracker }
interface Doc { addEventListener(name: string, listener: (event: {target: unknown}) => void, capture?: boolean): void }

const TIERS = ['basic', 'gpu', 'full'];
const KINDS = ['curl', 'docker', 'uv', 'pip', 'kubectl', 'helm'];

export function track(name: string, props: Props, win: Win = window as Win): void {
  if (typeof win.plausible === 'function') win.plausible(name, {props});
}

export function commandKind(command: string): string {
  const line = command.split('\n').map(text => text.replace(/^\s*\$\s*/, '').trim())
    .find(text => text && !text.startsWith('#')) ?? '';
  const word = line.split(/\s+/)[0].toLowerCase();
  return KINDS.includes(word) ? word : 'other';
}

export function fileName(url: string): string {
  try { return new URL(url, 'https://docs.invalid').pathname.split('/').pop() || ''; } catch { return ''; }
}

export function installEvents({window: win, document: doc, baseUrl}: {window: Win & {location: {pathname: string}}; document: Doc; baseUrl: string}) {
  const send = (name: string, props: Props) => track(name, props, win);
  const page = () => {
    const path = win.location.pathname;
    return '/' + (path.startsWith(baseUrl) ? path.slice(baseUrl.length) : path.replace(/^\//, ''));
  };
  const selectedTier = (inside: Elementish) => {
    const container = inside.closest('.tabs-container');
    const label = container?.querySelector('[role="tab"][aria-selected="true"]')?.textContent?.trim().toLowerCase() ?? '';
    return TIERS.includes(label) ? label : 'none';
  };
  let counted = new WeakSet<object>();
  const paused = new WeakSet<object>();

  doc.addEventListener('click', event => {
    const target = event.target as Elementish | null;
    if (!target?.closest) return;
    const copy = target.closest('button[aria-label^="Copy"]');
    const block = copy?.closest('.theme-code-block');
    if (copy && block) {
      const tier = block.closest('[role="tabpanel"]') ? selectedTier(block) : 'none';
      send('Install Command Copied', {page: page(), tier, kind: commandKind(block.querySelector('pre code')?.textContent ?? '')});
      return;
    }
    const tab = target.closest('[role="tab"]');
    const label = tab?.textContent?.trim().toLowerCase() ?? '';
    if (tab && tab.closest('.tabs-container') && TIERS.includes(label) && tab.getAttribute('aria-selected') !== 'true') {
      send('Install Tier Selected', {tier: label});
    }
  }, true);

  // play and pause do not bubble, so listen while they travel down.
  doc.addEventListener('pause', event => { if (event.target) paused.add(event.target as object); }, true);
  doc.addEventListener('play', event => {
    const video = event.target as (Elementish & {currentSrc?: string}) | null;
    if (!video || counted.has(video)) return;
    // A video that started itself only counts once the visitor has paused and resumed it.
    if (video.getAttribute?.('data-autoplay') && !paused.has(video)) return;
    counted.add(video);
    const source = video.currentSrc || video.getAttribute('src') || video.querySelector('source')?.getAttribute('src') || '';
    send('Demo Played', {video: fileName(source)});
  }, true);

  return {track: send, newPage: () => { counted = new WeakSet(); }};
}
