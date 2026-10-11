// Which docs track a build is, and where it lives on the site. Stable is the
// root; release candidates live under /next/ and the nightly build of main under
// /dev/. DOCS_NEXT is the older switch that release tags cut before DOCS_TRACK
// still read, so it keeps working.
const tracks = ['stable', 'next', 'dev'];

/** @param {Record<string, string | undefined>} env */
export function docsTrack(env = process.env) {
  const track = env.DOCS_TRACK || (env.DOCS_NEXT === 'true' ? 'next' : 'stable');
  if (!tracks.includes(track)) throw new Error(`Invalid DOCS_TRACK: ${track}`);
  return track;
}

/** The path of a track under /immich-memories/, with a trailing slash; empty for stable. */
export function trackPath(track) {
  return track === 'stable' ? '' : `${track}/`;
}
