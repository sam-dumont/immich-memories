const KEY = 'immich-memories.demo-mode';

function read(): boolean {
  try {
    return localStorage.getItem(KEY) === 'on';
  } catch {
    return false;
  }
}

let on = $state(read());

/** Demo mode blurs every picture and video, for screenshots and screen sharing. */
export const demoMode = {
  get on() {
    return on;
  },
  toggle() {
    on = !on;
    try {
      localStorage.setItem(KEY, on ? 'on' : 'off');
    } catch {
      // Kept for this page only.
    }
  },
};
