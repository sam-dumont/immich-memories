import {assetBase} from '../SetupBuilder/recipes.ts';

export function installationCommands(version: string): string {
  const released = /^v?\d+\.\d+\.\d+(?:-(?:rc|dev)\.\d+)?$/.test(version);
  if (!released) return '';
  const tag = version.replace(/^v/, '');
  const files = ['docker-compose.yml', 'example.env', 'docker-compose.gpu.yml', 'docker-compose.full.yml', 'docker-compose.cuda.yml', 'docker-compose.gpu-worker.yml', 'docker-compose.postgres.yml'];
  const acquire = ['mkdir -p immich-memories && cd immich-memories', ...files.map(file => `curl -fLO "${assetBase(version)}/${file}"`)];
  return [...acquire, 'cp example.env .env', `sed -i.bak 's/^IMMICH_MEMORIES_VERSION=.*/IMMICH_MEMORIES_VERSION=${tag}/' .env && rm .env.bak`].join('\n');
}


export function deploymentCommands(version: string): string {
  if (!/^v?\d+\.\d+\.\d+(?:-(?:rc|dev)\.\d+)?$/.test(version)) return '';
  const tag = version.replace(/^v/, '');
  return [
    'set -eu',
    `BUNDLE=immich-memories-deploy-${tag}.tar.gz`,
    `ASSETS=${assetBase(version)}`,
    'curl -fLO "$ASSETS/$BUNDLE"',
    'curl -fLO "$ASSETS/SHA256SUMS"',
    `awk -v bundle="$BUNDLE" '$2 == bundle {print}' SHA256SUMS > bundle.sha256`,
    'test -s bundle.sha256',
    'shasum -a 256 -c bundle.sha256',
    'mkdir -p vendor/immich-memories',
    'tar -xzf "$BUNDLE" -C vendor/immich-memories',
  ].join('\n');
}
