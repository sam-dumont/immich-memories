import React from 'react';
import Video from './Video';
import films from '../data/recorded-films.json';
import styles from './RecordedFilms.module.css';

// Written by scripts/demo_films.py from tests/e2e/fixtures/recordings: one real run of each
// memory type over the demo library, and the film rendered from it.
interface LeftOut {
  reason: string;
  pictures: number;
}

interface Film {
  memory_type: string;
  title: string | null;
  arguments: string[];
  film: string;
  poster: string;
  seconds: number;
  read: number;
  moments: number | null;
  stories: number;
  kept: number;
  left_out: LeftOut[];
}

const LABELS: Record<string, string> = {
  monthly_highlights: 'Monthly Highlights',
  year_in_review: 'Year in Review',
  season: 'Season',
  person_spotlight: 'Person Spotlight',
  multi_person: 'Multi-person',
  on_this_day: 'On This Day',
  holiday: 'Holiday',
  trip: 'Trip',
  album: 'Album',
  special_day: 'Special Day',
};

function length(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m ? `${m}:${String(s).padStart(2, '0')}` : `${s} s`;
}

function Step({label, value, of}: {label: string; value: number; of: number}) {
  // A log scale: 15 kept out of 1,129 read must still show as a bar.
  const width = Math.max(4, (Math.log10(value + 1) / Math.log10(of + 1)) * 100);
  return (
    <div className={styles.step}>
      <div className={styles.bar} style={{width: `${width}%`}} />
      <span className={styles.value}>{value.toLocaleString('en')}</span>
      <span className={styles.label}>{label}</span>
    </div>
  );
}

function Funnel({film}: {film: Film}) {
  return (
    <div className={styles.funnel} aria-label="From the pictures read to the film">
      <Step label="pictures read" value={film.read} of={film.read} />
      {film.moments ? <Step label="moments" value={film.moments} of={film.read} /> : null}
      <Step label={film.stories === 1 ? 'story' : 'stories'} value={film.stories} of={film.read} />
      <Step label="in the film" value={film.kept} of={film.read} />
      {film.left_out.length ? (
        <ul className={styles.reasons}>
          {film.left_out.map((row) => (
            <li key={row.reason}>
              <strong>{row.pictures.toLocaleString('en')}</strong> left out: {row.reason}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export default function RecordedFilms() {
  return (
    <div className={styles.grid}>
      {(films as Film[]).map((film) => (
        <section key={film.memory_type} className={styles.card}>
          <h3 className={styles.heading}>
            {LABELS[film.memory_type] ?? film.memory_type}
            <span className={styles.length}>{length(film.seconds)}</span>
          </h3>
          <Video
            src={film.film}
            poster={film.poster}
            controls
            preload="none"
            playsInline
            width="100%"
            className={styles.video}
            title={film.title ?? LABELS[film.memory_type]}
          />
          {film.title ? <p className={styles.title}>“{film.title}”</p> : null}
          <code className={styles.command}>immich-memories generate {film.arguments.join(' ')}</code>
          <Funnel film={film} />
        </section>
      ))}
    </div>
  );
}
