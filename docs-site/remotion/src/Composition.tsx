import { AbsoluteFill } from "remotion";
import { Audio } from "@remotion/media";
import { staticFile, interpolate } from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { COLORS } from "./theme";
import { SCENE_FRAMES as D, FADE, SLIDE, FILM_TRANSITION, CLOSING_TRANSITION,
  MUSIC_FADE_START, MUSIC_FADE_END } from "./timeline";
import { DemoHeading } from "./components/DemoHeading";
import { ClosingScene } from "./scenes/ClosingScene";
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

export const DemoVideo: React.FC<{theme: "light" | "dark"}> = ({theme}) => {

  // Ease the soundtrack in, then fade out over the closing frame, leaving half a second of silence.
  const musicVolume = (f: number) =>
    interpolate(f, [0, 30, MUSIC_FADE_START, MUSIC_FADE_END], [0, 0.7, 0.7, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });

  return (
    <AbsoluteFill data-theme={theme} style={{ backgroundColor: COLORS.bg }}>
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
          <BriefScene />
          <DemoHeading title="Choose what the film covers" />
        </TransitionSeries.Sequence>

        {/* 3. The cut in progress, on the same page */}
        <TransitionSeries.Sequence durationInFrames={D.cutting}>
          <CuttingScene />
          <DemoHeading title="Let the app prepare a cut" note="Preparation sped up" />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: FADE })}
        />

        {/* 4. Review — the contact sheet, the inspector, the stories */}
        <TransitionSeries.Sequence durationInFrames={D.review}>
          <ReviewScene />
          <DemoHeading title="See what made the cut, and why" />
        </TransitionSeries.Sequence>

        {/* 5. Change it — swap, remove, save a revision */}
        <TransitionSeries.Sequence durationInFrames={D.edit}>
          <EditScene />
          <DemoHeading title="Change the cut before rendering" />
        </TransitionSeries.Sequence>

        {/* 6. Render revision 1 */}
        <TransitionSeries.Sequence durationInFrames={D.render}>
          <RenderScene />
          <DemoHeading title="Render the revision you reviewed" note="Render sped up" />
        </TransitionSeries.Sequence>

        {/* 7. The film on the page */}
        <TransitionSeries.Sequence durationInFrames={D.film}>
          <FilmScene />
          <DemoHeading title="Play the finished film" />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={linearTiming({ durationInFrames: SLIDE })}
        />

        {/* 8. Runs — every run kept, the film's first */}
        <TransitionSeries.Sequence durationInFrames={D.runs}>
          <RunsScene />
          <DemoHeading title="Keep your films and their cuts" />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={linearTiming({ durationInFrames: SLIDE })}
        />

        {/* 9. Suggestions — what it would make next, on its own */}
        <TransitionSeries.Sequence durationInFrames={D.suggestions}>
          <SuggestionsScene />
          <DemoHeading title="See what automation would make next" />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: FADE })}
        />

        {/* 10. CLI — its final `open` leads straight into the rendered film */}
        <TransitionSeries.Sequence durationInFrames={D.cli}>
          <CliScene />
          <DemoHeading title="Use the same workflow from your terminal" note="Run sped up" />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: FILM_TRANSITION })}
        />

        {/* 11. The film it made, last: full bleed, real time */}
        <TransitionSeries.Sequence durationInFrames={D.output}>
          <OutputPreviewScene />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: CLOSING_TRANSITION })}
        />
        <TransitionSeries.Sequence durationInFrames={D.closing}>
          <ClosingScene />
        </TransitionSeries.Sequence>
      </TransitionSeries>
    </AbsoluteFill>
  );
};
