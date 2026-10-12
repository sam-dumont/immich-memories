/**
 * Where a docs page's Markdown version lives: the page's path without its trailing slash, plus
 * `.md` (`/docs/run/nas/` → `/docs/run/nas.md`). The page URL with `.md` added is the address
 * a model guesses first, and it can't clash with the page's own index.html.
 */
export function markdownPath(permalink) {
  return `${permalink.replace(/\/$/, '')}.md`;
}
