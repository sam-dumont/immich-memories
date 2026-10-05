import {useEffect, useState} from 'react';
import ThemedImage from '@theme/ThemedImage';
import useBaseUrl from '@docusaurus/useBaseUrl';
import {useColorMode} from '@docusaurus/theme-common';

interface Props {
  /** File stem under static/diagrams, made by docs-site/diagrams/figures. */
  name: string;
  /** The one thing the diagram says, shown above it and used as its alt text. */
  headline: string;
}

// A rendered diagram: its headline, the light or dark SVG, and a full-screen view on click.
export default function Diagram({name, headline}: Props) {
  const {colorMode} = useColorMode();
  const [open, setOpen] = useState(false);
  const sources = {
    light: useBaseUrl(`/diagrams/${name}.svg`),
    dark: useBaseUrl(`/diagrams/${name}-dark.svg`),
  };

  useEffect(() => {
    if (!open) return undefined;
    const close = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [open]);

  return (
    <figure className="docs-diagram">
      <figcaption className="docs-diagram__headline">{headline}</figcaption>
      <button
        type="button"
        className="docs-diagram__open"
        onClick={() => setOpen(true)}
        aria-label={`Enlarge the diagram: ${headline}`}>
        <ThemedImage alt={headline} sources={sources} loading="lazy" />
      </button>
      {open && (
        <div className="docs-diagram__overlay" role="dialog" aria-label={headline} onClick={() => setOpen(false)}>
          <img src={sources[colorMode]} alt={headline} />
        </div>
      )}
    </figure>
  );
}
