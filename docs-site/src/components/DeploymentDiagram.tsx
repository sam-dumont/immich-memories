import React, {useEffect, useId, useRef, useState} from 'react';
import styles from './DeploymentDiagram.module.css';

type Topology = 'basic' | 'worker' | 'cluster' | 'mac';
type Phase = 'prepare' | 'render' | 'access';
type Node = {name: string; sub: string; detail: string; kind: 'server' | 'chip' | 'photos' | 'browser'};
type Group = {id: string; title: string; boundary: string; nodes: Node[]; storage?: string};
type Flow = {from: string; to: string; label: string; detail: string; bypass?: boolean};
const titles: Record<Topology, string> = {
  basic: 'One app beside Immich', worker: 'App + one GPU service',
  cluster: 'Distributed Kubernetes services', mac: 'Local services on Apple Silicon',
};
const phases: {id: Phase; label: string}[] = [
  {id: 'prepare', label: 'Prepare a cut'}, {id: 'render', label: 'Render a film'},
  {id: 'access', label: 'Open the app'},
];

function model(topology: Topology, phase: Phase): {groups: Group[]; flows: Flow[]; note: string} {
  const remote = topology === 'worker' || topology === 'cluster';
  const app: Group = {
    id: 'app', title: 'Immich Memories',
    boundary: topology === 'cluster' ? 'App pod · one replica' : topology === 'mac' ? 'Your Mac · native app' : 'Your app host',
    nodes: [{name: 'App + CLI', sub: phase === 'access' ? 'Web UI · port 8080' : phase === 'render' ? 'Assemble the film' : 'Choose the cut', kind: 'server',
      detail: phase === 'render' ? remote ? 'Hands the chosen cut to the render worker. The UI and run history stay here.' : 'Downloads the selected originals and renders locally with FFmpeg.' : phase === 'prepare' ? 'Reads Immich metadata and previews, saves reusable facts, then chooses the cut. Laya runs in the app, even with a remote preparation service.' : 'Serves the UI and proxies previews. The browser does not receive your Immich API key.'}],
    storage: topology === 'cluster' ? 'Data/cache · output · model PVCs' : 'Store · cache · output files',
  };
  if (topology === 'mac' && phase === 'prepare') app.nodes.push({name: 'Owned local reader', sub: 'llama.cpp · when enabled', kind: 'chip', detail: 'A separate app-owned process reads annotation text. A blank reader URL selects this runtime when the reader is enabled. Its model is released before local rendering and music.'});
  const photos: Group = {id: 'immich', title: 'Your Immich', boundary: 'Existing Immich server', nodes: [{name: 'Immich API', sub: 'Your configured URL', kind: 'photos', detail: 'Provides metadata, previews and original media. Upload is optional; the app does not change the source originals.'}], storage: 'Your photo and video library'};
  let services: Group;
  if (phase === 'access' || topology === 'basic') {
    services = {id: 'services', title: 'Your browser', boundary: 'Desktop or phone', nodes: [{name: 'Web UI', sub: 'App URL · authenticated if exposed', kind: 'browser', detail: 'Connects to the app, which serves cached media or fetches it from Immich. Configure authentication before opening access to other machines.'}]};
  } else if (topology === 'worker') {
    services = {id: 'services', title: 'GPU service', boundary: 'NVIDIA host · one container', nodes: [{name: phase === 'prepare' ? 'Facts + captions' : 'Render worker', sub: phase === 'prepare' ? 'Port 8092 · /facts and /v1' : 'Port 8092 · /render', kind: 'chip', detail: phase === 'prepare' ? 'Receives previews for classification and captioning. These routes have no built-in authentication; keep them private.' : 'Receives the cut and Immich URL/API key, fetches originals and returns the film. /render requires a bearer token.'}], storage: 'Model cache · render scratch'};
  } else if (topology === 'cluster') {
    services = {id: 'services', title: phase === 'prepare' ? 'Preparation services' : 'Render sidecar', boundary: phase === 'prepare' ? 'Pods + supplied reader endpoint' : 'Same pod as the app', nodes: phase === 'prepare' ? [
      {name: 'Inference', sub: 'GPU reservation · 1 allocation', kind: 'chip', detail: 'Receives sampled frames for classification. The overlay reserves one advertised NVIDIA GPU allocation for this pod.'},
      {name: 'Caption server', sub: 'GPU allocation must be configured', kind: 'chip', detail: 'Receives picture tiles and frame strips. The shipped CUDA caption deployment has no GPU resource reservation. Configure allocation or advertised sharing before scheduling it.'},
      {name: 'Text reader', sub: 'Existing API · not deployed here', kind: 'server', detail: 'The overlay expects an existing text-reader endpoint and a served model name. This service receives annotation text, not pictures. Configure it separately; it can run on your network or another permitted endpoint.'},
    ] : [{name: 'Render worker', sub: 'App pod GPU reservation · 1 allocation', kind: 'chip', detail: 'The app and render sidecar share their pod. The app calls the authenticated worker on 127.0.0.1:8093. The sidecar receives the Immich key, fetches originals and returns the film to the app. The diagram does not promise that all workloads fit on two GPU nodes.'}], storage: phase === 'prepare' ? 'Service model caches' : 'Worker scratch/cache · ephemeral'};
  } else {
    services = {id: 'services', title: phase === 'prepare' ? 'Caption server' : 'Local rendering', boundary: 'Same Mac · separate runtime', nodes: [{name: phase === 'prepare' ? 'MLX captions' : 'Native FFmpeg rendering', sub: phase === 'prepare' ? 'localhost:8092/v1' : 'Runs inside the app workflow', kind: 'chip', detail: phase === 'prepare' ? 'Start the caption server separately. It receives picture tiles; keep its bind address on localhost when only this Mac uses it.' : 'Rendering uses VideoToolbox encoding and Metal title effects where available, with CPU fallback. This is not a remote worker or another machine. Docker on macOS cannot use Metal directly.'}]};
  }
  if (topology === 'cluster' && phase === 'access') services.nodes.push({name: 'HTTPS proxy + OIDC', sub: 'Operator-provided services', kind: 'server', detail: 'The example enables OIDC but does not deploy an ingress or identity provider. Supply the HTTPS proxy and identity registration; the app handles the login flow. This card groups the access dependencies, not one container.'});
  const flows: Flow[] = [{from: 'app', to: 'immich', label: phase === 'render' && remote ? 'Optional delivery' : phase === 'render' ? 'Selected originals' : phase === 'access' ? 'Preview requests' : 'Metadata + previews', detail: phase === 'render' && remote ? 'After rendering, the app can upload the finished film if you enable delivery.' : phase === 'render' ? 'The app downloads media for the chosen cut.' : phase === 'access' ? 'The app keeps the Immich key on the server.' : 'Preparation starts with your library; originals remain in Immich.'}];
  if (phase === 'access' || topology === 'basic') flows.push({from: 'services', to: 'app', label: 'Browser → app', detail: 'UI requests and media go through the app, behind the same login.'});
  else if (phase === 'prepare') flows.push({from: 'app', to: 'services', label: 'Preview tiles + frames', detail: topology === 'cluster' ? 'Classification and captions go to separate services. The text reader receives annotations through its separately configured endpoint.' : 'Images go to the caption service; the text reader is a separate role.'});
  else if (remote) {
    flows.push({from: 'app', to: 'services', label: 'Cut + Immich credentials', detail: 'The authenticated render request includes the Immich URL and API key. Use HTTPS across an untrusted network.'});
    flows.push({from: 'services', to: 'immich', label: 'Worker → originals', detail: 'The worker needs its own network route to Immich. It returns the finished film to the app.', bypass: true});
  } else flows.push({from: 'app', to: 'services', label: 'Local render work', detail: 'No remote handoff: processing and output stay on this Mac.'});
  if (remote && phase === 'render') flows.push(flows.shift()!);
  return {groups: [photos, app, services], flows, note: topology === 'cluster' ? 'Service boundaries, not node placement. Reserve GPUs explicitly; a namespace is not an authentication boundary. Reader and music endpoints are configured separately.' : topology === 'worker' ? 'One GPU container shares the GPU across phases and releases owned models between phases. Reader and generated-music services are separate choices, not included here.' : topology === 'mac' ? 'The app and caption runtime share one Mac. Captions and the reader are enabled in this recipe; generated music is optional.' : 'The default film needs no model server or GPU. The app keeps the store and outputs; Immich keeps your originals.'};
}

function Icon({kind}: {kind: Node['kind'] | 'disk'}) {
  const paths = {
    server: 'M4 3h16v7H4z M4 14h16v7H4z M7 6h1 M7 17h1 M12 6h5 M12 17h5',
    chip: 'M7 7h10v10H7z M10 10h4v4h-4z M9 3v4 M15 3v4 M9 17v4 M15 17v4 M3 9h4 M3 15h4 M17 9h4 M17 15h4',
    photos: 'M3 5h18v15H3z M3 16l5-5 5 5 3-3 5 5 M15 9h.01',
    browser: 'M3 4h18v16H3z M3 9h18 M6 6.5h.01 M9 6.5h.01',
    disk: 'M4 5c0-4 16-4 16 0s-16 4-16 0v14c0 4 16 4 16 0V5 M4 12c0 4 16 4 16 0',
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d={paths[kind]} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

export default function DeploymentDiagram({topology = 'basic', chooseTopology = false}: {topology?: Topology; chooseTopology?: boolean}) {
  const [view, setView] = useState(topology);
  const [phase, setPhase] = useState<Phase>('prepare');
  const [selected, setSelected] = useState<string | null>(null);
  const [drawing, setDrawing] = useState<{key: string; width: number; height: number; paths: {path: string; bypass?: boolean; badge: [number, number]}[]}>({key: '', width: 1, height: 1, paths: []});
  const canvas = useRef<HTMLDivElement>(null);
  const marker = `arrow-${useId().replace(/:/g, '')}`;
  const {groups, flows, note} = model(view, phase);
  const selectedNode = groups.flatMap(group => group.nodes).find(node => node.name === selected);
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const measure = () => {
      const bounds = element.getBoundingClientRect();
      const boxes = new Map(Array.from(element.querySelectorAll<HTMLElement>('[data-machine]')).map(item => [item.dataset.machine!, item.getBoundingClientRect()]));
      const paths = flows.map(flow => {
        const a = boxes.get(flow.from)!, b = boxes.get(flow.to)!;
        const vertical = Math.abs(a.left - b.left) < 10;
        if (vertical) {
          if (flow.bypass) {
            const x = a.left - bounds.left + 1, end = b.left - bounds.left + 1;
            return `M ${x} ${a.top - bounds.top + 30} H 8 V ${b.top - bounds.top + 30} H ${end}`;
          }
          const down = a.top < b.top;
          const x = a.left - bounds.left + a.width / 2;
          const y = (down ? a.bottom : a.top) - bounds.top;
          const end = (down ? b.top : b.bottom) - bounds.top;
          return `M ${x} ${y} L ${x} ${end}`;
        }
        if (flow.bypass) {
          const x = a.left - bounds.left + a.width / 2, end = b.left - bounds.left + b.width / 2;
          const y = a.bottom - bounds.top, finish = b.bottom - bounds.top;
          const bottom = bounds.height - 9;
          return `M ${x} ${y} V ${bottom - 8} Q ${x} ${bottom} ${x - 8} ${bottom} H ${end + 8} Q ${end} ${bottom} ${end} ${bottom - 8} V ${finish}`;
        }
        const right = a.left < b.left;
        const x = (right ? a.right : a.left) - bounds.left, end = (right ? b.left : b.right) - bounds.left;
        const y = a.top - bounds.top + 74, finish = b.top - bounds.top + 74;
        const mid = (x + end) / 2;
        return `M ${x} ${y} C ${mid} ${y}, ${mid} ${finish}, ${end} ${finish}`;
      });
      setDrawing({key: `${view}:${phase}`, width: bounds.width, height: bounds.height,
        paths: paths.map((path, index) => {
          const flow = flows[index], a = boxes.get(flow.from)!, b = boxes.get(flow.to)!;
          const vertical = Math.abs(a.left - b.left) < 10;
          const badge: [number, number] = flow.bypass
            ? vertical ? [8, (a.top + b.top) / 2 - bounds.top + 30] : [(a.left + a.width / 2 + b.left + b.width / 2) / 2 - bounds.left, bounds.height - 9]
            : vertical ? [a.left + a.width / 2 - bounds.left, (a.top < b.top ? a.bottom + b.top : b.bottom + a.top) / 2 - bounds.top]
            : [(a.left < b.left ? a.right + b.left : b.right + a.left) / 2 - bounds.left, a.top - bounds.top + 74];
          return {path, bypass: flow.bypass, badge};
        })});
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    element.querySelectorAll('[data-machine]').forEach(item => observer.observe(item));
    measure();
    return () => observer.disconnect();
  }, [view, phase]);
  return <figure className={styles.figure} aria-label={`${titles[view]}: ${phases.find(item => item.id === phase)!.label}`}>
    <div className={styles.header}>
      <div><span className={styles.eyebrow}>Deployment explorer</span><strong>{titles[view]}</strong></div>
      {chooseTopology && <label className={styles.selectLabel}>Setup<select aria-label="Deployment setup" value={view} onChange={event => {setView(event.target.value as Topology); setSelected(null);}}>{Object.entries(titles).map(([key, title]) => <option value={key} key={key}>{title}</option>)}</select></label>}
    </div>
    <div className={styles.controls} role="group" aria-label="Processing phase">{phases.map(item => <button key={item.id} type="button" aria-pressed={phase === item.id} onClick={() => {setPhase(item.id); setSelected(null);}}>{item.label}</button>)}</div>
    <div ref={canvas} className={styles.canvas}>
      <svg className={styles.wires} viewBox={`0 0 ${drawing.width} ${drawing.height}`} aria-hidden="true"><defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>{drawing.key === `${view}:${phase}` && drawing.paths.map(({path, bypass, badge}, index) => <g key={index}><path d={path} markerEnd={`url(#${marker})`} className={bypass ? styles.bypass : undefined} /><circle cx={badge[0]} cy={badge[1]} r="8" /><text x={badge[0]} y={badge[1]} dy=".35em">{index + 1}</text></g>)}</svg>
      {groups.map(group => <section key={group.id} className={styles.machine} data-machine={group.id} aria-label={group.title}>
        <div className={styles.machineHeading}><span>{group.boundary}</span><h3>{group.title}</h3></div>
        <div className={styles.nodes}>{group.nodes.map(node => <button type="button" className={styles.node} key={node.name} aria-pressed={selected === node.name} onClick={() => setSelected(selected === node.name ? null : node.name)}><Icon kind={node.kind} /><span><strong>{node.name}</strong><small>{node.sub}</small></span></button>)}</div>
        {group.storage && <div className={styles.storage}><Icon kind="disk" /><span>{group.storage}</span></div>}
      </section>)}
    </div>
    <div className={styles.flows}>{flows.map((flow, index) => <div key={flow.label}><span className={styles.number}>{index + 1}</span><p><strong>{flow.label}</strong><span>{flow.detail}</span></p></div>)}</div>
    <div className={styles.detail} aria-live="polite">{selectedNode ? <><strong>{selectedNode.name}</strong><p>{selectedNode.detail}</p></> : <p>{note} <span className={styles.hint}>Select a service for details.</span></p>}</div>
  </figure>;
}
