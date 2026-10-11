import type {ReactNode} from 'react';
import useMediaUrl from './useMediaUrl';

// A plain anchor on purpose: with `trailingSlash: true`, Docusaurus's Link appends "/" to a
// downloadable file's URL and the file 404s.
export default function StaticFile({href, children}: {href: string; children: ReactNode}) {
  return <a href={useMediaUrl(href)}>{children}</a>;
}
