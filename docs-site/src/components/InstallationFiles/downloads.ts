import {assetBase} from '../SetupBuilder/recipes.ts';

const repository = 'https://github.com/sam-dumont/immich-memories';
export function installationCommands(version: string): string {
  const released = /^v?\d+\.\d+\.\d+(?:-rc\.\d+)?$/.test(version);
  const tag = version.replace(/^v/, '');
  const files = ['docker-compose.yml', 'example.env', 'docker-compose.gpu.yml', 'docker-compose.full.yml', 'docker-compose.cuda.yml', 'docker-compose.gpu-worker.yml', 'docker-compose.postgres.yml'];
  const acquire = released
    ? ['mkdir -p immich-memories && cd immich-memories', ...files.map(file => `curl -fLO "${assetBase(version)}/${file}"`)]
    : [`git clone ${repository}.git immich-memories`, 'cd immich-memories', 'docker build -f docker/Dockerfile --build-arg APP_VERSION=0.0.0.dev0 -t ghcr.io/sam-dumont/immich-memories:development .'];
  return [...acquire, 'cp example.env .env', `printf '\nIMMICH_MEMORIES_VERSION=${released ? tag : 'development'}\n' >> .env`, 'mkdir -p output'].join('\n');
}
