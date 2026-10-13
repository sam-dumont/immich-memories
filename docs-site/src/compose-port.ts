/** Match the port in published Compose assets; unreleased builds use the next default. */
export function composeHostPort(version: string): number {
  const release = /^v?(\d+)\.(\d+)\.(\d+)(?:-((?:rc|dev)\.\d+))?$/.exec(version);
  if (!release) return 22830;
  const [, major, minor, patch, prerelease] = release;
  // Release candidates up to 1.0.0-rc.9 published their Compose files on 8080; rc.10 moved to 22830.
  const rc = /^rc\.(\d+)$/.exec(prerelease ?? '');
  const published8080 = Number(major) < 1
    || (major === '1' && minor === '0' && patch === '0' && Boolean(prerelease) && !(rc && Number(rc[1]) >= 10));
  return published8080 ? 8080 : 22830;
}
