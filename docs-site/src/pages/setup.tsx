import type {ReactNode} from 'react';
import Layout from '@theme/Layout';
import SetupBuilder from '@site/src/components/SetupBuilder';

export default function Setup(): ReactNode {
  return <Layout title="Setup builder" description="Generate the files and commands for your Immich Memories setup.">
    <main className="container margin-vert--lg" style={{maxWidth: '64rem'}}>
      <h1>Build your setup</h1>
      <p>Choose your platform and tier, save the generated files, then follow their install commands. Basic, GPU and Full each lead to the same first-film walkthrough.</p>
      <SetupBuilder />
    </main>
  </Layout>;
}
