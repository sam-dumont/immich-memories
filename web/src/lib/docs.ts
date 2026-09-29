// The published user docs; a page links its own section rather than repeating it.
const DOCS = 'https://sam-dumont.github.io/immich-video-memory-generator/docs/';

/** The docs page at `path` (as under docs-site/docs, without the extension). */
export const docsPage = (path: string) => `${DOCS}${path}`;
