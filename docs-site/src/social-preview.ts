/** One image per route, rooted inside either the release or candidate site. */
export function socialPreviewPath(pathname: string, baseUrl: string): string {
  if (!pathname.startsWith(baseUrl)) throw new Error('Social preview route is outside the site');
  const route = pathname.slice(baseUrl.length).replace(/\/+$/, '') || 'index';
  return route === 'index' ? 'img/social-card.jpg' : `img/social/${route}.png`;
}
