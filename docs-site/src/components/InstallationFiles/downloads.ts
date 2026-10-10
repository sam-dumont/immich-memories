import {assetBase, type Tier} from '../SetupBuilder/recipes.ts';

export function installationCommands(version: string, tier: Tier = 'basic'): string {
  const released = /^v?\d+\.\d+\.\d+(?:-(?:rc|dev)\.\d+)?$/.test(version);
  if (!released) return '';
  const tag = version.replace(/^v/, '');
  const files = ['docker-compose.yml', 'example.env',
    ...(tier === 'basic' ? [] : ['docker-compose.gpu.yml', ...(tier === 'full' ? ['docker-compose.full.yml'] : []), 'docker-compose.cuda.yml'])];
  const acquire = ['mkdir -p immich-memories && cd immich-memories', ...files.map(file => `curl -fLO "${assetBase(version)}/${file}"`)];
  const select = tier === 'basic' ? [] : [
    `sed -i.bak 's/^TIER=.*/TIER=${tier}/' .env && rm .env.bak`,
    `echo 'COMPOSE_FILE=${files.filter(file => file.endsWith('.yml')).join(':')}' >> .env`,
  ];
  return [...acquire, 'cp example.env .env', `sed -i.bak 's/^IMMICH_MEMORIES_VERSION=.*/IMMICH_MEMORIES_VERSION=${tag}/' .env && rm .env.bak`, ...select].join('\n');
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

export function unraidCommands(version: string): string {
  if (!/^v?\d+\.\d+\.\d+(?:-(?:rc|dev)\.\d+)?$/.test(version)) return '';
  const tag = version.replace(/^v/, '');
  return [
    'mkdir -p /boot/config/plugins/dockerMan/templates-user',
    `curl --fail --location https://raw.githubusercontent.com/sam-dumont/immich-memories/v${tag}/deploy/unraid/immich-memories.xml -o /boot/config/plugins/dockerMan/templates-user/my-immich-memories.xml`,
  ].join('\n');
}
