import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';
import {redirects} from './redirects';
import {productTagline} from './src/product';

const docsVersion = process.env.DOCS_VERSION || 'development';
const releaseDocs = /^v?\d+\.\d+\.\d+$/.test(docsVersion);

const config: Config = {
  title: 'Immich Memories',
  tagline: productTagline,
  customFields: {version: docsVersion},
  favicon: 'img/favicon.png',

  future: {
    v4: true,
  },

  url: 'https://sam-dumont.github.io',
  baseUrl: '/immich-video-memory-generator/',

  organizationName: 'sam-dumont',
  projectName: 'immich-video-memory-generator',

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
            'https://github.com/sam-dumont/immich-video-memory-generator/tree/main/docs-site/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    mermaid: {
      theme: {light: 'neutral', dark: 'dark'},
      options: {
        flowchart: {useMaxWidth: false, curve: 'monotoneY', nodeSpacing: 28, rankSpacing: 36, padding: 16},
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
          href: `https://github.com/sam-dumont/immich-video-memory-generator/tree/${releaseDocs ? (docsVersion.startsWith('v') ? docsVersion : `v${docsVersion}`) : 'main'}`,
          label: releaseDocs ? `Docs ${docsVersion}` : 'Development docs',
          position: 'right',
        },
        {
          href: 'https://github.com/sam-dumont/immich-video-memory-generator',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {
              label: 'Quick start',
              to: '/docs/get-started/quick-start',
            },
            {
              label: 'Improve a film',
              to: '/docs/make/improve-a-film',
            },
          ],
        },
        {
          title: 'Community',
          items: [
            {
              label: 'GitHub Issues',
              href: 'https://github.com/sam-dumont/immich-video-memory-generator/issues',
            },
            {
              label: 'Immich',
              href: 'https://immich.app/',
            },
          ],
        },
        {
          title: 'Operate',
          items: [
            {
              label: 'Operate and configure',
              to: '/docs/run/overview',
            },
          ],
        },
      ],
      copyright: `Copyright © 2025-${new Date().getFullYear()} Immich Memories. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'yaml', 'toml', 'hcl', 'sql', 'diff', 'docker', 'ini', 'nginx'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
