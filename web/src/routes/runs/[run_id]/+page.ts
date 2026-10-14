import { error } from '@sveltejs/kit';
import { api, ApiError, type Cut, type RunDetail, type Story } from '$lib/api';
import { t } from '$lib/i18n.svelte';

export const load = async ({ params, fetch, parent }) => {
  const id = encodeURIComponent(params.run_id);
  const [run, cut, story] = await Promise.all([
    api<RunDetail>(`/runs/${id}`, fetch).catch(async (reason) => {
      if (reason instanceof ApiError && reason.status === 404) {
        // The layout loads the reader's words alongside; wait for them before wording the refusal.
        await parent();
        error(404, t('Run not found. It may have been removed.'));
      }
      throw reason;
    }),
    // A run that stopped before selection has no cut; the page shows the run without one.
    api<Cut>(`/runs/${id}/cut`, fetch).catch((reason) => {
      if (reason instanceof ApiError && reason.status === 404) return null;
      throw reason;
    }),
    api<Story>(`/runs/${id}/story`, fetch).catch((reason) => {
      if (reason instanceof ApiError && reason.status === 404) return null;
      throw reason;
    }),
  ]);
  return { run, cut, story };
};
