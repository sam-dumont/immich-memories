import {readFileSync} from 'node:fs';
import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';
import {redirects} from './redirects';
import {productTagline} from './src/product';
import {resolveDocsVersion} from './build-version';
import {analyticsHeadTags} from './build-analytics';
import {docsTrack, trackPath} from './scripts/docs-track.mjs';

const docsVersion = resolveDocsVersion();

const track = docsTrack();
const stableBaseUrl = '/immich-memories/';
const baseUrl = `${stableBaseUrl}${trackPath(track)}`;
// Static media with the same bytes as the stable ref's, listed by
// scripts/docs_shared_media.py; useMediaUrl links those from the stable tree.
const sharedMedia: string[] = track !== 'stable' && process.env.DOCS_SHARED_MEDIA_FILE
  ? JSON.parse(readFileSync(process.env.DOCS_SHARED_MEDIA_FILE, 'utf8'))
  : [];

// The release candidate and development tracks say which docs they are, and link back.
const trackBanner = {
  next: `Docs ${docsVersion}. <a href="/immich-memories/">Read the current final release docs</a>.`,
  dev: `Development docs, built from <code>main</code> (${docsVersion}). Features here may not be released yet. <a href="/immich-memories/">Read the stable docs</a>.`,
}[track];

const config: Config = {
  title: 'Immich Memories',
  tagline: productTagline,
  customFields: {version: docsVersion, sharedMedia, stableBaseUrl},
  favicon: 'img/favicon.png',
  trailingSlash: true,
  // Only the canonical root docs belong in search; /next and /dev duplicate them.
  noIndex: track !== 'stable',

  future: {
    // Keep the opted-in 3.9 behavior; future releases can add new v4 defaults.
    v4: {
      removeLegacyPostBuildHeadAttribute: true,
      useCssCascadeLayers: true,
    },
  },

  url: 'https://sam-dumont.github.io',
  baseUrl,

  organizationName: 'sam-dumont',
  projectName: 'immich-memories',

  // The docs serve their own pinned tracker; only events go through the collector proxy.
  // Use normal History API tracking for Docusaurus routes, not the blog's hash variant.
  // The installed app sends no analytics (see the Privacy page).
  headTags: analyticsHeadTags(baseUrl),

  onBrokenLinks: 'throw',
  onBrokenAnchors: 'throw',
  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },

  themes: ['@docusaurus/theme-mermaid'],

  // llms.txt: a map for coding agents and chat models, with links into this track.
  plugins: [['@docusaurus/plugin-client-redirects', {redirects}], './plugins/llms-txt.mjs'],

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  clientModules: ['./src/analytics-events.ts'],

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl:
            'https://github.com/sam-dumont/immich-memories/tree/main/docs-site/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    metadata: [
      {name: 'application-version', content: docsVersion},
      ...(process.env.GOOGLE_SITE_VERIFICATION
        ? [{name: 'google-site-verification', content: process.env.GOOGLE_SITE_VERIFICATION}]
        : []),
    ],
    ...(trackBanner ? {announcementBar: {
      id: track === 'next' ? 'release-candidate' : 'development',
      content: trackBanner,
      isCloseable: false,
    }} : {}),
    mermaid: {
      theme: {light: 'neutral', dark: 'dark'},
      options: {
        flowchart: {useMaxWidth: false, curve: 'monotoneY', nodeSpacing: 28, rankSpacing: 36, padding: 16, subGraphTitleMargin: {top: 6, bottom: 14}},
      },
    },
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Immich Memories',
      logo: {
        alt: 'Immich Memories',
        src: 'img/logo.svg',
        width: 32,
        height: 32,
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Start here',
        },
        {
          type: 'html',
          position: 'right',
          value: `<span class="navbar__item">Docs ${docsVersion}</span>`,
        },
        {
          href: 'https://github.com/sam-dumont/immich-memories',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      // Light follows the page theme; the dark style is a black band in both.
      style: 'light',
      links: [
        {label: 'Quick start', to: '/docs/get-started/quick-start'},
        {label: 'Improve a film', to: '/docs/make/improve-a-film'},
        {label: 'How this was built', to: '/docs/welcome/how-this-was-built'},
        {label: 'Privacy', to: '/privacy'},
        // This track's llms.txt, written at build time; pathname:// adds the base URL without routing.
        {label: 'AI documentation index', to: 'pathname:///llms.txt'},
        {label: 'GitHub', href: 'https://github.com/sam-dumont/immich-memories'},
        {label: 'Immich', href: 'https://immich.app/'},
      ],
      copyright: `Copyright © 2025-${new Date().getFullYear()} Immich Memories · ${docsVersion}`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'yaml', 'toml', 'hcl', 'sql', 'diff', 'docker', 'ini', 'nginx'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
