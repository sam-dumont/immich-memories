import {useEffect, useState, type ReactNode} from 'react';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import CodeBlock from '@theme/CodeBlock';
import Link from '@docusaurus/Link';
import {API_KEY_PLACEHOLDER, buildSetup, looksInternal, type Setup, type Sources, type Platform} from './recipes';
import sources from './sources.json';
import styles from './styles.module.css';
import {composeHostPort} from '../../compose-port';

export default function SetupBuilder({initialPlatform = 'linux', initialInline = false, showCommands = true, showPlatform = true}: {initialPlatform?: Platform; initialInline?: boolean; showCommands?: boolean; showPlatform?: boolean} = {}): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  const buildVersion = String(siteConfig.customFields?.version || 'development');
  const [setup, setSetup] = useState<Setup>({
    platform: initialPlatform, inline: initialInline, namespace: 'immich-memories', tier: 'basic', immichUrl: 'http://192.168.1.10:2283',
    gpuBox: '', readerUrl: '', readerModel: '', cuda: false,
    version: buildVersion,
  });
  const [notice, setNotice] = useState('');
  useEffect(() => {
    const token = () => [...crypto.getRandomValues(new Uint8Array(32))].map(value => value.toString(16).padStart(2, '0')).join('');
    setSetup(previous => ({...previous, secretKey: token(), triggerToken: token()}));
  }, []);
  const update = (values: Partial<Setup>) => {
    setNotice('');
    setSetup(previous => ({...previous, ...values}));
  };
  const copyFile = async (name: string, content: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setNotice(`Copied ${name}.`);
    } catch { setNotice('Copy is unavailable. Open the preview and select its text.'); }
  };
  const downloadFile = (name: string, content: string) => {
    const url = URL.createObjectURL(new Blob([content + '\n'], {type: 'text/plain;charset=utf-8'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = name.split('/').pop() || name;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice(`Download started: ${name}.`);
  };
  const result = buildSetup(setup, sources as Sources, buildVersion);
  const compose = setup.platform === 'linux' || setup.platform === 'synology';
  const hostPort = compose || setup.platform === 'mac';
  const uiPort = setup.uiPort ?? (setup.platform === 'mac' ? 8080 : composeHostPort(setup.version));
  return <section className={styles.builder} aria-label="Setup builder">
    <p className={styles.note}><strong>This page runs entirely in your browser.</strong> What you type here is never
      sent anywhere: no requests, no analytics, no tracking. The files are built on this page and stay on it until you copy or download them.</p>
    <div className={styles.fields}>
      {showPlatform && <label>Where will it run?
        <select aria-label="Where will it run?" value={setup.platform} onChange={event => update({platform: event.target.value as Setup['platform'], gpuBox: '', cuda: false})}>
          <option value="linux">Linux · Docker Compose</option>
          <option value="synology">Synology · Container Manager</option>
          <option value="mac">Mac · native</option>
          <option value="kubernetes">Kubernetes</option>
        </select>
      </label>}
      <p className={styles.note}>Setup files for docs build <strong>{buildVersion}</strong>.
        The app image and release assets use this same version.</p>
      <label>Immich URL
        <input type="url" value={setup.immichUrl} onChange={event => update({immichUrl: event.target.value})} />
      </label>
      {(looksInternal(setup.immichUrl) || setup.immichPublicUrl) && <label>Immich address in your browser
        <input type="url" placeholder="https://photos.example.org" value={setup.immichPublicUrl ?? ''} onChange={event => update({immichPublicUrl: event.target.value})} />
        <small>That URL only works from where the app runs, so the "View in Immich" links it shows would not open.
          Enter the address you open Immich at in your browser. Leave it empty to build links from the URL above.</small>
      </label>}
      {hostPort && <label>UI host port
        <input type="number" min="1" max="65535" step="1" value={uiPort} onChange={event => update({uiPort: Number(event.target.value)})} />
        <small>Choose a free port if another app already uses this one. The UI stays localhost-only.</small>
      </label>}
      {setup.platform === 'kubernetes' && <label>Namespace
        <input value={setup.namespace} onChange={event => update({namespace: event.target.value})} />
        <small>Applied to both generated files and every command below.</small>
      </label>}
      {setup.platform === 'kubernetes' && <label className={styles.check}>
        <input type="checkbox" checked={Boolean(setup.automation)} onChange={event => update({automation: event.target.checked})} />
        Scheduled films (CronJobs)
        <small>Adds a trigger token to the Secret and switches on the two CronJobs in the base.</small>
      </label>}
    </div>
    <p className={styles.note}>The builder does not ask for your Immich API key. The files hold the placeholder
      {' '}<code>{API_KEY_PLACEHOLDER}</code>: create a key with the <Link to="/docs/run/docker#the-api-key">ten required read permissions</Link>
      {' '}and paste it over the placeholder in your own editor. Add the five upload permissions only to send films back;
      {' '}<code>asset.delete</code> is optional. Avoid the All preset.</p>
    <fieldset className={styles.tiers}>
      <legend>Choose a tier</legend>
      <p className={styles.note}>Start with Basic if you are unsure. Every tier makes a complete film.</p>
      {([
        ['basic', 'Basic', 'A complete film from metadata and small classifiers.'],
        ['gpu', 'GPU', 'Picture descriptions, intent and extra sharing checks.'],
        ['full', 'Full', 'A text reader refines the draft and writes titles.'],
      ] as const).map(([value, label, detail]) => <label key={value}>
        <input type="radio" name="setup-tier" value={value} checked={setup.tier === value} onChange={() => update({tier: value})} />
        <span><strong>{label}</strong><small>{detail}</small></span>
      </label>)}
    </fieldset>
    <div className={styles.fields}>
      {compose && setup.tier !== 'basic' && <label>GPU box address (optional)
        <input aria-label="GPU box address (optional)" value={setup.gpuBox} onChange={event => update({gpuBox: event.target.value})} placeholder="192.168.1.50" />
        <small>Use the combined worker on your private network. Leave blank for services on this machine.</small>
      </label>}
      {compose && setup.tier !== 'basic' && !setup.gpuBox && <label className={styles.check}>
        <input type="checkbox" checked={setup.cuda} onChange={event => update({cuda: event.target.checked})} />
        Use NVIDIA CUDA containers
        <small>Select this for services on this NVIDIA host. Needs the NVIDIA driver and Container Toolkit; CPU images do not satisfy GPU readiness.</small>
      </label>}
      {setup.tier === 'full' && <>
        <label>Reader URL{setup.platform === 'mac' ? ' (optional)' : ''}
          <input type="url" value={setup.readerUrl} onChange={event => update({readerUrl: event.target.value})} placeholder={setup.platform === 'mac' ? 'Blank: app-owned local reader' : 'http://reader.example.lan:8000/v1'} />
        </label>
        <label>Reader model{setup.platform === 'mac' ? ' (optional)' : ''}
          <input value={setup.readerModel} onChange={event => update({readerModel: event.target.value})} placeholder={setup.platform === 'mac' ? 'Blank: pinned local default' : 'Name advertised by your reader'} />
        </label>
        <small>The builder does not ask for a reader API key: the files hold <code>replace-with-your-reader-api-key</code> when a reader URL is set. Replace it, or empty it for a reader without auth.</small>
      </>}
    </div>
    {compose && <label className={styles.check}>
      <input type="checkbox" checked={Boolean(setup.inline)} onChange={event => update({inline: event.target.checked})} />
      Single file for a stack editor
      <small>Includes a browser-generated settings key and your reader details. Store the downloaded file privately.</small>
    </label>}
    <details>
      <summary>Platform coverage and tested installations</summary>
      <p><Link to="/docs/run/tested-deployments">See the deployment matrix for exact release and platform coverage.</Link></p>
    {setup.platform === 'kubernetes'
      ? <p className={styles.note}><strong>Tested as a generated installation</strong> on Kubernetes (RKE2): the GPU tier and Basic, each with the CronJobs, were installed from builder output and made a film.
        {' '}The files are also checked with Kustomize and the form is checked in a browser.
        {' '}Other clusters, storage classes and tiers are not covered: see the <Link to="/docs/run/tested-deployments">matrix</Link>.
        {' '}<Link href="https://github.com/sam-dumont/immich-memories/issues/new">Tried it? Report your platform, release and preflight result.</Link>
      </p>
      : <p className={styles.note}><strong>Not yet tested as an end-to-end generated installation</strong> on
        {' '}{({linux: 'Linux Docker Compose', synology: 'Synology Container Manager', mac: 'native Mac'})[setup.platform]}.
        {' '}Files are checked with Compose and the form is checked in a browser. Those checks do not run this installation.
        {' '}Earlier NAS, Mac and GPU Kubernetes checks are recorded in the <Link to="/docs/better/measured#cold-start-time-by-hardware-and-tier">measured results</Link>.
        {' '}<Link href="https://github.com/sam-dumont/immich-memories/issues/new">Tried it? Report your platform, release and preflight result.</Link>
      </p>}
    </details>
    <p className={styles.note}>Nothing here contacts an Immich or model server.
      {setup.tier === 'full' && ' Full explicitly enables reader calls once the app runs.'}</p>
    {result.error ? <p className={styles.error} role="status">{result.error}</p> : <div aria-live="polite">
      <p>Save these files for a fresh install. For an existing install, change service URLs in Settings.
        Preflight checks whether the requested tier is ready. After it passes, make <Link to="/docs/get-started/first-film">your first film</Link>.</p>
      {result.files.map(file => <div key={file.name} className={styles.file}>
        <div className={styles.fileHeader}>
          <code>{file.name}</code>
          <div className={styles.fileActions}>
            <button type="button" className="button button--secondary button--sm" aria-label={`Copy ${file.name}`} onClick={() => void copyFile(file.name, file.content)}>Copy</button>
            <button type="button" className="button button--primary button--sm" aria-label={`Download ${file.name}`} onClick={() => downloadFile(file.name, file.content)}>Download</button>
          </div>
        </div>
        {file.name.endsWith('.env') && <p className={styles.note}>Browsers often save this as <code>env</code> or <code>env.txt</code>.
          Rename it to <code>.env</code> (with the leading dot) before you run <code>docker compose</code>.</p>}
        <details className={styles.preview}>
          <summary>Preview {file.name}</summary>
          <CodeBlock language={file.language}>{file.content}</CodeBlock>
        </details>
      </div>)}
      <p role="status">{notice}</p>
      {result.workerCommands && <CodeBlock language="bash" title="On the NVIDIA GPU host">{result.workerCommands}</CodeBlock>}
      {result.accessCommands && <details>
        <summary>Private UI access with an SSH tunnel</summary>
        <CodeBlock language="bash" title="Private UI access">{result.accessCommands}</CodeBlock>
      </details>}
      {compose && <p>On a server or NAS, configure <Link to={setup.inline ? "/docs/run/docker#stack-editor-lan-access" : "/docs/get-started/quick-start#2-connect-immich"}>app login for LAN access</Link> before starting, or use the private SSH tunnel above.</p>}
      {compose && !setup.inline && <p>The commands below use <code>immich-memories/output</code> for finished films. On Linux, run <code>mkdir -p immich-memories/output &amp;&amp; sudo chown 1000:1000 immich-memories/output</code> before those commands. On Synology, give that folder write access for UID/GID 1000 using the <Link to="/docs/run/nas#the-output-folder">folder permissions recipe</Link>.</p>}
      {showCommands && <CodeBlock language="bash" title={result.workerCommands ? "On the app host" : "Install and check"}>{result.commands}</CodeBlock>}
    </div>}
  </section>;
}
