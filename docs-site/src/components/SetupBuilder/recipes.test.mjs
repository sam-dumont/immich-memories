import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {API_KEY_PLACEHOLDER, buildSetup, looksInternal, nativeInstallCommand} from './recipes.ts';
import {toYaml} from './yaml.ts';
import {deploymentCommands} from '../InstallationFiles/downloads.ts';

const sources = JSON.parse(readFileSync(new URL('./sources.json', import.meta.url), 'utf8'));
const setup = {
  platform: 'synology', tier: 'basic', immichUrl: 'http://192.168.1.10:2283',
  gpuBox: '', readerUrl: '', readerModel: '',
  cuda: false, version: '1.2.3', inline: true, secretKey: 'a'.repeat(64),
};

for (const port of [0, -1, 65536, 8080.5, NaN]) {
  test(`reject UI host port ${port}`, () => {
    const result = buildSetup({...setup, uiPort: port}, sources, '1.2.3');
    assert.equal(result.error, 'UI host port must be a whole number from 1 to 65535.');
    assert.deepEqual(result.files, []);
  });
}

test('default port stays private', () => {
  const result = buildSetup(setup, sources, '1.2.3');
  const compose = (result.files.find(file => file.name === 'docker-compose.yml').data);
  assert.deepEqual(compose.services['immich-memories'].ports, ['127.0.0.1:8080:8080']);
});

test('free NAS port reaches both generated private mapping and access commands', () => {
  const result = buildSetup({...setup, uiPort: 18081}, sources, '1.2.3');
  const compose = (result.files.find(file => file.name === 'docker-compose.yml').data);
  assert.deepEqual(compose.services['immich-memories'].ports, ['127.0.0.1:18081:8080']);
  assert.match(result.commands, /http:\/\/localhost:18081/);
  assert.match(result.accessCommands, /ssh -L 18081:localhost:18081/);
});

test('Kubernetes Secret preserves its generated private Settings key', () => {
  const result = buildSetup({...setup, platform: 'kubernetes', inline: false}, sources, '1.2.3');
  const secret = (result.files.find(file => file.name.endsWith('/secret.yaml')).data);
  assert.equal(secret.stringData.IMMICH_MEMORIES_SECRET_KEY, setup.secretKey);
});

for (const secretKey of [undefined, 'short-key']) {
  test(`Kubernetes rejects an invalid Settings key: ${secretKey}`, () => {
    const result = buildSetup({...setup, platform: 'kubernetes', inline: false, secretKey}, sources, '1.2.3');
    assert.equal(result.error, 'Generate a private settings key before exporting Kubernetes setup files.');
    assert.deepEqual(result.files, []);
  });
}


test('Basic generates CPU-only files across Docker, Mac and Kubernetes', () => {
  const basic = {...setup, tier: 'basic'};
  const docker = buildSetup(basic, sources, '1.2.3');
  assert.equal(docker.error, null);
  const compose = (docker.files.find(file => file.name === 'docker-compose.yml').data);
  assert.deepEqual(Object.keys(compose.services), Object.keys(sources.base.services));
  assert.equal(compose.services['immich-memories'].environment.IMMICH_MEMORIES_DEPLOYMENT_TIER, 'basic');
  const mac = buildSetup({...basic, platform: 'mac'}, sources, '1.2.3');
  assert.equal(mac.files[0].data.tier, 'basic');
  assert.doesNotMatch(mac.commands, /mlxcel/);
  const kube = buildSetup({...basic, platform: 'kubernetes', inline: false}, sources, '1.2.3');
  const kustomization = (kube.files.find(file => file.name.endsWith('kustomization.yaml')).data);
  assert.ok(kustomization.resources.includes('../base'));
  assert.doesNotMatch(kube.commands, /tier-basic|tier-nas/);
});


test('vendored inputs pin the docs version and verify before extracting', () => {
  assert.equal(deploymentCommands('development'), '');
  const command = deploymentCommands('v1.0.0-rc.2');
  assert.match(command, /releases\/download\/v1\.0\.0-rc\.2/);
  assert.match(command, /BUNDLE=immich-memories-deploy-1\.0\.0-rc\.2\.tar\.gz/);
  assert.ok(command.indexOf('shasum -a 256 -c') < command.indexOf('tar -xzf'));
  assert.match(command, /test -s bundle\.sha256/);
  assert.match(command, /-C vendor\/immich-memories/);
  assert.doesNotMatch(command, /latest|git clone|docker build/);
});

test('Mac Basic leaves out the caption endpoint and does not move it', () => {
  const result = buildSetup({...setup, platform: 'mac', inline: false}, sources, '1.2.3');
  const config = result.files[0].data;
  assert.equal(config.advanced.editorial, undefined);
  assert.doesNotMatch(result.commands, /caption_base_url/);
});

test('generated Compose pins the docs build version like the release asset', () => {
  const result = buildSetup({...setup, platform: 'linux', tier: 'gpu', inline: false}, sources, '1.2.3');
  const compose = result.files.find(file => file.name === 'docker-compose.yml').content;
  assert.match(compose, /IMMICH_MEMORIES_VERSION:-1\.2\.3\}/);
  assert.doesNotMatch(compose, /:-latest/);
});

test('Mac only installs llama.cpp for the app-owned local reader', () => {
  const mac = {...setup, platform: 'mac', inline: false};
  assert.doesNotMatch(buildSetup(mac, sources, '1.2.3').commands, /llama\.cpp/);
  assert.doesNotMatch(buildSetup({...mac, tier: 'gpu'}, sources, '1.2.3').commands, /llama\.cpp/);
  assert.match(buildSetup({...mac, tier: 'full'}, sources, '1.2.3').commands, /llama\.cpp/);
  const remote = buildSetup({...mac, tier: 'full', readerUrl: 'http://reader.lan:8000/v1', readerModel: 'm'}, sources, '1.2.3');
  assert.doesNotMatch(remote.commands, /llama\.cpp/);
});

const mac = {...setup, platform: 'mac', inline: false};
const lines = text => text.split('\n');

test('Mac installs plain ffmpeg and checks zscale instead of forcing ffmpeg-full', () => {
  const {commands} = buildSetup(mac, sources, '1.2.3');
  assert.match(commands, /^brew install uv ffmpeg$/m);
  assert.match(commands, /grep zscale/);
  assert.doesNotMatch(commands, /^export PATH/m);
  assert.doesNotMatch(commands, /^brew install .*ffmpeg-full/m);
});

test('Mac sets umask 077 before the config is saved, and warns about config.yaml.bak', () => {
  const {commands} = buildSetup(mac, sources, '1.2.3');
  const rows = lines(commands);
  const umask = rows.indexOf('umask 077');
  assert.ok(umask >= 0 && umask < rows.findIndex(row => /Save the generated config\.yaml/.test(row)));
  assert.match(commands, /config\.yaml\.bak/);
  assert.match(commands, /rm ~\/\.immich-memories\/config\.yaml\.bak/);
});

test('Mac ui command honours the UI port field', () => {
  assert.match(buildSetup(mac, sources, '1.2.3').commands, /^immich-memories ui --host 127\.0\.0\.1 --port 8080$/m);
  assert.match(buildSetup({...mac, uiPort: 8081}, sources, '1.2.3').commands, /ui --host 127\.0\.0\.1 --port 8081$/m);
  assert.equal(buildSetup({...mac, uiPort: 0}, sources, '1.2.3').error, 'UI host port must be a whole number from 1 to 65535.');
});

const kube = {...setup, platform: 'kubernetes', inline: false};

test('Kubernetes namespace reaches both files and every -n', () => {
  const result = buildSetup({...kube, namespace: 'films'}, sources, '1.2.3');
  const secret = (result.files.find(file => file.name.endsWith('/secret.yaml')).data);
  const kustomization = (result.files.find(file => file.name.endsWith('kustomization.yaml')).data);
  assert.equal(secret.metadata.namespace, 'films');
  assert.equal(kustomization.namespace, 'films');
  const flags = [...result.commands.matchAll(/ -n (\S+)/g)].map(match => match[1]);
  assert.ok(flags.length >= 4);
  assert.deepEqual([...new Set(flags)], ['films']);
  assert.doesNotMatch(result.commands, /immich-memories uses|Change it in both/);
});

test('Kubernetes namespace defaults to immich-memories and must be a DNS label', () => {
  const result = buildSetup(kube, sources, '1.2.3');
  assert.match(result.commands, /-n immich-memories deploy/);
  for (const namespace of ['Bad_NS', '-x', 'a'.repeat(64)]) {
    assert.match(buildSetup({...kube, namespace}, sources, '1.2.3').error, /Namespace/);
  }
});

test('Kubernetes install list fetches models before the first film', () => {
  const rows = lines(buildSetup(kube, sources, '1.2.3').commands);
  const fetch = rows.findIndex(row => /immich-memories models fetch$/.test(row));
  assert.ok(fetch > rows.findIndex(row => /rollout status/.test(row)));
  assert.ok(fetch < rows.findIndex(row => /immich-memories preflight$/.test(row)));
});

const triggerToken = 'b'.repeat(64);

test('Kubernetes without automation has no trigger token and leaves the CronJobs off', () => {
  const result = buildSetup(kube, sources, '1.2.3');
  const secret = result.files.find(file => file.name.endsWith('/secret.yaml')).data;
  assert.equal(secret.stringData.IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN, undefined);
  assert.doesNotMatch(result.commands, /cronjobs\.yaml/);
});

test('Kubernetes automation puts the trigger token in the Secret and enables cronjobs.yaml before the apply', () => {
  const result = buildSetup({...kube, automation: true, triggerToken}, sources, '1.2.3');
  assert.equal(result.error, null);
  const secret = result.files.find(file => file.name.endsWith('/secret.yaml')).data;
  assert.equal(secret.stringData.IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN, triggerToken);
  const rows = lines(result.commands);
  const enable = rows.findIndex(row => /cronjobs\.yaml/.test(row) && /^sed /.test(row));
  assert.ok(enable > -1);
  assert.ok(enable < rows.findIndex(row => /^kubectl kustomize /.test(row)));
  assert.ok(enable < rows.findIndex(row => /^kubectl apply -k /.test(row)));
});

for (const bad of [undefined, 'short']) {
  test(`Kubernetes automation rejects a bad trigger token: ${bad}`, () => {
    const result = buildSetup({...kube, automation: true, triggerToken: bad}, sources, '1.2.3');
    assert.match(result.error, /trigger token/);
    assert.deepEqual(result.files, []);
  });
}

test('native install command scopes prerelease to the pinned package, never the whole resolve', () => {
  const command = nativeInstallCommand('1.2.3', 'all');
  assert.match(command, /--prerelease if-necessary-or-explicit/);
  assert.doesNotMatch(command, /--prerelease allow/);
});

const platforms = ['linux', 'synology', 'mac', 'kubernetes'];
const everyOutput = platforms.flatMap(platform => ['basic', 'gpu', 'full'].map(tier => buildSetup({
  ...setup, platform, tier, inline: false, readerUrl: tier === 'full' ? 'http://192.168.1.20:8000/v1' : '',
  readerModel: tier === 'full' ? 'gemma-4-E4B-it-Q4_0' : '',
}, sources, '1.2.3')));

test('every .yml/.yaml output is block YAML, not JSON', () => {
  for (const result of everyOutput) {
    assert.equal(result.error, null);
    for (const file of result.files.filter(file => /\.ya?ml$/.test(file.name))) {
      assert.doesNotMatch(file.content, /^\s*[{[]/, file.name);
      assert.doesNotMatch(file.content, /"[A-Za-z_-]+": /, file.name);
    }
  }
});

test('kustomize patches are YAML block scalars', () => {
  const kube = buildSetup({...setup, platform: 'kubernetes', inline: false}, sources, '1.2.3');
  const text = kube.files.find(file => file.name.endsWith('kustomization.yaml')).content;
  assert.match(text, /^ {4}patch: \|$/m);
  assert.match(text, /^ {6}- op: add$/m);
});

test('the placeholder stands in for the Immich API key everywhere and no input asks for it', () => {
  for (const result of everyOutput) {
    const text = result.files.map(file => file.content).join('\n');
    assert.ok(text.includes(API_KEY_PLACEHOLDER));
    assert.doesNotMatch(text, /synthetic|[a-f0-9]{32}.*IMMICH_API_KEY/);
    assert.match(result.commands, /Put your Immich API key in/);
  }
});

test('the emitter quotes everything YAML would read as another type', () => {
  const tricky = {
    ports: ['127.0.0.1:8080:8080'], flags: ['true', 'false', 'yes', 'no', 'null', 'on', '~', 'Y'],
    numbers: ['8080', '1.2', '0x1f', '1e3', '-1', '.5'], empty: '', colon: 'a: b', hash: 'a #b', trailing: 'a:',
    star: '*x', amp: '&x', bang: '!x', brace: '{x}', bracket: '[x]', dash: '- x', percent: '%x', at: '@x', quote: 'say "hi"',
    interp: '${IMMICH_MEMORIES_VERSION:-latest}', multi: 'a\nb', unicode: 'café', spaced: ' lead',
    real: [true, false, 8080, 1.5, null], emptyMap: {}, emptyList: [], 'needs: quote': 1, nested: [[1, 2], {a: [{b: 1}]}],
  };
  const text = toYaml(tricky);
  for (const line of ['  - "127.0.0.1:8080:8080"', '  - "true"', '  - "8080"', 'empty: ""', 'interp: "${IMMICH_MEMORIES_VERSION:-latest}"']) {
    assert.ok(text.includes(line), line);
  }
});

test('a reader URL gets the reader key placeholder and a step; no reader leaves it empty', () => {
  const withReader = buildSetup({...setup, inline: false, tier: 'full', readerUrl: 'http://r:8000/v1', readerModel: 'm'}, sources, '1.2.3');
  assert.match(withReader.files.find(file => file.name === '.env').content, /^READER_API_KEY=replace-with-your-reader-api-key$/m);
  assert.match(withReader.commands, /Put your reader's API key in \.env/);
  const none = buildSetup({...setup, inline: false, tier: 'basic'}, sources, '1.2.3');
  assert.match(none.files.find(file => file.name === '.env').content, /^IMMICH_API_KEY=/m);
  assert.doesNotMatch(none.commands, /reader's API key/);
});

test('an internal Immich address is flagged, a public one is not', () => {
  for (const url of ['http://immich.immich.svc.cluster.local:2283', 'http://immich-server:2283', 'http://host.docker.internal:2283']) {
    assert.equal(looksInternal(url), true, url);
  }
  for (const url of ['http://192.168.1.10:2283', 'https://photos.example.org', 'http://nas.local:2283', 'nonsense']) {
    assert.equal(looksInternal(url), false, url);
  }
});

test('the browser address reaches every platform without touching the server URL', () => {
  const withPublic = {...setup, immichUrl: 'http://immich-server:2283', immichPublicUrl: 'https://photos.example.org'};
  const compose = buildSetup({...withPublic, inline: false}, sources, '1.2.3');
  const env = compose.files.find(file => file.name === '.env').content;
  assert.match(env, /^IMMICH_URL='http:\/\/immich-server:2283'$/m);
  const environment = file => file.data.services['immich-memories'].environment;
  assert.equal(environment(compose.files.find(file => file.name === 'docker-compose.yml')).IMMICH_MEMORIES_IMMICH__PUBLIC_URL, 'https://photos.example.org');
  const without = buildSetup({...setup, inline: false}, sources, '1.2.3').files.find(file => file.name === 'docker-compose.yml');
  assert.equal('IMMICH_MEMORIES_IMMICH__PUBLIC_URL' in environment(without), false);
  const mac = buildSetup({...withPublic, platform: 'mac', inline: false}, sources, '1.2.3');
  assert.equal(mac.files.find(file => file.name === 'config.yaml').data.immich.public_url, 'https://photos.example.org');
  const k8s = buildSetup({...withPublic, platform: 'kubernetes', inline: false}, sources, '1.2.3');
  const secret = k8s.files.find(file => file.name.endsWith('/secret.yaml')).data;
  assert.equal(secret.stringData.IMMICH_MEMORIES_IMMICH__PUBLIC_URL, 'https://photos.example.org');
  assert.equal(secret.stringData.IMMICH_URL, 'http://immich-server:2283');
});

test('a malformed browser address is refused', () => {
  const result = buildSetup({...setup, immichPublicUrl: 'photos.example.org'}, sources, '1.2.3');
  assert.match(result.error, /browser address needs a complete URL/);
});
