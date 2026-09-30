import React, {type ReactNode, useEffect, useRef, useState} from 'react';
import Mermaid from '@theme-original/Mermaid';
import type {Props} from '@theme/Mermaid';
import {useColorMode} from '@docusaurus/theme-common';

export default function ReadableMermaid(props: Props): ReactNode {
  const {colorMode} = useColorMode();
  const viewport = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const measure = () => setOverflows(element.scrollWidth > element.clientWidth + 1);
    const resize = new ResizeObserver(measure);
    const mutation = new MutationObserver(measure);
    resize.observe(element);
    mutation.observe(element, {childList: true, subtree: true});
    measure();
    return () => { resize.disconnect(); mutation.disconnect(); };
  }, [props.value, colorMode]);
  const dark = colorMode === 'dark';
  const themeVariables = {
    fontFamily: 'Inter, sans-serif',
    fontSize: '16px',
    primaryColor: dark ? '#1c2845' : '#eef1fc',
    primaryTextColor: dark ? '#edf2ff' : '#172247',
    primaryBorderColor: dark ? '#7d9dec' : '#4250af',
    lineColor: dark ? '#a4b7e8' : '#59678e',
    secondaryColor: dark ? '#222222' : '#f6f6f4',
    secondaryTextColor: dark ? '#dbdbdb' : '#172247',
    tertiaryColor: dark ? '#222222' : '#ffffff',
    clusterBkg: dark ? '#222222' : '#f6f6f4',
    clusterBorder: dark ? '#555555' : '#d2d7e3',
    edgeLabelBackground: dark ? '#000000' : '#ffffff',
  };
  const value = `%%{init: ${JSON.stringify({theme: 'base', themeVariables})}}%%\n${props.value}`;
  return (
    <figure className="docs-diagram">
      {overflows && <figcaption className="docs-diagram-hint">
        Wide diagram: scroll sideways, or focus it and use the arrow keys.
      </figcaption>}
      <div ref={viewport} className="docs-diagram-viewport" role="region"
        aria-label={overflows ? 'Diagram, scroll horizontally to see all branches' : 'Diagram'}
        tabIndex={overflows ? 0 : undefined}>
        <Mermaid {...props} value={value} />
      </div>
    </figure>
  );
}
