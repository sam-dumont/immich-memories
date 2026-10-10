import type {ReactNode} from 'react';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import CodeBlock from '@theme/CodeBlock';
import Link from '@docusaurus/Link';
import {nativeInstallCommand, type Tier} from '../SetupBuilder/recipes';
import {installationCommands, deploymentCommands} from './downloads';

export default function InstallationFiles({kind = 'compose', tier = 'basic'}: {kind?: 'compose' | 'bundle' | 'native'; tier?: Tier}): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  const version = String(siteConfig.customFields?.version || 'development');
  const released = /^v?\d+\.\d+\.\d+(?:-(?:rc|dev)\.\d+)?$/.test(version);
  if (!released) return <aside className="alert alert--warning">
    <p><strong>Prebuilt installation for this preview is not published.</strong> This page
      describes development code. Its matching images, native package and setup downloads
      must be published before a first-run test can use it.</p>
    <p>Check the <a href="https://github.com/sam-dumont/immich-memories/releases">application releases</a>
      {' '}for an installable version and its matching documentation. Model-only releases are not app releases.
      For source builds, use <Link to="/docs/contribute/development-setup">contributor setup</Link>.</p>
    <p>Stop here if you need a prebuilt first installation; the remaining steps require those assets.</p>
  </aside>;
  if (kind === 'native') return <CodeBlock language="bash" title={`Install ${version}: choose your platform`}>
    {`# Linux / Intel Mac\n${nativeInstallCommand(version, 'all')}\n# Apple Silicon: use this instead\n${nativeInstallCommand(version, 'all-mac')}`}
  </CodeBlock>;
  if (kind === 'bundle') return <CodeBlock language="bash" title={`Vendor ${version}`}>
    {deploymentCommands(version)}
  </CodeBlock>;
  return <CodeBlock language="bash" title={`Download ${tier === 'basic' ? 'Basic' : tier === 'gpu' ? 'GPU' : 'Full'} installation files (${version})`}>
    {installationCommands(version, tier)}
  </CodeBlock>;
}
