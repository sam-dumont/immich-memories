import { goto } from '$app/navigation';
import type { components } from './api-types';

export type RunSummary = components['schemas']['RunSummary'];
export type RunPage = components['schemas']['RunPage'];
export type Messages = components['schemas']['Messages'];
export type RunDetail = components['schemas']['RunDetail'];
export type Cut = components['schemas']['Cut'];
export type CutShot = components['schemas']['CutShot'];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail = '',
  ) {
    super(detail || `API answered ${status}`);
  }
}

// The same session cookie as the server pages; a 401 means the session ended.
export async function api<T>(path: string, fetcher: typeof fetch = fetch): Promise<T> {
  const response = await fetcher(`/api/v1${path}`, { headers: { accept: 'application/json' } });
  if (response.status === 401) {
    await goto('/login', { replaceState: true });
  }
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}

export const thumbnail = (assetId: string, size: 'thumbnail' | 'preview' = 'thumbnail') =>
  `/api/v1/assets/${encodeURIComponent(assetId)}/thumbnail${size === 'preview' ? '?size=preview' : ''}`;

export const video = (assetId: string) => `/api/v1/assets/${encodeURIComponent(assetId)}/video`;
