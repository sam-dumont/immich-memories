import useBaseUrl from '@docusaurus/useBaseUrl';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';

// Media under static/ that this build shares with the stable docs (same bytes)
// is linked from the stable tree, so /next/ and /dev/ don't carry their own copy.
// Everything else resolves under this build's base, as useBaseUrl does.
export default function useMediaUrl(path: string): string {
  const {siteConfig} = useDocusaurusContext();
  const local = useBaseUrl(path);
  const {sharedMedia = [], stableBaseUrl = '/'} = siteConfig.customFields as {sharedMedia?: string[]; stableBaseUrl?: string};
  const key = path.replace(/^\//, '');
  return key && sharedMedia.includes(key) ? `${stableBaseUrl}${key}` : local;
}
