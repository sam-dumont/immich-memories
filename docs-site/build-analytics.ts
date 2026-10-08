import type {Config} from '@docusaurus/types';

export function analyticsHeadTags(baseUrl: string, env: NodeJS.ProcessEnv = process.env): NonNullable<Config['headTags']> {
  const domain = env.DOCS_ANALYTICS_DOMAIN?.trim();
  const endpoint = env.DOCS_ANALYTICS_ENDPOINT?.trim();
  if (!domain && !endpoint) return [];
  if (!domain || !endpoint) {
    throw new Error('Set both DOCS_ANALYTICS_DOMAIN and DOCS_ANALYTICS_ENDPOINT, or leave both unset.');
  }
  return [{
    tagName: 'script',
    attributes: {
      defer: 'true',
      'data-domain': domain,
      'data-api': endpoint,
      src: `${baseUrl}js/app.js`,
    },
  }];
}
