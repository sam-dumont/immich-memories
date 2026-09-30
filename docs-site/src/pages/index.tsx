import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useBaseUrl from '@docusaurus/useBaseUrl';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';
import CodeBlock from '@theme/CodeBlock';
import {productDescription, productTagline} from '../product';
import styles from './index.module.css';

const journeys = [
  {label: 'Start here', title: 'Make your first film', body: 'Install, connect Immich, and try one month. Review the cut before rendering.', to: '/docs/get-started/quick-start', action: 'Quick start'},
  {label: 'After your first film', title: 'Get a better cut', body: 'Fix a missing person, change the length, swap a shot or choose the music.', to: '/docs/make/improve-a-film', action: 'Improve a film'},
  {label: 'For operators', title: 'Run it your way', body: 'Storage, authentication, networking and optional services. The details live here.', to: '/docs/run/overview', action: 'Operate and configure'},
];

export default function Home(): ReactNode {
  const demo = useBaseUrl('/demo/demo.mp4');
  const trip = useBaseUrl('/demo/trip-preview.mp4');
  const hero = useBaseUrl('/img/demo-hero.gif');
  const still = useBaseUrl('/img/screenshots/memory-story.png');
  const review = useBaseUrl('/img/screenshots/memory-review-edit.png');
  return (
    <Layout title="Immich Memories" description={productDescription}>
      <header className={styles.hero}>
        <div className="container">
          <div className={styles.heroInner}>
            <div className={styles.heroText}>
              <p className={styles.eyebrow}>Self-hosted · Works alongside Immich</p>
              <Heading as="h1" className={styles.heroTitle}>{productTagline}</Heading>
              <p className={styles.heroSubtitle}>
                Pick a month, a year, a trip or a person. Review the cut,
                then render with titles and music.
              </p>
              <div className={styles.heroCtas}>
                <Link className={styles.ctaPrimary} to="/docs/get-started/quick-start">Make your first film</Link>
                <Link className={styles.ctaSecondary} to="/docs/how-it-chooses/overview">How it chooses</Link>
              </div>
              <p className={styles.heroNote}>One container is enough to start. A GPU and a text model are optional.</p>
            </div>
            <div className={styles.heroVisual}>
              <a href={demo} aria-label="Play the Immich Memories demo with music">
                <picture>
                  <source media="(prefers-reduced-motion: reduce)" srcSet={still} />
                  <img className={styles.heroScreenshot} src={hero}
                    alt="Choose a month, review its cut, and watch the finished film"
                    width="720" height="405" fetchPriority="high" />
                </picture>
              </a>
              <p className={styles.heroCredit}>
                <a href={demo}>Play the demo with music</a> · <a href={trip}>Watch a trip film</a><br />
                CC0 stock pictures. <a href="https://github.com/sam-dumont/immich-video-memory-generator/blob/main/tests/e2e/fixtures/library/CREDITS.md">Credits</a>
              </p>
            </div>
          </div>
        </div>
      </header>

      <section className={styles.journeys}>
        <div className="container">
          <Heading as="h2" className={styles.sectionTitle}>Start with what you need</Heading>
          <div className={styles.journeyGrid}>
            {journeys.map((journey) => (
              <Link key={journey.to} to={journey.to} className={styles.journey}>
                <span className={styles.eyebrow}>{journey.label}</span>
                <Heading as="h3">{journey.title}</Heading>
                <p>{journey.body}</p>
                <span className={styles.journeyAction}>{journey.action} →</span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section className={styles.reviewSection}>
        <div className="container">
          <div className={styles.reviewGrid}>
            <img src={review} alt="Review a cut: swap a picture and remove a shot before rendering"
              className={styles.heroScreenshot} width="1440" height="900" loading="lazy" />
            <div>
              <p className={styles.eyebrow}>You get the final say</p>
              <Heading as="h2">Keep the moments. Change the rest.</Heading>
              <p>The app groups pictures into moments, picks shots that tell the story, and keeps them in time order. You see the cut before anything renders.</p>
              <p>Remove a shot, trim a video or swap a picture. The film renders from the revision you reviewed.</p>
              <Link to="/docs/get-started/first-film">See the first-film walkthrough →</Link>
            </div>
          </div>
        </div>
      </section>

      <section className={styles.quickstart}>
        <div className="container">
          <div className={styles.quickstartGrid}>
            <div>
              <Heading as="h2">A container next to Immich</Heading>
              <p>You need Immich v2 or v3, its API key, Docker Compose v2 and 4 GB of RAM for this container.</p>
              <p>The <Link to="/docs/get-started/quick-start">quick start</Link> supplies the Compose file and walks you through the connection. Once configured:</p>
              <CodeBlock language="bash" title="Start and prepare the app">
                {'docker compose up -d\ndocker compose exec immich-memories immich-memories models fetch'}
              </CodeBlock>
              <p className={styles.quickstartAlt}>Then open <code>http://localhost:8080</code>. For a remote host, follow the access instructions in the quick start.</p>
            </div>
            <div className={styles.trustPanel}>
              <Heading as="h3">Your originals stay yours</Heading>
              <p>A default film talks to your Immich server. No telemetry. Uploading the finished film back to Immich is opt-in.</p>
              <p>Maps and external model services need separate configuration.</p>
              <Link to="/docs/run/privacy">See what leaves your network →</Link>
              <hr />
              <Heading as="h3">Add more when you need it</Heading>
              <p>Start with the default cut. Add captions, model refinement or faster rendering later.</p>
              <Link to="/docs/better/overview">Optional upgrades →</Link>
            </div>
          </div>
        </div>
      </section>
    </Layout>
  );
}
