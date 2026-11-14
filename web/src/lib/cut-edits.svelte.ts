import type { components } from './api-types';

type Cut = components['schemas']['Cut'];
type CutShot = components['schemas']['CutShot'];
export type RevisionEdits = components['schemas']['RevisionEdits'];

type Snapshot = { removed: string[]; segments: Record<string, [number, number]>; swaps: Record<string, string>; added: string[] };

const empty = (): Snapshot => ({ removed: [], segments: {}, swaps: {}, added: [] });
const copy = (value: Snapshot): Snapshot => ({
  removed: [...value.removed],
  segments: { ...value.segments },
  swaps: { ...value.swaps },
  added: [...value.added],
});

/**
 * The owner's unsaved edits to one cut, their last pass over it. Nothing here selects: it removes,
 * trims, holds a still longer or shorter, swaps a shot for another picture of its moment, or adds a
 * picture from the pool. The film is what they keep, longer or shorter than the cut. Undo walks
 * back one edit at a time; saving hands the edits to the server, which checks only what the
 * renderer cannot play.
 */
export class CutEditor {
  #cut: Cut;
  current = $state<Snapshot>(empty());
  history = $state<Snapshot[]>([]);
  fullVideoReset = $state(0);

  constructor(cut: Cut) {
    this.#cut = cut;
  }

  get count() {
    const { removed, segments, swaps, added } = this.current;
    return removed.length + Object.keys(segments).length + Object.keys(swaps).length + added.length;
  }

  #change(apply: (next: Snapshot) => void) {
    this.history = [...this.history, copy(this.current)];
    const next = copy(this.current);
    apply(next);
    this.current = next;
  }

  undo() {
    const previous = this.history.at(-1);
    if (!previous) return;
    this.history = this.history.slice(0, -1);
    this.current = previous;
  }

  discard() {
    if (this.count) this.#change((next) => Object.assign(next, empty()));
  }

  load(edits: RevisionEdits) {
    this.#change((next) => {
      next.removed = [...(edits.removed ?? [])];
      next.segments = Object.fromEntries(Object.entries(edits.segments ?? {}).map(([key, [a, b]]) => [key, [a, b]]));
      next.swaps = { ...(edits.swaps ?? {}) };
      next.added = [...(edits.added ?? [])];
    });
  }

  isRemoved = (shot: CutShot) => this.current.removed.includes(shot.asset_id);
  playing = (shot: CutShot) => this.current.swaps[shot.asset_id] ?? shot.asset_id;
  interval = (shot: CutShot): [number, number] | null =>
    this.current.segments[this.playing(shot)] ?? (shot.source_interval ? [...shot.source_interval] : null);
  seconds = (shot: CutShot) => {
    const segment = this.current.segments[this.playing(shot)];
    // The renderer counts recorded intervals, so the budget here does too.
    return segment ? segment[1] - segment[0] : shot.recorded_seconds;
  };
  // What the inspector says the shot holds: the edited stretch once trimmed or held, else the film's own time.
  onScreen = (shot: CutShot) => {
    const segment = this.current.segments[this.playing(shot)];
    return segment ? segment[1] - segment[0] : shot.seconds;
  };

  toggleRemoved(shot: CutShot) {
    this.#change((next) => {
      next.removed = next.removed.includes(shot.asset_id)
        ? next.removed.filter((id) => id !== shot.asset_id)
        : [...next.removed, shot.asset_id];
    });
  }

  trim(shot: CutShot, interval: [number, number]) {
    this.#change((next) => {
      next.segments[this.playing(shot)] = [Math.round(interval[0] * 100) / 100, Math.round(interval[1] * 100) / 100];
    });
  }

  hold(shot: CutShot, seconds: number) {
    this.trim(shot, [0, seconds]);
  }

  fullInterval(shot: CutShot): [number, number] | null {
    const duration = shot.source_duration;
    if (!shot.motion || duration == null || !Number.isFinite(duration) || duration < 0.01) return null;
    // Floor, as the renderer does, so rounding never puts the end beyond the source.
    return [0, Math.floor(duration * 100) / 100];
  }

  useFullVideos(shots: CutShot[] = this.#cut.shots) {
    const ranges = shots.flatMap((shot) => {
      if (this.isRemoved(shot) || this.playing(shot) !== shot.asset_id) return [];
      const interval = this.fullInterval(shot);
      const previous = this.interval(shot);
      if (!interval || (previous?.[0] === 0 && previous?.[1] === interval[1])) return [];
      return [{id: shot.asset_id, interval}];
    });
    if (ranges.length) this.#change((next) => {
      for (const {id, interval} of ranges) next.segments[id] = interval;
    });
    this.fullVideoReset += 1;
  }

  swap(shot: CutShot, replacement: string | null) {
    this.#change((next) => {
      const previous = next.swaps[shot.asset_id] ?? shot.asset_id;
      delete next.segments[previous];
      if (replacement && replacement !== shot.asset_id) next.swaps[shot.asset_id] = replacement;
      else delete next.swaps[shot.asset_id];
    });
  }

  unadd(assetId: string) {
    this.#change((next) => {
      next.added = next.added.filter((id) => id !== assetId);
      delete next.segments[assetId];
    });
  }

  /** Seconds of pictures and video the edited cut plays; an added picture counts as a typical shot. */
  get contentSeconds() {
    const kept = this.#cut.shots.filter((shot) => !this.isRemoved(shot));
    const typical = kept.length ? kept.reduce((sum, shot) => sum + this.seconds(shot), 0) / kept.length : 3;
    return kept.reduce((sum, shot) => sum + this.seconds(shot), 0) + this.current.added.length * typical;
  }

  /** Whether the film grows past the length the cut was made for: the owner's call, never refused. */
  get grows() {
    return this.#cut.content_budget_seconds != null && this.contentSeconds > this.#cut.content_budget_seconds + 1e-6;
  }

  get edits(): RevisionEdits {
    // Keep a removed shot's local range for Undo/Put it back, but do not send a
    // range for material the renderer is not going to play.
    const playing = new Set([
      ...this.#cut.shots.filter((shot) => !this.isRemoved(shot)).map(this.playing),
      ...this.current.added,
    ]);
    return {...this.current, segments: Object.fromEntries(
      Object.entries(this.current.segments).filter(([assetId]) => playing.has(assetId)),
    )};
  }
}
