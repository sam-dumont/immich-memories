import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {buildSetup, nativeInstallCommand} from './recipes.ts';
import {deploymentCommands} from '../InstallationFiles/downloads.ts';

const sources = JSON.parse(readFileSync(new URL('./sources.json', import.meta.url), 'utf8'));
const setup = {
  platform: 'synology', tier: 'basic', immichUrl: 'http://192.168.1.10:2283',
  apiKey: 'synthetic-fixture-key', gpuBox: '', readerUrl: '', readerModel: '',
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
  const compose = JSON.parse(result.files.find(file => file.name === 'docker-compose.yml').content);
  assert.deepEqual(compose.services['immich-memories'].ports, ['127.0.0.1:8080:8080']);
});

test('free NAS port reaches both generated private mapping and access commands', () => {
  const result = buildSetup({...setup, uiPort: 18081}, sources, '1.2.3');
  const compose = JSON.parse(result.files.find(file => file.name === 'docker-compose.yml').content);
  assert.deepEqual(compose.services['immich-memories'].ports, ['127.0.0.1:18081:8080']);
  assert.match(result.commands, /http:\/\/localhost:18081/);
  assert.match(result.accessCommands, /ssh -L 18081:localhost:18081/);
});

test('Kubernetes Secret preserves its generated private Settings key', () => {
  const result = buildSetup({...setup, platform: 'kubernetes', inline: false}, sources, '1.2.3');
  const secret = JSON.parse(result.files.find(file => file.name.endsWith('/secret.yaml')).content);
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
  const compose = JSON.parse(docker.files.find(file => file.name === 'docker-compose.yml').content);
  assert.deepEqual(Object.keys(compose.services), Object.keys(sources.base.services));
  assert.equal(compose.services['immich-memories'].environment.IMMICH_MEMORIES_DEPLOYMENT_TIER, 'basic');
  const mac = buildSetup({...basic, platform: 'mac'}, sources, '1.2.3');
  assert.equal(JSON.parse(mac.files[0].content).tier, 'basic');
  assert.doesNotMatch(mac.commands, /mlxcel/);
  const kube = buildSetup({...basic, platform: 'kubernetes', inline: false}, sources, '1.2.3');
  const kustomization = JSON.parse(kube.files.find(file => file.name.endsWith('kustomization.yaml')).content);
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
  const config = JSON.parse(result.files[0].content);
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
  const secret = JSON.parse(result.files.find(file => file.name.endsWith('/secret.yaml')).content);
  const kustomization = JSON.parse(result.files.find(file => file.name.endsWith('kustomization.yaml')).content);
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

test('native install command scopes prerelease to the pinned package, never the whole resolve', () => {
  const command = nativeInstallCommand('1.2.3', 'all');
  assert.match(command, /--prerelease if-necessary-or-explicit/);
  assert.doesNotMatch(command, /--prerelease allow/);
});
