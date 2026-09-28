import React, {type ReactNode} from 'react';
import Mermaid from '@theme-original/Mermaid';
import type {Props} from '@theme/Mermaid';

export default function ReadableMermaid(props: Props): ReactNode {
  return (
    <figure className="docs-diagram">
      <figcaption className="docs-diagram-hint">
        Swipe sideways, or focus the diagram and use the arrow keys, to see more.
      </figcaption>
      <div
        className="docs-diagram-viewport"
        role="region"
        aria-label="Diagram, scroll horizontally to see all branches"
        tabIndex={0}>
        <Mermaid {...props} />
      </div>
    </figure>
  );
}
