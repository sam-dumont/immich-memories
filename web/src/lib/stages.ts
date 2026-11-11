import { roughDuration } from './format';
import { N_, t } from './i18n.svelte';

// Every heading a run can show, by the key the server sends (progress_text.STAGE_TEXTS keeps
// the same English templates for the terminal; a test holds the two tables equal).
const STAGES: Record<string, string> = {
  // The cut.
  'cut.evidence': N_('Preparing editorial evidence'),
  'cut.metadata': N_('Reading dates, places and people'),
  'cut.event_evidence': N_('Reading event evidence'),
  'cut.event_packs': N_('Reading event evidence'),
  'cut.cards': N_('Building editorial cards'),
  'cut.editing': N_('Editing the memory'),
  'cut.count_family_check': N_('Editing the memory: {pictures} pictures going into the family-viewing check'),
  'cut.count_duplicates': N_('Editing the memory: {pictures} pictures after the duplicate review'),
  'cut.count_picture_review': N_('Editing the memory: {pictures} pictures going into the picture review'),
  'cut.family_check': N_('Running the family-viewing check'),
  'cut.period_account': N_('Reading the period account: {month}'),
  'cut.timing': N_('Validating selected source timing'),
  'cut.complete': N_('Editorial selection complete'),
  'cut.cancelled': N_('Editorial selection cancelled'),
  'cut.failed': N_('Editorial selection failed'),
  'cut.batch_waiting': N_('Waiting on the {provider} batch: {count} prompts, submitted {time}'),
  'cut.reader_waiting': N_('Waiting for the reader: connection dropped, retry {attempt} of {retries}'),
  'cut.reader_gave_up': N_('Gave up on the reader after {retries} dropped connections: check that server'),
  // A free-text request preparing its period.
  'ask.unprepared': N_('{count} pictures in this period aren\'t prepared yet; preparing them first takes about {duration}'),
  'ask.prepared': N_('{count} pictures prepared'),
  // What a job shows before its command has said anything.
  'job.pool': N_('Preparing the pool'),
  'job.render': N_('Preparing the render'),
  'job.models': N_('Downloading pinned models'),
  'job.model': N_('Downloading {name}'),
  'job.detectors': N_('Downloading the detector snapshots'),
  'job.sentence': N_('Reading your sentence'),
  'job.library': N_('Reading the library'),
  // The render.
  'render.preparing_clips': N_('Preparing clips...'),
  'render.clips_prepared': N_('Clips prepared'),
  'render.downloading': N_('Downloading: {name}'),
  'render.extracting': N_('Extracting segment: {name}'),
  'render.sources_prepared': N_('Prepared {done}/{total} sources'),
  'render.title': N_('Generating title screen...'),
  'render.trip_map': N_('Generating trip map...'),
  'render.title_ready': N_('Title screen ready'),
  'render.year_card': N_('Year divider {index} of {count}'),
  'render.month_card': N_('Month divider {index} of {count}'),
  'render.location_card': N_('Location card {index} of {count}'),
  'render.ending': N_('Generating ending screen...'),
  'render.encoding': N_('Encoding video...'),
  'render.encoding_clock': N_('Encoding ({done} / {total}) — {percent}%'),
  'render.encoding_time': N_('Encoding ({time})'),
  'render.encoding_speed': N_('Encoding ({time}) @ {speed}x'),
  'render.assembly': N_('Streaming video assembly...'),
  'render.audio_mix': N_('Mixing audio...'),
  'render.mux': N_('Muxing final output...'),
  'render.check': N_('Checking the finished film'),
  'render.check_decoded': N_('Checking the finished film: {done} of {total} decoded'),
  'render.music_mute': N_('Muting original audio...'),
  'render.music': N_('Generating music...'),
  'render.music_mix': N_('Mixing music...'),
  'render.music_ready': N_('Music ready'),
  'render.music_warning': N_('Music finished with a warning'),
  'render.upload': N_('Uploading to Immich...'),
  'render.upload_incomplete': N_('Immich delivery incomplete; local film kept'),
  'render.complete': N_('Complete!'),
  'render.worker_check': N_('Checking the render worker'),
  'render.worker_queue': N_('Waiting for the render worker'),
  'render.worker_download': N_('Downloading the finished film'),
  'render.worker_bytes': N_('Downloading the finished film: {done}/{total} bytes'),
  'render.worker_bytes_open': N_('Downloading the finished film: {done} bytes received'),
  'render.worker_film_check': N_('Checking the downloaded film'),
  // The music, in a film or a preview.
  'music.reading_cut': N_('Reading the cut for music'),
  'music.checking_service': N_('Checking music service'),
  'music.generating': N_('Generating music'),
  'music.next_service': N_('Music service failed; trying the next service'),
  'music.stems': N_('Separating stems'),
  // The preparation passes, under the engine names they report with.
  reused: N_('Reusing saved picture checks'),
  skipped_models: N_('Model checks not requested'),
  skipped_captions: N_('Descriptions not requested'),
  previews: N_('Fetching picture previews'),
  pixels: N_('Measuring the pictures'),
  faces: N_('Finding faces'),
  public_heads: N_('Reading what each picture shows'),
  detectors: N_('Checking pictures for the family audience'),
  motion: N_('Measuring motion in the videos'),
  captions: N_('Describing the pictures'),
  remote_facts: N_('Reading picture facts'),
  obstruction: N_('Checking for a covered lens'),
  'videos.previews': N_('Fetching video clip previews'),
  'videos.detectors': N_('Checking video frames for the family audience'),
  'videos.detector_frames': N_('Sampling video frames'),
  'videos.remote_frames': N_('Checking video clips'),
  'videos.clip_frames': N_('Reading what each video shows'),
  'videos.video_motion': N_('Measuring motion in video clips'),
  'videos.obstruction_frames': N_('Checking video clips for a covered lens'),
  'live_photos.previews': N_('Fetching Live Photo clip previews'),
  'live_photos.detectors': N_('Checking Live Photo frames for the family audience'),
  'live_photos.detector_frames': N_('Sampling Live Photo frames'),
  'live_photos.remote_frames': N_('Checking Live Photo clips'),
  'live_photos.clip_frames': N_('Reading what each Live Photo clip shows'),
  'live_photos.video_motion': N_('Measuring motion in Live Photo clips'),
  'live_photos.obstruction_frames': N_('Checking Live Photo clips for a covered lens'),
  'videos.other': N_('Checking video clips'),
  'live_photos.other': N_('Checking Live Photo clips'),
  'pictures.other': N_('Preparing the pictures'),
};

/** A run's heading in the reader's language, from its stage key and the values it needs. */
export const stageHeading = (key: string, params: Record<string, string | number> = {}) => {
  const values: Record<string, string | number> = { ...params };
  if (params.duration_seconds != null) values.duration = roughDuration(Number(params.duration_seconds));
  const text = t(STAGES[key] ?? STAGES['pictures.other'], values);
  return params.frame != null && params.frames != null
    ? t('{stage} (frame {frame}/{frames})', { stage: text, frame: params.frame, frames: params.frames })
    : text;
};

/** A stage recorded before keys: a preparation pass's engine name, else the English it kept. */
export const stageLabel = (name: string, english = name) => (STAGES[name] ? t(STAGES[name]) : english);
