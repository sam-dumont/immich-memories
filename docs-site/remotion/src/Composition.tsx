import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Audio } from "@remotion/media";
import { staticFile, interpolate } from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { COLORS, MUSIC_FADE_START, TOTAL_FRAMES } from "./theme";
import { useBassIntensity } from "./hooks/useBassIntensity";
import { TitleScene } from "./scenes/TitleScene";
import { BriefScene } from "./scenes/BriefScene";
import { CuttingScene } from "./scenes/CuttingScene";
import { ReviewScene } from "./scenes/ReviewScene";
import { EditScene } from "./scenes/EditScene";
import { RenderScene } from "./scenes/RenderScene";
import { FilmScene } from "./scenes/FilmScene";
import { RunsScene } from "./scenes/RunsScene";
import { SuggestionsScene } from "./scenes/SuggestionsScene";
import { CliScene } from "./scenes/CliScene";
import { OutputPreviewScene } from "./scenes/OutputPreviewScene";

const FADE = 15; // 0.5s
const SLIDE = 12; // 0.4s

// Scene durations (frames at 30fps). TransitionSeries overlaps each pair it
// joins by the transition's length, so the video runs sum(D) - sum(transitions):
// 1570 - 84 = 1486 frames, which is TOTAL_FRAMES in theme.ts. Scenes on the
// same page (the brief and its cut; the run page from review to film) follow
// each other with no transition, the way the browser shows them.
//
// The ceiling is demo-music.wav: 49.97 s, or 1499 frames. A demo that outruns
// its own track ends on an audible cut, which is why the terminal and the film
// tail are cut to the frame rather than rounded up.
const D = {
  title: 75, // 2.5s
  brief: 170, // 5.7s — Monthly Highlights, June 2024, the command follows; Cut
  cutting: 140, // 4.7s — the job panel: stage, bar, "N of M · ~Ns left", pictures just read
  review: 190, // 6.3s — the contact sheet; a video shot and why it is there; Stories and back
  edit: 240, // 8.0s — swap one shot, remove one, Save revision
  render: 160, // 5.3s — Revision 1, date overlay, Render; the render's own stages
  film: 100, // 3.3s — the film plays on the page
  runs: 80, // 2.7s — the film's run and the cut's, with the older ones
  suggestions: 85, // 2.8s — what automation would make next; check one
  // The recording runs 58.0s and CliScene starts it at 18.6s, so 118 frames at
  // 10x is the whole rest of it: one more and the terminal freezes on its last
  // line, one fewer and the `open` that ends it never arrives.
  cli: 118, // 3.9s — the real terminal at 10x: the bar, the cut, runs story, runs why
  output: 212, // 7.1s — the film it made, ending on its last picture, full bleed
};

export const DemoVideo: React.FC = () => {
  const frame = useCurrentFrame();
  const bass = useBassIntensity(frame);

  // Ease the soundtrack in, then fade out over the last five seconds.
  const musicVolume = (f: number) =>
    interpolate(f, [0, 30, MUSIC_FADE_START, TOTAL_FRAMES], [0, 0.7, 0.7, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <Audio src={staticFile("demo-music.wav")} volume={musicVolume} />

      <TransitionSeries>
        {/* 1. Title */}
        <TransitionSeries.Sequence durationInFrames={D.title}>
          <TitleScene />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: FADE })}
        />

        {/* 2. Brief — the memory type, the month, the command it stands for; Cut */}
        <TransitionSeries.Sequence durationInFrames={D.brief}>
          <BriefScene bassIntensity={bass} />
        </TransitionSeries.Sequence>

        {/* 3. The cut in progress, on the same page */}
        <TransitionSeries.Sequence durationInFrames={D.cutting}>
          <CuttingScene bassIntensity={bass} />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: FADE })}
        />

        {/* 4. Review — the contact sheet, the inspector, the stories */}
        <TransitionSeries.Sequence durationInFrames={D.review}>
          <ReviewScene bassIntensity={bass} />
        </TransitionSeries.Sequence>

        {/* 5. Change it — swap, remove, save a revision */}
        <TransitionSeries.Sequence durationInFrames={D.edit}>
          <EditScene bassIntensity={bass} />
        </TransitionSeries.Sequence>

        {/* 6. Render revision 1 */}
        <TransitionSeries.Sequence durationInFrames={D.render}>
          <RenderScene bassIntensity={bass} />
        </TransitionSeries.Sequence>

        {/* 7. The film on the page */}
        <TransitionSeries.Sequence durationInFrames={D.film}>
          <FilmScene bassIntensity={bass} />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={linearTiming({ durationInFrames: SLIDE })}
        />

        {/* 8. Runs — every run kept, the film's first */}
        <TransitionSeries.Sequence durationInFrames={D.runs}>
          <RunsScene bassIntensity={bass} />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={linearTiming({ durationInFrames: SLIDE })}
        />

        {/* 9. Suggestions — what it would make next, on its own */}
        <TransitionSeries.Sequence durationInFrames={D.suggestions}>
          <SuggestionsScene bassIntensity={bass} />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: FADE })}
        />

        {/* 10. CLI — its final `open` leads straight into the rendered film */}
        <TransitionSeries.Sequence durationInFrames={D.cli}>
          <CliScene />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: FADE })}
        />

        {/* 11. The film it made, last: full bleed, real time */}
        <TransitionSeries.Sequence durationInFrames={D.output}>
          <OutputPreviewScene frames={D.output} />
        </TransitionSeries.Sequence>
      </TransitionSeries>
    </AbsoluteFill>
  );
};
