import { FILM_PICTURES_END, SHOTS } from "./fixture.ts";

// Frames at 30 fps. The composition and the hero recipe read this same edit.
export const FPS = 30;
export const FADE = 15;
export const SLIDE = 12;
export const FILM_TRANSITION = 18;
export const CLOSING_TRANSITION = 24;

export const SCENE_FRAMES = {
  title: 150,
  brief: 210,
  cutting: 150,
  review: 300,
  edit: 330,
  render: 240,
  film: 120,
  runs: 150,
  suggestions: 180,
  cli: 480,
  output: 420,
  closing: 135,
} as const;

const overlaps = {
  title: 0, brief: FADE, cutting: 0, review: FADE, edit: 0,
  render: 0, film: 0, runs: SLIDE, suggestions: SLIDE, cli: FADE,
  output: FILM_TRANSITION, closing: CLOSING_TRANSITION,
} as const;

let cursor = 0;
export const SCENE_START = Object.fromEntries(
  Object.entries(SCENE_FRAMES).map(([name, frames]) => {
    const key = name as keyof typeof SCENE_FRAMES;
    cursor -= overlaps[key];
    const start = cursor;
    cursor += frames;
    return [key, start];
  }),
) as Record<keyof typeof SCENE_FRAMES, number>;

export const TOTAL_FRAMES = cursor;
export const MUSIC_FADE_START = SCENE_START.closing;
export const MUSIC_FADE_END = TOTAL_FRAMES - 15;

// The last stretch of the film's pictures, at normal speed, ending on a photograph: the
// film ends on a blurred card, and the demo holds its final picture before the closing
// frame rather than cutting off a moving image. Where that is moves with every re-cut, so
// the exporter measures it (FILM_PICTURES_END).
export const OUTPUT_PLAY_FRAMES = 375;
export const OUTPUT_FROM = Math.max(0, FILM_PICTURES_END - OUTPUT_PLAY_FRAMES / FPS);
// The page's player opens on the film's first picture, ahead of the shots the revision
// swapped and removed.
export const PLAYER_FROM = SHOTS[0].start;
export const PLAYER_PLAY = 30;
