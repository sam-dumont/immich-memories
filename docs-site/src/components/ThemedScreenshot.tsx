import ThemedImage from '@theme/ThemedImage';
import useMediaUrl from './useMediaUrl';
import {useColorMode} from '@docusaurus/theme-common';

interface Props {
  name: string;
  alt: string;
}

export default function ThemedScreenshot({name, alt}: Props) {
  const {colorMode} = useColorMode();
  const sources = {
    light: useMediaUrl(`/img/screenshots/${name}.png`),
    dark: useMediaUrl(`/img/screenshots/dark-${name}.png`),
  };
  return (
    <figure className="docs-screenshot">
      <a href={sources[colorMode]} aria-label={`Open full-size screenshot: ${alt}`} target="_blank" rel="noopener noreferrer">
        <ThemedImage alt={alt} sources={sources} loading="lazy" style={{cursor: 'zoom-in'}} />
      </a>
    </figure>
  );
}

export function Screenshot({src, alt}: {src: string; alt: string}) {
  const url = useMediaUrl(src);
  return (
    <figure className="docs-screenshot">
      <a href={url} aria-label={`Open full-size screenshot: ${alt}`} target="_blank" rel="noopener noreferrer">
        <img src={url} alt={alt} loading="lazy" style={{cursor: 'zoom-in'}} />
      </a>
    </figure>
  );
}
