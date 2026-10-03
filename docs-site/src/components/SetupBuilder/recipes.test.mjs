import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {buildSetup} from './recipes.ts';

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
