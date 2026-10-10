import {useEffect, useRef, type ReactNode} from 'react';
import {useColorMode} from '@docusaurus/theme-common';
import useBaseUrl from '@docusaurus/useBaseUrl';

export function DemoLink({children}: {children: ReactNode}) {
  const {colorMode} = useColorMode();
  const href = useBaseUrl(`/demo/${colorMode === 'dark' ? 'dark-demo' : 'demo'}.mp4`);
  return <a href={href}>{children}</a>;
}

export default function DemoPreview() {
  const video = useRef<HTMLVideoElement>(null);
  const {colorMode} = useColorMode();
  const name = colorMode === 'dark' ? 'dark-demo' : 'demo';
  const src = useBaseUrl(`/demo/${name}.mp4`);
  const poster = useBaseUrl(`/demo/${name}-poster.jpg`);
  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const applyPreference = () => {
      if (preference.matches) video.current?.pause();
      else void video.current?.play().catch(() => undefined);
    };
    applyPreference();
    preference.addEventListener('change', applyPreference);
    return () => preference.removeEventListener('change', applyPreference);
  }, [src]);
  return (
    <figure className="docs-screenshot docs-demo-preview">
      <video
        key={src}
        ref={video}
        src={src}
        poster={poster}
        controls
        muted
        playsInline
        preload="none"
        width={1920}
        height={1080}
        aria-label="Immich Memories demo: choose pictures, review and edit the cut, then watch the finished film"
        style={{width: '100%', height: 'auto', display: 'block', borderRadius: 10}}
      >
        <a href={src}>Watch the demo</a>
      </video>
    </figure>
  );
}
