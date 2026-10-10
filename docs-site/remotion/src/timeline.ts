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

// A continuous lake passage from the actual fixture film, reviewed at normal
// speed: jetty, camp above the lake, mist on the water. Hold the final picture
// before the closing card instead of cutting off a moving image.
export const OUTPUT_FROM = 43.5;
export const OUTPUT_PLAY_FRAMES = 375;
export const PLAYER_FROM = 19.2;
export const PLAYER_PLAY = 30;
