import type {ReactNode} from 'react';
import OriginalSiteMetadata from '@theme-original/SiteMetadata';
import {PageMetadata} from '@docusaurus/theme-common';
import {useLocation} from '@docusaurus/router';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import {socialPreviewPath} from '../../social-preview';

export default function SiteMetadata(): ReactNode {
  const {pathname} = useLocation();
  const {siteConfig: {baseUrl}} = useDocusaurusContext();
  const image = socialPreviewPath(pathname, baseUrl);
  return (
    <>
      <OriginalSiteMetadata />
      <PageMetadata image={image}>
        <meta property="og:image:width" content="1200" />
        <meta property="og:image:height" content="630" />
        <meta property="og:image:type" content={image.endsWith('.jpg') ? 'image/jpeg' : 'image/png'} />
      </PageMetadata>
    </>
  );
}
