/** Match the port in published Compose assets; unreleased builds use the next default. */
export function composeHostPort(version: string): number {
  const release = /^v?(\d+)\.(\d+)\.(\d+)(?:-((?:rc|dev)\.\d+))?$/.exec(version);
  if (!release) return 22830;
  const [, major, minor, patch, prerelease] = release;
  const beforeFinal = Number(major) < 1
    || (major === '1' && minor === '0' && patch === '0' && Boolean(prerelease));
  return beforeFinal ? 8080 : 22830;
}
