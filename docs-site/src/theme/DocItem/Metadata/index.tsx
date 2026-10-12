import type {ReactNode} from 'react';
import Head from '@docusaurus/Head';
import OriginalMetadata from '@theme-original/DocItem/Metadata';
import {useDoc} from '@docusaurus/plugin-content-docs/client';
import {markdownPath} from '../../../../plugins/markdown-path.mjs';

// Every docs page has a Markdown version next to it, built by plugins/llms-txt.mjs.
export default function Metadata(): ReactNode {
  const {metadata} = useDoc();
  return (
    <>
      <OriginalMetadata />
      <Head>
        <link rel="alternate" type="text/markdown" href={markdownPath(metadata.permalink)} />
      </Head>
    </>
  );
}
