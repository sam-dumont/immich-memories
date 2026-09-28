import type { JobView } from './api';

/**
 * Follow a job by its server-sent events until it finishes. EventSource reconnects on its own,
 * so a dropped connection or a sleeping laptop picks the job up where the server has it.
 */
export function followJob(id: string, onUpdate: (job: JobView) => void): () => void {
  const source = new EventSource(`/api/v1/jobs/${encodeURIComponent(id)}/events`);
  source.onmessage = (event) => {
    const job = JSON.parse(event.data) as JobView;
    onUpdate(job);
    if (job.status !== 'running') source.close();
  };
  return () => source.close();
}
