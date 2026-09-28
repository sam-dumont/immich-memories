import { goto } from '$app/navigation';
import type { components } from './api-types';

export type RunSummary = components['schemas']['RunSummary'];
export type RunPage = components['schemas']['RunPage'];
export type Messages = components['schemas']['Messages'];
export type RunDetail = components['schemas']['RunDetail'];
export type Cut = components['schemas']['Cut'];
export type CutShot = components['schemas']['CutShot'];
export type Story = components['schemas']['Story'];
export type JobView = components['schemas']['JobView'];
export type CutBrief = components['schemas']['CutBrief'];
export type RenderOptions = components['schemas']['RenderOptions'];
export type NamedPerson = components['schemas']['NamedPerson'];
export type AlbumChoice = components['schemas']['AlbumChoice'];
export type TripChoice = components['schemas']['TripChoice'];
export type Trips = components['schemas']['Trips'];
export type SpecialDay = components['schemas']['SpecialDay'];

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
    await goto('/app/login', { replaceState: true });
  }
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}

export const thumbnail = (assetId: string, size: 'thumbnail' | 'preview' = 'thumbnail') =>
  `/api/v1/assets/${encodeURIComponent(assetId)}/thumbnail${size === 'preview' ? '?size=preview' : ''}`;

export const video = (assetId: string) => `/api/v1/assets/${encodeURIComponent(assetId)}/video`;

/** POST JSON; a 409 hands back the job already running so the page can join it. */
export async function post<T>(path: string, body: unknown): Promise<{ status: number; body: T & { detail?: string; job?: JobView } }> {
  const response = await fetch(`/api/v1${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
  });
  if (response.status === 401) await goto('/app/login', { replaceState: true });
  // A proxy's error page or a crashed handler is not JSON; the caller still gets a status and a line.
  const answer = await response.json().catch(() => ({ detail: `${response.status} ${response.statusText}` }));
  return { status: response.status, body: answer };
}
