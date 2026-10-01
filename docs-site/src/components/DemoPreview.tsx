import type {ReactNode} from 'react';
import {useColorMode} from '@docusaurus/theme-common';
import useBaseUrl from '@docusaurus/useBaseUrl';
import ThemedImage from '@theme/ThemedImage';

export function DemoLink({children}: {children: ReactNode}) {
  const {colorMode} = useColorMode();
  const href = useBaseUrl(`/demo/${colorMode === 'dark' ? 'dark-demo' : 'demo'}.mp4`);
  return <a href={href}>{children}</a>;
}

export default function DemoPreview() {
  const animations = {
    light: useBaseUrl('/img/demo-hero.gif'),
    dark: useBaseUrl('/img/dark-demo-hero.gif'),
  };
  const stills = {
    light: useBaseUrl('/img/screenshots/memory-story.png'),
    dark: useBaseUrl('/img/screenshots/dark-memory-story.png'),
  };
  const alt = 'Choose a month, review its cut, and watch the finished film';
  return (
    <figure className="docs-screenshot docs-demo-preview">
      <DemoLink>
        <span className="docs-demo-motion"><ThemedImage sources={animations} alt={alt} width={720} height={405} fetchPriority="high" /></span>
        <span className="docs-demo-still"><ThemedImage sources={stills} alt={alt} width={1440} height={900} /></span>
      </DemoLink>
    </figure>
  );
}
