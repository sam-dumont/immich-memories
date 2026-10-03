import {assetBase} from '../SetupBuilder/recipes.ts';

export function installationCommands(version: string): string {
  const released = /^v?\d+\.\d+\.\d+(?:-rc\.\d+)?$/.test(version);
  if (!released) return '';
  const tag = version.replace(/^v/, '');
  const files = ['docker-compose.yml', 'example.env', 'docker-compose.gpu.yml', 'docker-compose.full.yml', 'docker-compose.cuda.yml', 'docker-compose.gpu-worker.yml', 'docker-compose.postgres.yml'];
  const acquire = ['mkdir -p immich-memories && cd immich-memories', ...files.map(file => `curl -fLO "${assetBase(version)}/${file}"`)];
  return [...acquire, 'cp example.env .env', `printf '\nIMMICH_MEMORIES_VERSION=${tag}\n' >> .env`, 'mkdir -p output'].join('\n');
}
