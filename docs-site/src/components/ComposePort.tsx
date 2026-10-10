import type {ReactNode} from 'react';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import {composeHostPort} from '../compose-port';

export default function ComposePort({host, link = false}: {host?: string; link?: boolean} = {}): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  const port = composeHostPort(String(siteConfig.customFields?.version || 'development'));
  const text = host ? `http://${host}:${port}` : String(port);
  return host && link ? <a href={text}>{text}</a> : text;
}
