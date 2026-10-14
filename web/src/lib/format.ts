import { locale } from './i18n.svelte';

// Lengths, durations and sizes the way the reader's language writes them ("2.5 s", "2,5 s").

const unit = (value: number, name: string, digits: number, display: 'short' | 'narrow' = 'short') =>
  new Intl.NumberFormat(locale(), {
    style: 'unit',
    unit: name,
    unitDisplay: display,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);

/** A length in the film to the tenth of a second: "2.5 s". */
export const seconds = (value: number) => unit(value, 'second', 1);

/** A plain number to the tenth, for the start of a range ("0.5–2.5 s"). */
export const tenths = (value: number) =>
  new Intl.NumberFormat(locale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value);

/** A rough wait or estimate: whole seconds under a minute ("45 s"), whole minutes above ("3 min"). */
export const roughDuration = (value: number) =>
  value < 60 ? unit(Math.ceil(value), 'second', 0) : unit(Math.ceil(value / 60), 'minute', 0);

/** A file or cache size: "1.5 MB", "1,5 Mo". */
export const fileSize = (bytes: number) =>
  bytes < 1024 ** 2
    ? unit(bytes / 1024, 'kilobyte', 1)
    : bytes < 1024 ** 3
      ? unit(bytes / 1024 ** 2, 'megabyte', 1)
      : unit(bytes / 1024 ** 3, 'gigabyte', 2);

/** The month a chapter of the contact sheet opens on: "August 2025", "août 2025". */
export const monthOf = (taken: string) => {
  const when = new Date(taken.slice(0, 10) + 'T12:00:00');
  return Number.isNaN(when.getTime())
    ? ''
    : new Intl.DateTimeFormat(locale(), { month: 'long', year: 'numeric' }).format(when);
};

/** Time a job has been running: "3m 5s", "3 min 5 s", from whole seconds. */
export const elapsed = (value: number) => {
  const minutes = Math.floor(value / 60);
  const rest = unit(value % 60, 'second', 0, 'narrow');
  return minutes ? `${unit(minutes, 'minute', 0, 'narrow')} ${rest}` : rest;
};
