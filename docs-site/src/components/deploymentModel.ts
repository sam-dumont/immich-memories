// The deployment explorer's content: what each setup and phase shows. DeploymentDiagram draws
// it; the Markdown pages list it as text.
export type Topology = 'basic' | 'worker' | 'cluster' | 'mac';
export type Phase = 'prepare' | 'render' | 'access';
export type Node = {name: string; sub: string; detail: string; kind: 'server' | 'chip' | 'photos' | 'browser'};
export type Group = {id: string; title: string; boundary: string; nodes: Node[]; storage?: string};
export type Flow = {from: string; to: string; label: string; detail: string; bypass?: boolean};
export const titles: Record<Topology, string> = {
  basic: 'One app beside Immich', worker: 'App + one GPU service',
  cluster: 'Distributed Kubernetes services', mac: 'Local services on Apple Silicon',
};
export const phases: {id: Phase; label: string}[] = [
  {id: 'prepare', label: 'Prepare a cut'}, {id: 'render', label: 'Render a film'},
  {id: 'access', label: 'Open the app'},
];

export function model(topology: Topology, phase: Phase): {groups: Group[]; flows: Flow[]; note: string} {
  const remote = topology === 'worker' || topology === 'cluster';
  const app: Group = {
    id: 'app', title: 'Immich Memories',
    boundary: topology === 'cluster' ? 'App pod · one replica' : topology === 'mac' ? 'Your Mac · native app' : 'Your app host',
    nodes: [{name: 'App + CLI', sub: phase === 'access' ? topology === 'mac' ? 'Native UI · port 8080' : 'App listener · port 8080' : phase === 'render' ? 'Assemble the film' : 'Choose the cut', kind: 'server',
      detail: phase === 'render' ? remote ? 'Hands the chosen cut to the render worker. The UI and run history stay here.' : 'Downloads the selected originals and renders locally with FFmpeg.' : phase === 'prepare' ? 'Reads Immich metadata and previews, saves reusable facts, then chooses the cut. On GPU and Full tiers, Laya runs in the app, even with a remote preparation service.' : topology === 'mac' ? 'Serves the UI on the native app port and proxies previews. The browser does not receive your Immich API key.' : 'Serves the UI and proxies previews on the app listener. For Compose, open the published host port in your browser; the container still listens on 8080. The browser does not receive your Immich API key.'}],
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
