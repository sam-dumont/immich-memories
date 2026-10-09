import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';
import {redirects} from './redirects';
import {productTagline} from './src/product';
import {resolveDocsVersion} from './build-version';
import {analyticsHeadTags} from './build-analytics';

const docsVersion = resolveDocsVersion();

const nextDocs = process.env.DOCS_NEXT === 'true';
const baseUrl = nextDocs ? '/immich-memories/next/' : '/immich-memories/';

const config: Config = {
  title: 'Immich Memories',
  tagline: productTagline,
  customFields: {version: docsVersion},
  favicon: 'img/favicon.png',
  trailingSlash: true,
  // Only the canonical root docs belong in search; /next duplicates the release.
  noIndex: nextDocs,

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

  plugins: [['@docusaurus/plugin-client-redirects', {redirects}]],

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

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
    ...(nextDocs ? {announcementBar: {
      id: 'release-candidate',
      content: `Docs ${docsVersion}. <a href="/immich-memories/">Read the current final release docs</a>.`,
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
