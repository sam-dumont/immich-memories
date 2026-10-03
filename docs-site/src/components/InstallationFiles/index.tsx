import type {ReactNode} from 'react';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import CodeBlock from '@theme/CodeBlock';
import Link from '@docusaurus/Link';
import {installationCommands} from './downloads';

export default function InstallationFiles(): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  const version = String(siteConfig.customFields?.version || 'development');
  const released = /^v?\d+\.\d+\.\d+(?:-rc\.\d+)?$/.test(version);
  return <>
    <p>{released ? `Download the release assets and select ${version.replace(/^v/, '')} with one version variable.`
      : 'This preview builds the app from source. Release instructions download the published assets.'}</p>
    <CodeBlock language="bash" title={released ? 'Download installation files' : 'Build the development image'}>
      {installationCommands(version)}
    </CodeBlock>
    <p>The base file runs NAS. GPU adds <code>docker-compose.gpu.yml</code>; Full also adds <code>docker-compose.full.yml</code>.
      NVIDIA adds <code>docker-compose.cuda.yml</code>. Set <code>COMPOSE_FILE</code> in <code>.env</code> to select those files.
      For filled-in files, use the <Link to="/setup">setup builder</Link>.</p>
  </>;
}
