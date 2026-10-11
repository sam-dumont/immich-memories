import {useEffect, type ReactNode} from 'react';
import NotFound from '@theme-original/NotFound';
import useBaseUrl from '@docusaurus/useBaseUrl';
import {track} from '@site/src/analytics/events';

// Plausible's documented 404 goal: one event per missing page, with the path that was asked for.
export default function NotFoundWithEvent(): ReactNode {
  const base = useBaseUrl('/');
  useEffect(() => {
    const path = window.location.pathname;
    track('404', {path: '/' + (path.startsWith(base) ? path.slice(base.length) : path.replace(/^\//, ''))});
  }, [base]);
  return <NotFound />;
}
