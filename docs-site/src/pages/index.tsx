import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import useBaseUrl from '@docusaurus/useBaseUrl';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';
import styles from './index.module.css';

function HeroSection() {
  return (
    <header className={styles.hero}>
      <div className="container">
        <div className={styles.heroInner}>
          <div className={styles.heroText}>
            <Heading as="h1" className={styles.heroTitle}>
              Your Immich library,<br />turned into video memories
            </Heading>
            <p className={styles.heroSubtitle}>
              Pick a month, a year, a trip or a person. It finds the stories in that
              period, keeps the pictures and videos that tell them in the order they were
              taken, and renders the film with titles, maps and music.
            </p>
            <p className={styles.heroSubtitle}>
              <strong>One container next to Immich is enough.</strong> A GPU adds
              captions and speed when you have one, and a model on top of it polishes the cut.
            </p>
            <div className={styles.heroCtas}>
              <Link className={styles.ctaPrimary} to="/docs/get-started/quick-start">
                Quick start
              </Link>
              <Link className={styles.ctaSecondary} to="/docs/">
                What it does
              </Link>
            </div>
          </div>
          <div className={styles.heroVisual}>
            <a href={useBaseUrl('/demo/demo.mp4')} aria-label="Play the demo with music">
              <picture>
                <source
                  media="(prefers-reduced-motion: reduce)"
                  srcSet={useBaseUrl('/img/screenshots/memory-story.png')}
                />
                <img
                  className={styles.heroScreenshot}
                  src={useBaseUrl('/img/demo-hero.gif')}
                  alt="Choose a memory, review and change its cut, and watch the finished film"
                  width="720"
                  height="405"
                  fetchPriority="high"
                />
              </picture>
            </a>
            <p className={styles.heroCredit}>
              <a href={useBaseUrl('/demo/demo.mp4')}>Play the demo with music</a>
              {' · '}
              <a href={useBaseUrl('/demo/trip-preview.mp4')}>Watch a finished trip film</a>
              . CC0 stock pictures from StockSnap and Wikimedia Commons,{' '}
              <a href="https://github.com/sam-dumont/immich-video-memory-generator/blob/main/tests/e2e/fixtures/library/CREDITS.md">
                credited with their authors
              </a>
              .
            </p>
          </div>
        </div>
      </div>
    </header>
  );
}

function QuickstartSection() {
  return (
    <section className={styles.quickstart}>
      <div className="container">
        <Heading as="h2" className={styles.sectionTitle}>
          Up in five minutes
        </Heading>
        <div className={styles.quickstartGrid}>
          <div className={styles.quickstartCode}>
            <div className={styles.codeBlock}>
              <div className={styles.codeHeader}>
                <span className={styles.codeDot} style={{background: '#ff5f57'}} />
                <span className={styles.codeDot} style={{background: '#febc2e'}} />
                <span className={styles.codeDot} style={{background: '#28c840'}} />
                <span className={styles.codeLabel}>terminal</span>
              </div>
              <pre className={styles.codeContent}>
{`mkdir -p immich-memories/output && cd immich-memories
BASE=https://raw.githubusercontent.com/sam-dumont/immich-video-memory-generator/main
curl -O $BASE/docker-compose.yml -O $BASE/example.env
cp example.env .env   # set IMMICH_URL and IMMICH_API_KEY
docker compose up -d

# the small CPU classifiers, about 140 MB, once
docker compose exec immich-memories \\
  immich-memories models fetch

# then open http://localhost:8080`}
              </pre>
            </div>
            <p className={styles.quickstartAlt}>
              Docker with Compose v2, Immich v2 or v3, 4 GB of RAM. The{' '}
              <Link to="/docs/get-started/quick-start">Quick start</Link> walks it step by step,
              and <Link to="/docs/run/uv-pip">pip / uv</Link> works without Docker.
            </p>
          </div>
          <div className={styles.quickstartSteps}>
            <p className={styles.quickstartAlt} style={{marginTop: 0}}>
              Once it is up, every memory is the same four moves:
            </p>
            <div className={styles.step}>
              <span className={styles.stepNumber}>1</span>
              <div>
                <strong>Brief</strong>
                <p>Pick a memory type and its month, year, trip or person</p>
              </div>
            </div>
            <div className={styles.step}>
              <span className={styles.stepNumber}>2</span>
              <div>
                <strong>Cut</strong>
                <p>It finds the stories in the period and gives each its share</p>
              </div>
            </div>
            <div className={styles.step}>
              <span className={styles.stepNumber}>3</span>
              <div>
                <strong>Review</strong>
                <p>See every shot before it renders; remove, trim or swap what you disagree with</p>
              </div>
            </div>
            <div className={styles.step}>
              <span className={styles.stepNumber}>4</span>
              <div>
                <strong>Render</strong>
                <p>The reviewed cut, with titles, maps and music, into a folder or back into Immich</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

type ShowcaseItem = {
  title: string;
  description: string;
  image: string;
  alt: string;
};

const showcaseItems: ShowcaseItem[] = [
  {
    title: 'Ten memory types',
    description: 'A month, a season, a year in review, a trip with its map, a holiday across the years, one person or several, on this day, an album, and a special day your library flagged on its own. Or pick the dates yourself.',
    image: '/img/screenshots/memory-brief.png',
    alt: 'The brief: memory type, month, and the command it runs',
  },
  {
    title: 'See the cut before it renders',
    description: 'The whole film as a contact sheet, in the order it plays. Open a picture to read why it stayed. The stories keep the order they happened in, and a week at home with nothing in it stays short instead of filled with guesses.',
    image: '/img/screenshots/memory-story.png',
    alt: 'The cut contact sheet and the picture inspector',
  },
  {
    title: 'Change what you disagree with',
    description: 'Remove a shot, trim a video, or swap a picture for another one of the same moment. Save it as a revision and render that. Nothing gets chosen again behind your back.',
    image: '/img/screenshots/memory-review-edit.png',
    alt: 'A picture swapped and one removed, with the change bar',
  },
  {
    title: 'Titles, maps and music',
    description: 'Animated title cards, month dividers, and for a trip a satellite fly-over from home to where you went. Your own music or one of 28 bundled tracks, picked by mood and ducked under the clips\' own sound.',
    image: '/img/trip-map-flyover.jpg',
    alt: 'The opening map of a trip film: a week by a lake, June 2024',
  },
];

function ShowcaseSection() {
  return (
    <section className={styles.showcase}>
      <div className="container">
        <Heading as="h2" className={styles.sectionTitle}>
          What it actually does
        </Heading>
        <div className={styles.showcaseGrid}>
          {showcaseItems.map((item, idx) => (
            <div key={idx} className={styles.showcaseCard}>
              <img
                src={useBaseUrl(item.image)}
                alt={item.alt}
                className={styles.showcaseImage}
                loading="lazy"
              />
              <div className={styles.showcaseContent}>
                <Heading as="h3" className={styles.showcaseTitle}>{item.title}</Heading>
                <p>{item.description}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

type Rung = {
  label: string;
  title: string;
  body: string;
  link: string;
  linkText: string;
};

const rungs: Rung[] = [
  {
    label: 'Default',
    title: 'A plain NAS',
    body: 'Dates, places, favourites, the people Immich recognised, and a few small classifiers on the CPU. No key beyond the Immich one, no account, nothing else to host. Tell it where home is and who is who, and that already makes a film worth sending.',
    link: '/docs/get-started/who-is-who',
    linkText: 'Teach it your family',
  },
  {
    label: 'Optional',
    title: 'Add a GPU',
    body: 'A caption for every picture in the cut and a second family-viewing check, and the reading goes faster. Everything already read stays banked, so adding one later redoes nothing.',
    link: '/docs/get-started/what-a-gpu-or-a-model-adds',
    linkText: 'What a GPU adds',
  },
  {
    label: 'Optional',
    title: 'Add a model',
    body: 'With a GPU there too, a text model reads the draft and swaps out the shots that add nothing, writes the title and picks the music. Local or hosted, your choice, and the rules draft still ships if it fails.',
    link: '/docs/better/overview',
    linkText: 'Make it better',
  },
];

function LadderSection() {
  return (
    <section className={styles.ladder}>
      <div className="container">
        <Heading as="h2" className={styles.sectionTitle}>
          Grows with you
        </Heading>
        <p className={styles.ladderIntro}>
          Start with the container. Every step up is optional, and none of them means a
          reinstall.
        </p>
        <div className={styles.ladderGrid}>
          {rungs.map((rung) => (
            <div key={rung.title} className={styles.rung}>
              <span className={styles.rungLabel}>{rung.label}</span>
              <Heading as="h3" className={styles.rungTitle}>{rung.title}</Heading>
              <p>{rung.body}</p>
              <Link to={rung.link}>{rung.linkText} →</Link>
            </div>
          ))}
        </div>
        <div className={styles.ladderMore}>
          <p>
            <strong>Then, when you want it:</strong>{' '}
            <Link to="/docs/make/automate">one film a day on its own</Link>, uploaded back into
            Immich if you ask; <Link to="/docs/make/cli/generate">the CLI</Link> for scripts and cron;{' '}
            <Link to="/docs/how-it-chooses/overview">every selection rule written down</Link> and{' '}
            <Link to="/docs/how-it-chooses/overrule-it">every lever to overrule it</Link>;{' '}
            <Link to="/docs/run/kubernetes">Kubernetes</Link>,{' '}
            <Link to="/docs/run/terraform">Terraform</Link>,{' '}
            <Link to="/docs/run/authentication">OIDC</Link> and{' '}
            <Link to="/docs/run/database">PostgreSQL</Link> for the operators.
          </p>
        </div>
      </div>
    </section>
  );
}

function ValuesSection() {
  return (
    <section className={styles.values}>
      <div className="container">
        <div className={styles.valuesGrid}>
          <div className={styles.value}>
            <div className={styles.valueIcon}>
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
              </svg>
            </div>
            <strong>Your data stays home</strong>
            <p>A default run talks to your Immich server and nothing else. No telemetry, no account. Map tiles and place names are two switches, off until you turn them on, and a model gets pictures only if you configure one.</p>
          </div>
          <div className={styles.value}>
            <div className={styles.valueIcon}>
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
            </div>
            <strong>Read-only by default</strong>
            <p>Your originals are never modified. Upload-back is opt-in, and the only thing it ever trashes is its own superseded render of the same memory.</p>
          </div>
          <div className={styles.value}>
            <div className={styles.valueIcon}>
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="14" y2="17"/>
              </svg>
            </div>
            <strong>Every rule written down</strong>
            <p>How it picks is documented with diagrams, and <code>runs why</code> says which step kept a picture or left it out. The web UI shows the CLI command behind every job it starts.</p>
          </div>
          <div className={styles.value}>
            <div className={styles.valueIcon}>
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
              </svg>
            </div>
            <strong>One film a day, if you want it</strong>
            <p>Once a day, <code>immich-memories auto run</code> picks the one memory worth making (a trip that just ended, last month, a birthday), with variety rules so it does not repeat itself. In Docker a built-in timer runs it daily once you switch it on; bare metal installs a system job.</p>
          </div>
        </div>
      </div>
    </section>
  );
}

function CtaSection() {
  return (
    <section className={styles.finalCta}>
      <div className="container">
        <Heading as="h2" className={styles.ctaTitle}>
          Cut your first month tonight
        </Heading>
        <p className={styles.ctaDescription}>
          One container on the box that already runs Immich.
        </p>
        <div className={styles.heroCtas}>
          <Link className={styles.ctaPrimary} to="/docs/get-started/quick-start">
            Quick start
          </Link>
          <Link className={styles.ctaSecondary} to="/docs/run/requirements">
            Requirements
          </Link>
        </div>
      </div>
    </section>
  );
}

export default function Home(): ReactNode {
  return (
    <Layout
      title="Home"
      description="Turn your Immich library into memory films: a month, a year, a trip, one person. Works on a plain NAS, better with a GPU or a model. Titles, maps and music, self-hosted.">
      <HeroSection />
      <QuickstartSection />
      <ShowcaseSection />
      <LadderSection />
      <ValuesSection />
      <CtaSection />
    </Layout>
  );
}
