import React, {type ReactNode, useEffect, useRef, useState} from 'react';
import Mermaid from '@theme-original/Mermaid';
import type {Props} from '@theme/Mermaid';
import {useColorMode} from '@docusaurus/theme-common';

export default function ReadableMermaid(props: Props): ReactNode {
  const {colorMode} = useColorMode();
  const figure = useRef<HTMLElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (!expanded) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setExpanded(false);
      if (event.key !== 'Tab') return;
      const items = figure.current?.querySelectorAll<HTMLElement>('button:not(:disabled), [tabindex="0"]');
      if (!items?.length) return;
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last.focus();}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first.focus();}
    };
    document.addEventListener('keydown', keydown);
    return () => {document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', keydown);};
  }, [expanded]);
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const measure = () => {
      const svg = element.querySelector('svg');
      if (svg?.viewBox.baseVal.width) svg.style.width = `${svg.viewBox.baseVal.width * zoom}px`;
      setOverflows(element.scrollWidth > element.clientWidth + 1);
    };
    const resize = new ResizeObserver(measure);
    const mutation = new MutationObserver(measure);
    resize.observe(element);
    mutation.observe(element, {childList: true, subtree: true});
    measure();
    return () => { resize.disconnect(); mutation.disconnect(); };
  }, [props.value, colorMode, zoom]);
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
    <figure ref={figure} className={`docs-diagram${expanded ? ' docs-diagram-expanded' : ''}`}
      role={expanded ? 'dialog' : undefined} aria-modal={expanded ? true : undefined}
      aria-label={expanded ? 'Expanded diagram' : undefined}>
      <div className="docs-diagram-tools" role="group" aria-label="Diagram size">
        <button type="button" aria-label="Zoom diagram out" disabled={zoom <= .75} onClick={() => setZoom(value => Math.max(.75, value - .25))}>−</button>
        <span aria-live="polite">{Math.round(zoom * 100)}%</span>
        <button type="button" aria-label="Zoom diagram in" disabled={zoom >= 2} onClick={() => setZoom(value => Math.min(2, value + .25))}>+</button>
        <button type="button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>
          {expanded ? 'Close expanded view' : 'Expand diagram'}
        </button>
      </div>
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
