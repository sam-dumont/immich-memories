import type {ReactNode} from 'react';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import CodeBlock from '@theme/CodeBlock';

const repository = 'https://github.com/sam-dumont/immich-video-memory-generator';

export default function InstallationFiles(): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  const version = String(siteConfig.customFields?.version || 'development');
  const released = /^v?\d+\.\d+\.\d+(?:-rc\.\d+)?$/.test(version);
  const tag = version.startsWith('v') ? version : `v${version}`;
  const image = released
    ? `ghcr.io/sam-dumont/immich-video-memory-generator:${version.replace(/^v/, '')}`
    : 'immich-memories:development';
  const commands = released
    ? `mkdir immich-memories && cd immich-memories\nREF=${tag}\nBASE=https://raw.githubusercontent.com/sam-dumont/immich-video-memory-generator/$REF\ncurl -fLO "$BASE/docker-compose.yml" -fLO "$BASE/example.env"`
    : `git clone ${repository}.git immich-memories\ncd immich-memories\ndocker build -f docker/Dockerfile --build-arg APP_VERSION=0.0.0.dev0 -t ${image} .`;
  return <>
    <p>{released
      ? `These instructions install ${tag}. The files and image use the same release.`
      : <>This preview builds from source. The release docs pin these files and the image to the RC tag.</>}</p>
    <CodeBlock language="bash" title={released ? `Download ${tag}` : 'Build the development image'}>
      {`${commands}\ncp example.env .env\nmkdir -p output`}
    </CodeBlock>
    <p>Save this as <code>docker-compose.override.yml</code> beside the downloaded Compose file. It selects the matching image:</p>
    <CodeBlock language="yaml" title="docker-compose.override.yml">
      {`services:\n  immich-memories:\n    image: ${image}`}
    </CodeBlock>
  </>;
}
