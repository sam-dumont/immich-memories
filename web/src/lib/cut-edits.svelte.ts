import type { components } from './api-types';

type Cut = components['schemas']['Cut'];
type CutShot = components['schemas']['CutShot'];
type Revision = components['schemas']['Revision'];
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
  // The added pictures as shots, by id: each revision brings the ones it adds.
  #additions = $state<Record<string, CutShot>>({});
  current = $state<Snapshot>(empty());
  history = $state<Snapshot[]>([]);

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

  load(edits: RevisionEdits & Pick<Revision, 'additions'>) {
    for (const shot of edits.additions ?? []) this.#additions[shot.asset_id] = shot;
    this.#change((next) => {
      next.removed = [...(edits.removed ?? [])];
      next.segments = Object.fromEntries(Object.entries(edits.segments ?? {}).map(([key, [a, b]]) => [key, [a, b]]));
      next.swaps = { ...(edits.swaps ?? {}) };
      next.added = [...(edits.added ?? [])];
    });
  }

  isRemoved = (shot: CutShot) => this.current.removed.includes(shot.asset_id);
  isAdded = (shot: CutShot) => this.current.added.includes(shot.asset_id);
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
    if (this.isAdded(shot)) return this.unadd(shot.asset_id);
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

  /**
   * The cut as the film plays it: its own shots in their order, each addition before the first
   * shot taken after it, as the renderer places them. Positions count the additions; the cut's
   * own shots keep their timecodes.
   */
  get shots(): CutShot[] {
    const when = (shot: CutShot) => Date.parse(shot.taken);
    const pending = this.current.added.flatMap((id) => this.#additions[id] ?? []).sort((a, b) => when(a) - when(b));
    if (!pending.length) return this.#cut.shots;
    const order: CutShot[] = [];
    for (const shot of this.#cut.shots) {
      while (pending.length && when(pending[0]) < when(shot)) order.push(pending.shift()!);
      order.push(shot);
    }
    order.push(...pending);
    let previous: CutShot | undefined;
    return order.map((shot, index) => {
      const month = shot.taken.slice(0, 7);
      previous = {
        ...shot,
        position: index + 1,
        start: this.isAdded(shot) ? (previous ? previous.start + previous.seconds : 0) : shot.start,
        new_day: shot.day !== previous?.day,
        chapter: month !== previous?.taken.slice(0, 7) ? shot.chapter || month : '',
      };
      return previous;
    });
  }

  /** Seconds of pictures and video the edited cut plays; an addition not yet known counts as a typical shot. */
  get contentSeconds() {
    const kept = this.#cut.shots.filter((shot) => !this.isRemoved(shot));
    const total = kept.reduce((sum, shot) => sum + this.seconds(shot), 0);
    const typical = kept.length ? total / kept.length : 3;
    const added = this.current.added.map((id) => (this.#additions[id] ? this.seconds(this.#additions[id]) : typical));
    return added.reduce((sum, seconds) => sum + seconds, total);
  }

  /** Whether the film grows past the length the cut was made for: the owner's call, never refused. */
  get grows() {
    return this.#cut.content_budget_seconds != null && this.contentSeconds > this.#cut.content_budget_seconds + 1e-6;
  }

  /** What a save sends: a trim on a shot taken out stays here for Undo, never in the revision. */
  get edits(): RevisionEdits {
    const kept = this.#cut.shots.filter((shot) => !this.isRemoved(shot)).map((shot) => this.playing(shot));
    const plays = new Set([...kept, ...this.current.added]);
    const segments = Object.fromEntries(Object.entries(this.current.segments).filter(([id]) => plays.has(id)));
    return { ...this.current, segments };
  }
}
