import {useEffect, useState, type ReactNode} from 'react';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import CodeBlock from '@theme/CodeBlock';
import Link from '@docusaurus/Link';
import {buildSetup, type Setup, type Sources, type Platform} from './recipes';
import sources from './sources.json';
import styles from './styles.module.css';

export default function SetupBuilder({initialPlatform = 'linux', initialInline = false, showCommands = true, showPlatform = true}: {initialPlatform?: Platform; initialInline?: boolean; showCommands?: boolean; showPlatform?: boolean} = {}): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  const buildVersion = String(siteConfig.customFields?.version || 'development');
  const [setup, setSetup] = useState<Setup>({
    platform: initialPlatform, inline: initialInline, uiPort: 8080, namespace: 'immich-memories', tier: 'basic', immichUrl: 'http://192.168.1.10:2283', apiKey: '',
    gpuBox: '', readerUrl: '', readerModel: '', readerApiKey: '', cuda: false,
    version: buildVersion,
  });
  const [notice, setNotice] = useState('');
  useEffect(() => {
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    setSetup(previous => ({...previous, secretKey: [...bytes].map(value => value.toString(16).padStart(2, '0')).join('')}));
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
  return <section className={styles.builder} aria-label="Setup builder">
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
      <label>Immich API key
        <input type="password" autoComplete="off" value={setup.apiKey} onChange={event => update({apiKey: event.target.value})} />
      </label>
      {hostPort && <label>UI host port
        <input type="number" min="1" max="65535" step="1" value={setup.uiPort} onChange={event => update({uiPort: Number(event.target.value)})} />
        <small>Choose a free port if another app already uses 8080. The UI stays localhost-only.</small>
      </label>}
      {setup.platform === 'kubernetes' && <label>Namespace
        <input value={setup.namespace} onChange={event => update({namespace: event.target.value})} />
        <small>Applied to both generated files and every command below.</small>
      </label>}
    </div>
    <p className={styles.note}>Create a key with the <Link to="/docs/run/docker#the-api-key">ten required read permissions</Link>.
      Add the five upload permissions only to send films back; <code>asset.delete</code> is optional.
      Avoid the All preset.</p>
    <fieldset className={styles.tiers}>
      <legend>Choose a tier</legend>
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
        <small>Needs the NVIDIA driver and container toolkit. A CPU container does not satisfy GPU readiness.</small>
      </label>}
      {setup.tier === 'full' && <>
        <label>Reader URL{setup.platform === 'mac' ? ' (optional)' : ''}
          <input type="url" value={setup.readerUrl} onChange={event => update({readerUrl: event.target.value})} placeholder={setup.platform === 'mac' ? 'Blank: app-owned local reader' : 'http://reader.example.lan:8000/v1'} />
        </label>
        <label>Reader model{setup.platform === 'mac' ? ' (optional)' : ''}
          <input value={setup.readerModel} onChange={event => update({readerModel: event.target.value})} placeholder={setup.platform === 'mac' ? 'Blank: pinned local default' : 'Name advertised by your reader'} />
        </label>
        <label>Reader API key (optional)
          <input aria-label="Reader API key (optional)" type="password" autoComplete="off" value={setup.readerApiKey || ''} onChange={event => update({readerApiKey: event.target.value})} />
          <small>Needed only when your reader requires authentication.</small>
        </label>
      </>}
    </div>
    {compose && <label className={styles.check}>
      <input type="checkbox" checked={Boolean(setup.inline)} onChange={event => update({inline: event.target.checked})} />
      Single file for a stack editor
      <small>Includes your credentials and a browser-generated settings key. Store the downloaded file privately.</small>
    </label>}
    <p className={styles.note}><Link to="/docs/run/tested-deployments">Can I run this? Check the version and topology matrix.</Link></p>
    <p className={styles.note}><strong>Not yet tested as an end-to-end generated installation</strong> on
      {' '}{({linux: 'Linux Docker Compose', synology: 'Synology Container Manager', mac: 'native Mac', kubernetes: 'Kubernetes'})[setup.platform]}.
      {' '}Files are checked with Compose/Kustomize and the form is checked in a browser. Those checks do not run this installation.
      {' '}Earlier NAS, Mac and GPU Kubernetes checks are recorded in the <Link to="/docs/better/measured#cold-start-time-by-hardware-and-tier">measured results</Link>.
      {' '}<Link href="https://github.com/sam-dumont/immich-memories/issues/new">Tried it? Report your platform, release and preflight result.</Link>
    </p>
    <p className={styles.note}>Your choices produce files in this browser. Nothing is sent to an Immich or model server.
      {setup.tier === 'full' && ' Full explicitly enables reader calls.'}</p>
    {result.error ? <p className={styles.error} role="status">{result.error}</p> : <div aria-live="polite">
      <p>Save these files for a fresh install. For an existing install, change service URLs in Settings.
        Preflight checks whether the requested tier is ready.</p>
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
      {result.accessCommands && <CodeBlock language="bash" title="Private UI access">{result.accessCommands}</CodeBlock>}
      {showCommands && <CodeBlock language="bash" title={result.workerCommands ? "On the app host" : "Install and check"}>{result.commands}</CodeBlock>}
    </div>}
  </section>;
}
