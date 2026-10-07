import {useEffect, useRef, useState} from 'react';
import useBaseUrl from '@docusaurus/useBaseUrl';

export default function CliDemo() {
  const video = useRef<HTMLVideoElement>(null);
  const [reduced, setReduced] = useState(false);
  const src = useBaseUrl('/demo/cli-demo.mp4');
  const poster = useBaseUrl('/demo/cli-demo-poster.jpg');

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReduced(query.matches);
    if (!query.matches) void video.current?.play().catch(() => undefined);
  }, []);

  return (
    <video
      ref={video}
      muted
      loop
      playsInline
      controls={reduced}
      preload="metadata"
      poster={poster}
      width={1400}
      height={780}
      aria-label="A terminal: immich-memories generate cuts June 2024 into an 18-picture film, runs story lists the cut in order, and runs why explains one picture."
      style={{width: '100%', height: 'auto', display: 'block', borderRadius: 10, border: '1px solid var(--im-border)'}}
    >
      <source src={src} type="video/mp4" />
    </video>
  );
}
