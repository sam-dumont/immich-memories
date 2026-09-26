import { error } from '@sveltejs/kit';
import { api, ApiError, type Cut, type RunDetail } from '$lib/api';

export const load = async ({ params, fetch }) => {
  const id = encodeURIComponent(params.run_id);
  const [run, cut] = await Promise.all([
    api<RunDetail>(`/runs/${id}`, fetch).catch((reason) => {
      if (reason instanceof ApiError && reason.status === 404) error(404, 'Run not found. It may have been removed.');
      throw reason;
    }),
    // A run that stopped before selection has no cut; the page shows the run without one.
    api<Cut>(`/runs/${id}/cut`, fetch).catch((reason) => {
      if (reason instanceof ApiError && reason.status === 404) return null;
      throw reason;
    }),
  ]);
  return { run, cut };
};
