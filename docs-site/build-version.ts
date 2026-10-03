import {execFileSync} from 'node:child_process';

export const releaseVersion = /^v?\d+\.\d+\.\d+(?:-rc\.\d+)?$/;
const buildVersion = /^(?:v?\d+\.\d+\.\d+(?:-rc\.\d+)?(?:-\d+-g[0-9a-f]+)?(?:-dirty)?|development(?:-[0-9a-f]+(?:-dirty)?)?)$/;

export function resolveDocsVersion(env: NodeJS.ProcessEnv = process.env, cwd = process.cwd()): string {
  if (env.DOCS_VERSION) {
    if (!buildVersion.test(env.DOCS_VERSION)) throw new Error(`Invalid DOCS_VERSION: ${env.DOCS_VERSION}`);
    return env.DOCS_VERSION;
  }
  try {
    // Model artifact tags are independent of the application release version.
    const value = execFileSync('git', ['describe', '--tags', '--match', 'v[0-9]*.[0-9]*.[0-9]*', '--always', '--abbrev=12', '--dirty'], {cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore']}).trim();
    if (buildVersion.test(value)) return value;
    return /^[0-9a-f]+(?:-dirty)?$/.test(value) ? `development-${value}` : 'development';
  } catch {
    return 'development';
  }
}
