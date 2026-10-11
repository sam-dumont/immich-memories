import {useEffect, useState, type ReactNode} from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';

const FLAG = 'plausible_ignore';

function OptOut(): ReactNode {
  const [ignored, setIgnored] = useState<boolean | null>(null);
  useEffect(() => {
    try { setIgnored(window.localStorage.getItem(FLAG) === 'true'); } catch { setIgnored(false); }
  }, []);
  const toggle = () => {
    try {
      if (ignored) window.localStorage.removeItem(FLAG);
      else window.localStorage.setItem(FLAG, 'true');
      setIgnored(!ignored);
    } catch { /* storage blocked: the tracker cannot read the flag either */ }
  };
  return <p>
    <button type="button" className="button button--secondary" onClick={toggle} disabled={ignored === null}>
      {ignored ? 'Count my visits again' : 'Stop counting my visits'}
    </button>
    {' '}<span role="status">{ignored === null ? '' : ignored ? 'Your visits are not counted in this browser.' : 'Your visits are counted, anonymously.'}</span>
  </p>;
}

const EVENTS: [string, string, string][] = [
  ['Pageview', 'You open a page', 'Page URL, referrer'],
  ['Engagement', 'You leave or switch away from a page', 'Time on page, how far you scrolled'],
  ['Outbound Link: Click', 'You click a link to another site', 'The link URL'],
  ['File Download', 'You click a link to a file on this site', 'The file URL'],
  ['Install Command Copied', 'You copy a command from a code block', 'The page, the tier tab that was open (basic, gpu, full or none) and the first word of the command (curl, docker, uv, pip, kubectl, helm or other). Not the command itself'],
  ['Install Tier Selected', 'You pick a tier tab in the quick start', 'The tier'],
  ['Demo Played', 'You play a demo video', 'The video file name'],
  ['Setup Builder Downloaded', 'You download a file from the setup builder', 'The tier and the file name. Nothing you typed'],
  ['Setup Builder Copied', 'You copy a file from the setup builder', 'The tier and the file name. Nothing you typed'],
  ['404', 'You land on a page that does not exist', 'The path you asked for'],
];

export default function Privacy(): ReactNode {
  return <Layout title="Privacy" description="What this documentation website records about visits, what it does not, and how to opt out.">
    <main className="container margin-vert--lg" style={{maxWidth: '48rem'}}>
      <h1>Privacy</h1>
      <p>This page covers the documentation website. The Immich Memories app you install sends no analytics:
        see <Link to="/docs/run/privacy">Run &gt; Privacy</Link> for what the app can contact.</p>

      <h2>Hosting</h2>
      <p>The site is static and served by GitHub Pages. GitHub receives your request and handles it under
        its own <Link href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement">privacy statement</Link>.</p>

      <h2>Counting visits</h2>
      <p>Visits are counted with <Link href="https://plausible.io/">Plausible</Link> Community Edition, which
        the maintainer hosts. It sets no cookies and does no fingerprinting. Nothing is stored in your browser,
        except the opt-out flag below if you set it.</p>
      <p>No personal data is stored. Plausible mixes your IP address, browser string and this site into a
        visitor hash with a salt that is rotated and deleted every 24 hours, so a visit cannot be tied to
        the next day's. The IP address and the raw browser string are not kept. Your country and region are
        worked out from the IP address at that moment.</p>

      <h2>What is recorded</h2>
      <p>Every event also carries the browser, operating system, device type, country and region.</p>
      <table>
        <thead><tr><th>Event</th><th>When</th><th>What it carries</th></tr></thead>
        <tbody>{EVENTS.map(([name, when, carries]) => <tr key={name}><td>{name}</td><td>{when}</td><td>{carries}</td></tr>)}</tbody>
      </table>
      <p>Nothing you type on this site is recorded. Nothing is shared, sold or used for advertising, and the
        data stays on the maintainer's server.</p>

      <h2>Opt out</h2>
      <p>The button sets a flag in your browser's local storage that makes the tracker skip your visits.
        It applies to this browser only. An ad blocker or your browser's tracking protection works too.</p>
      <OptOut />

      <h2>Contact</h2>
      <p>Questions or a removal request: open an issue or a discussion in
        the <Link href="https://github.com/sam-dumont/immich-memories">GitHub repository</Link>.</p>
    </main>
  </Layout>;
}
