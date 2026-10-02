export type Platform = 'linux' | 'synology' | 'mac' | 'kubernetes';
export type Tier = 'nas' | 'gpu' | 'full';
export interface Setup {
  platform: Platform;
  tier: Tier;
  immichUrl: string;
  apiKey: string;
  gpuBox: string;
  readerUrl: string;
  readerModel: string;
  readerApiKey?: string;
  cuda: boolean;
  version: string;
  uiPort?: number;
  inline?: boolean;
  secretKey?: string;
}
export interface Recipe {name: string; language: string; content: string}

const repository = 'https://github.com/sam-dumont/immich-video-memory-generator';
const quote = (value: string): string => `'${value.replace(/'/g, "'\\''")}'`;
const dotenv = (value: string): string => `'${value.replace(/'/g, "\\'")}'`;

function releaseVersion(version: string): string | null {
  return /^v?\d+\.\d+\.\d+(?:-rc\.\d+)?$/.test(version) ? version.replace(/^v/, '') : null;
}

export function assetBase(version: string): string {
  const release = releaseVersion(version);
  return release !== null
    ? `${repository}/releases/download/v${release}`
    : `${repository}/releases/latest/download`;
}

export function validateSetup(setup: Setup): string | null {
  if (['linux', 'synology'].includes(setup.platform) &&
      (!Number.isInteger(setup.uiPort ?? 8080) || (setup.uiPort ?? 8080) < 1 || (setup.uiPort ?? 8080) > 65535)) {
    return 'UI host port must be a whole number from 1 to 65535.';
  }
  if (setup.version === 'development') return 'Choose a published release version for these setup files.';
  if (!releaseVersion(setup.version) && setup.version !== 'latest') return 'Use a release version such as 1.0.0 or 1.0.0-rc.1.';
  if (setup.platform === 'kubernetes' && !releaseVersion(setup.version)) return 'Kubernetes needs a published release version to select its bundle.';
  for (const value of [setup.apiKey, setup.gpuBox, setup.readerModel, setup.immichUrl, setup.readerUrl, setup.readerApiKey || '']) {
    if (/[\r\n\0]/.test(value)) return 'Use one line for each setting.';
  }
  for (const [label, value] of [['Immich', setup.immichUrl], ['Reader', setup.readerUrl]]) {
    if (!value && label === 'Reader') continue;
    try {
      const url = new URL(value);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
        return `${label} needs an HTTP or HTTPS URL without embedded credentials.`;
      }
    } catch { return `${label} needs a complete URL.`; }
  }
  if (setup.gpuBox && ['mac', 'kubernetes'].includes(setup.platform)) return 'Remote GPU box setup is available for Docker Compose.';
  if (!setup.apiKey) return 'Enter your Immich API key.';
  if ((setup.inline || setup.platform === 'kubernetes') && !/^[a-f0-9]{64}$/.test(setup.secretKey || '')) {
    return setup.platform === 'kubernetes'
      ? 'Generate a private settings key before exporting Kubernetes setup files.'
      : 'Generate a private settings key before exporting a single-file stack.';
  }
  if (setup.gpuBox) {
    const raw = setup.gpuBox;
    const host = raw.includes(':') && !raw.includes('[') && raw.split(':').length > 2 ? `[${raw}]` : raw;
    try {
      const address = new URL(`http://${host}`);
      if (!address.hostname || address.username || address.password || address.pathname !== '/'
          || address.search || address.hash || raw.includes('/')) return 'GPU box needs a hostname or IP address, with an optional port.';
    } catch { return 'GPU box needs a hostname or IP address, with an optional port.'; }
  }
  if (setup.tier === 'full' && ((setup.platform !== 'mac' && !setup.readerUrl) || (setup.readerUrl && !setup.readerModel))) {
    return 'Full needs a reader URL and its served model name.';
  }
  return null;
}

type Mapping = {[key: string]: unknown};
export type Sources = {base: Mapping; gpu: Mapping; full: Mapping; cuda: Mapping; worker?: Mapping};
export interface Result {files: Recipe[]; commands: string; workerCommands?: string; accessCommands?: string; error: string | null}

function merge(base: Mapping, patch: Mapping): Mapping {
  const result = {...base};
  for (const [key, value] of Object.entries(patch)) {
    const previous = result[key];
    result[key] = value && previous && !Array.isArray(value) && !Array.isArray(previous)
      && typeof value === 'object' && typeof previous === 'object'
      ? merge(previous as Mapping, value as Mapping) : value;
  }
  return result;
}

// Resolve only Compose's template variables. Supplied dollars remain literal at launch.
function inlineValues(value: unknown, values: Record<string, string>): unknown {
  if (typeof value === 'string') return value.replace(/(?<!\$)\$\{([A-Z_]+)(?:(:-|:\?)([^}]*))?\}/g,
    (_match, name: string, operator: string, fallback: string) => {
      const supplied = values[name];
      const resolved = supplied || (operator === ':-' ? fallback : '');
      if (!resolved && operator === ':?') throw new Error(`Missing ${name}.`);
      return resolved.replace(/\$/g, '$$$$');
    });
  if (Array.isArray(value)) return value.map(item => inlineValues(item, values));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(
    ([key, item]) => [key, inlineValues(item, values)],
  ));
  return value;
}

function macRecipe(setup: Setup): Result {
  const full = setup.tier === 'full';
  const config: Mapping = {
    immich: {url: setup.immichUrl, api_key: setup.apiKey}, tier: setup.tier,
    advanced: {
      editorial: {preparation: {caption_base_url: setup.tier === 'nas' ? '' : 'http://127.0.0.1:8092/v1'}},
      llm: {enabled: full, base_url: setup.readerUrl, api_key: setup.readerApiKey || '', model: setup.readerModel || 'gemma-4-E4B-it-Q4_0'},
    },
  };
  const release = releaseVersion(setup.version);
  const pinned = release !== null;
  const version = release?.replace('-rc.', 'rc');
  const caption = setup.tier === 'nas' ? [] : [
    'brew install lablup/tap/mlxcel',
    'SNAPSHOT=$(uvx --from huggingface-hub hf download mlx-community/SmolVLM2-500M-Video-Instruct-mlx --revision fa57db46815177fbdfd65cc85a2b3416a8332268)',
    'mlxcel serve --model "$SNAPSHOT" --alias smolvlm2-500m-base-public --host 127.0.0.1 --port 8092 > captioner.log 2>&1 &',
  ];
  return {error: null, files: [{name: 'config.yaml', language: 'yaml', content: JSON.stringify(config, null, 2)}], commands: [
    'brew install uv ffmpeg-full llama.cpp',
    'export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"',
    `uv tool install ${pinned ? '--prerelease allow ' : ''}"immich-memories[all-mac]${pinned ? `==${version}` : ''}" --with laya-mlx`,
    'mkdir -p ~/.immich-memories',
    '# Save the generated config.yaml in ~/.immich-memories.',
    'umask 077',
    'test -f ~/.immich-memories/secret-key || openssl rand -hex 32 > ~/.immich-memories/secret-key',
    'export IMMICH_MEMORIES_SECRET_KEY="$(cat ~/.immich-memories/secret-key)"',
    ...caption,
    'immich-memories config move-to-db tier editorial.preparation.caption_base_url llm.enabled llm.base_url llm.model llm.api_key',
    'immich-memories models fetch',
    'immich-memories preflight',
    'immich-memories capabilities',
    'immich-memories ui --host 127.0.0.1',
  ].join('\n')};
}

export function buildSetup(setup: Setup, sources: Sources, buildVersion: string): Result {
  const version = releaseVersion(buildVersion);
  if (!version) return {files: [], commands: '', error: 'This docs build has no published release. Use release docs to export setup files.'};
  if (releaseVersion(setup.version) !== version) return {
    files: [], commands: '', error: `These setup files require the docs build version ${version}.`,
  };
  const error = validateSetup(setup);
  if (error) return {files: [], commands: '', error};
  if (setup.platform === 'mac') return macRecipe(setup);
  if (setup.platform === 'kubernetes') {
    const tag = releaseVersion(setup.version)!;
    const root = setup.tier === 'nas' ? 'base' : `overlays/tier-${setup.tier}`;
    const secret = {apiVersion: 'v1', kind: 'Secret', metadata: {
      name: 'immich-memories-secrets', namespace: 'immich-memories',
    }, type: 'Opaque', stringData: {IMMICH_URL: setup.immichUrl, IMMICH_API_KEY: setup.apiKey, IMMICH_MEMORIES_SECRET_KEY: setup.secretKey!, ...(setup.readerApiKey ? {IMMICH_MEMORIES_DEPLOYMENT_READER_API_KEY: setup.readerApiKey} : {})}};
    const ports = new Set<number>([Number(new URL(setup.immichUrl).port || (setup.immichUrl.startsWith('https:') ? 443 : 80))]);
    if (setup.tier === 'full') ports.add(Number(new URL(setup.readerUrl).port || (setup.readerUrl.startsWith('https:') ? 443 : 80)));
    const egress = {target: {kind: 'NetworkPolicy', name: 'immich-memories'}, patch: JSON.stringify([{
      op: 'add', path: '/spec/egress/-', value: {ports: [...ports].map(port => ({port, protocol: 'TCP'}))},
    }])};
    const files = [
      {name: 'deploy/kubernetes/custom/secret.yaml', language: 'yaml', content: JSON.stringify(secret, null, 2)},
      {name: 'deploy/kubernetes/custom/kustomization.yaml', language: 'yaml', content: JSON.stringify({
        apiVersion: 'kustomize.config.k8s.io/v1beta1', kind: 'Kustomization', namespace: 'immich-memories',
        resources: [`../${root}`, 'secret.yaml'], patches: [egress],
      }, null, 2)},
    ];
    if (setup.tier === 'full') files.push({
      name: 'deploy/kubernetes/overlays/tier-full/reader-config.yaml', language: 'yaml', content: JSON.stringify({
        apiVersion: 'v1', kind: 'ConfigMap', metadata: {name: 'immich-memories-reader'},
        data: {url: setup.readerUrl, model: setup.readerModel},
      }, null, 2),
    });
    return {files, error: null, commands: [
      `curl -fLO ${quote(`${repository}/releases/download/v${tag}/immich-memories-deploy-${tag}.tar.gz`)}`,
      `tar -xzf ${quote(`immich-memories-deploy-${tag}.tar.gz`)}`,
      'mkdir -p deploy/kubernetes/custom',
      '# Save the generated files at their labelled paths.',
      '# Before applying: choose local/block storage for immich-memories-cache (SQLite).',
      '# NFS/SMB app-data storage is refused at startup; use PostgreSQL for a network database.',
      '# Storage choices: https://sam-dumont.github.io/immich-video-memory-generator/docs/run/kubernetes#prerequisites',
      `kubectl kustomize deploy/kubernetes/custom`,
      'kubectl apply -k deploy/kubernetes/custom',
      'kubectl rollout status -n immich-memories deploy/immich-memories',
      'kubectl exec -n immich-memories deploy/immich-memories -- immich-memories preflight',
      'kubectl exec -n immich-memories deploy/immich-memories -- immich-memories capabilities',
      '# Keep this private forwarding command running in this terminal.',
      'kubectl port-forward -n immich-memories svc/immich-memories 8080:80',
      '# Open http://localhost:8080 in your browser and start your first monthly cut.',
    ].join('\n')};
  }
  const uiPort = setup.uiPort ?? 8080;
  let compose = sources.base;
  if (setup.tier !== 'nas' && !setup.gpuBox) compose = merge(compose, sources.gpu);
  if (setup.tier === 'full') compose = merge(compose, sources.full);
  if (setup.cuda && !setup.gpuBox && setup.tier !== 'nas') compose = merge(compose, sources.cuda);
  // The single generated file starts all the services selected by this form.
  const services = compose.services as Mapping;
  compose = {...compose, services: Object.fromEntries(Object.entries(services).map(([key, value]) => {
    const service = {...value as Mapping};
    delete service.profiles;
    if (key === 'immich-memories' && Array.isArray(service.ports)) {
      service.ports = service.ports.map(port => typeof port === 'string'
        ? port.replace(/:8080:8080$/, `:${uiPort}:8080`) : port);
    }
    return [key, service];
  }))};
  const env = [
    `IMMICH_MEMORIES_VERSION=${releaseVersion(setup.version) || 'latest'}`,
    `TIER=${setup.tier}`,
    `IMMICH_URL=${dotenv(setup.immichUrl)}`, `IMMICH_API_KEY=${dotenv(setup.apiKey)}`,
    ...(setup.gpuBox ? [`GPU_BOX=${dotenv(setup.gpuBox)}`] : []),
    ...(setup.tier === 'full' ? [
      'READER_ENABLED=true', `READER_URL=${dotenv(setup.readerUrl)}`,
      `READER_MODEL=${dotenv(setup.readerModel)}`,
      `READER_API_KEY=${dotenv(setup.readerApiKey || '')}`,
    ] : []),
  ];
  if (setup.inline) {
    const app = compose.services as Mapping;
    const service = app['immich-memories'] as Mapping;
    compose = {...compose, volumes: {...compose.volumes as Mapping, 'immich-memories-output': {}},
      services: {...app, 'immich-memories': {...service, volumes: (service.volumes as string[]).map(
        volume => volume === './output:/app/output' ? 'immich-memories-output:/app/output' : volume,
      )}}};
    compose = inlineValues(compose, {
      IMMICH_MEMORIES_VERSION: releaseVersion(setup.version) || 'latest', TIER: setup.tier,
      IMMICH_URL: setup.immichUrl, IMMICH_API_KEY: setup.apiKey, GPU_BOX: setup.gpuBox,
      READER_ENABLED: setup.tier === 'full' ? 'true' : 'false', READER_URL: setup.readerUrl,
      READER_MODEL: setup.readerModel, READER_API_KEY: setup.readerApiKey || '',
      IMMICH_MEMORIES_SECRET_KEY: setup.secretKey!,
    }) as Mapping;
  }
  const workerFiles: Recipe[] = [];
  const workerCommands: string[] = [];
  if (setup.gpuBox && sources.worker) {
    const host = setup.gpuBox.split(':').length > 2 && !setup.gpuBox.startsWith('[') ? `[${setup.gpuBox}]` : setup.gpuBox;
    const port = new URL(`http://${host}`).port || '8092';
    const workerServices = sources.worker.services as Mapping;
    const worker = {...sources.worker, services: {...workerServices, 'gpu-worker': {
      ...workerServices['gpu-worker'] as Mapping,
      ports: [`${'${GPU_WORKER_BIND_ADDRESS:-127.0.0.1}'}:${port}:8092`],
    }}};
    workerFiles.push({name: 'gpu-worker/docker-compose.yml', language: 'yaml', content: JSON.stringify(worker, null, 2)},
      {name: 'gpu-worker/.env', language: 'dotenv', content: [
        `IMMICH_MEMORIES_VERSION=${releaseVersion(setup.version) || 'latest'}`,
        `IMMICH_URL=${dotenv(setup.immichUrl)}`, 'GPU_WORKER_BIND_ADDRESS=0.0.0.0',
      ].join('\n')});
    workerCommands.push('', '# On the NVIDIA GPU box: save gpu-worker files in their own directory.',
      '# Permit this port only from your app host on the private network; model routes are unauthenticated.',
      'cd gpu-worker', `printf 'RENDER_WORKER_TOKEN=%s\\n' "$(openssl rand -hex 32)" >> .env`,
      'docker compose up -d',
      '# Optional render offload: set render.worker_base_url and render.worker_token in app Settings.',
      '# Use this same private worker address and the token in gpu-worker/.env. Offload is not enabled by this recipe.');
  }
  return {error: null, files: [
    {name: 'docker-compose.yml', language: 'yaml', content: JSON.stringify(compose, null, 2)},
    ...(!setup.inline ? [{name: '.env', language: 'dotenv', content: env.join('\n')}] : []),
    ...workerFiles,
  ], workerCommands: workerCommands.join('\n'), accessCommands: [
    '# From your computer, when the app runs on a headless host:',
    `ssh -L ${uiPort}:localhost:${uiPort} your-ssh-user@your-host`,
    `# Open http://localhost:${uiPort} in your browser.`,
  ].join('\n'), commands: [
    '# On the app host:',
    'mkdir -p immich-memories/output && cd immich-memories',
    ...(setup.inline ? ['# Save docker-compose.yml here, or paste it into your stack editor.'] : [
      '# Save the two generated files here, then create your private settings key.',
      `printf 'IMMICH_MEMORIES_SECRET_KEY=%s\\n' "$(openssl rand -hex 32)" >> .env`,
    ]),
    'docker compose up -d',
    'docker compose exec immich-memories immich-memories models fetch',
    'docker compose exec immich-memories immich-memories preflight',
    'docker compose exec immich-memories immich-memories capabilities',
    `# Open http://localhost:${uiPort} in your browser.`,
  ].join('\n')};
}
