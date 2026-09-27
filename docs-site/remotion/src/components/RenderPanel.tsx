import React from "react";
import { Img, OffthreadVideo, staticFile } from "remotion";
import { mdiMusicNote, mdiPlay, mdiUpload } from "@mdi/js";
import { UI } from "../theme";
import { Mdi } from "./Mdi";
import { JobPanel } from "./JobPanel";
import { Button, Check, Field, Heading } from "./ui";

/**
 * web/src/lib/RenderPanel.svelte: what to render (the cut as chosen or a saved
 * revision) and how, then the render job, then the film on the page.
 */

export type RenderState = {
  revision: boolean;
  /** The "What to render" select, open with this option under the pointer. */
  open?: "cut" | "revision";
  addDate: boolean;
  renderPressed?: number;
  job?: { label: string; fraction: number; elapsed: string; done: boolean };
  /** The film element: its poster until playing, then the film from `from` seconds. */
  film?: { playing: boolean; from: number };
};

export const RENDER_COMMAND = (runId: string) =>
  `immich-memories runs render ${runId} --revision=1 --music-volume=0.5 --add-date`;

const Radio: React.FC<{ label: string; checked?: boolean }> = ({
  label,
  checked,
}) => (
  <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
    <div
      style={{
        width: 14,
        height: 14,
        borderRadius: 999,
        border: `${checked ? 4 : 1}px solid ${checked ? UI.primary : "#767676"}`,
        boxSizing: "border-box",
      }}
    />
    {label}
  </div>
);

const Options: React.FC<{ hover: "cut" | "revision" }> = ({ hover }) => (
  <div
    style={{
      position: "absolute",
      top: 70,
      left: 0,
      right: 0,
      background: UI.light,
      border: `1px solid ${UI.gray300}`,
      borderRadius: 8,
      boxShadow: "0 8px 24px rgba(0,0,0,0.15)",
      padding: 4,
      zIndex: 5,
      fontSize: 15,
    }}
  >
    {(
      [
        ["cut", "The cut as chosen"],
        ["revision", "Revision 1"],
      ] as const
    ).map(([key, label]) => (
      <div
        key={key}
        style={{
          padding: "6px 10px",
          borderRadius: 5,
          background: hover === key ? UI.primary : "transparent",
          color: hover === key ? UI.light : UI.dark,
        }}
      >
        {label}
      </div>
    ))}
  </div>
);

const Form: React.FC<{ state: RenderState }> = ({ state }) => (
  <div style={{ display: "grid", gridTemplateColumns: "376px 376px", gap: 16 }}>
    <div style={{ position: "relative" }}>
      <Field
        label="What to render"
        value={state.revision ? "Revision 1" : "The cut as chosen"}
        select
        focused={state.open !== undefined}
      />
      {state.open && <Options hover={state.open} />}
    </div>
    <Field label="Transition Style" value="As configured" select />
    <Field label="Title (decided as generate decides when empty)" value="" />
    <Field label="Subtitle" value="" />
    <Field label="Who names the film" value="As generate decides" select />
    <Field label="Orientation" value="Automatic" select />
    <Field label="Resolution" value="As configured" select />
    <Field label="Format" value="As configured" select />
    <Field label="Quality" value="As configured" select />
    <Field label="Scaling Mode" value="As configured" select />
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <Check label="Add date overlay" checked={state.addDate} />
      <Check label="Caption clips with their place" />
      <Check label="Privacy mode: blur every picture and scramble names" />
    </div>
    <div />
    <div
      style={{
        gridColumn: "span 2",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        height: 132,
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 600 }}>Music</div>
      <div style={{ display: "flex", gap: 8 }}>
        <Radio label="Automatic (as configured)" checked />
        <Radio label="No music" />
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <Button size="small" variant="outline" icon={mdiMusicNote}>
          Preview a track
        </Button>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            border: `1px solid ${UI.gray300}`,
            borderRadius: 8,
            padding: "6px 12px",
            fontSize: 14,
          }}
        >
          <Mdi path={mdiUpload} size={16} />
          Upload a track
        </div>
      </div>
      <div
        style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 14 }}
      >
        Music volume:
        <div
          style={{
            position: "relative",
            width: 192,
            height: 4,
            borderRadius: 2,
            background: UI.gray300,
          }}
        >
          <div
            style={{
              width: "50%",
              height: "100%",
              borderRadius: 2,
              background: UI.primary,
            }}
          />
          <div
            style={{
              position: "absolute",
              left: 88,
              top: -6,
              width: 16,
              height: 16,
              borderRadius: 999,
              background: UI.primary,
            }}
          />
        </div>
        <span>50%</span>
      </div>
    </div>
    <div style={{ gridColumn: "span 2" }}>
      <Check label="Upload the film to Immich" />
    </div>
    <Button pressed={state.renderPressed ?? 0}>Render</Button>
  </div>
);

/** The film element as the panel shows it once the render succeeded. */
const Film: React.FC<{ film: NonNullable<RenderState["film"]> }> = ({
  film,
}) => (
  <div
    style={{
      position: "relative",
      width: 768,
      height: 432,
      borderRadius: 16,
      overflow: "hidden",
      background: "#000",
    }}
  >
    {film.playing ? (
      <OffthreadVideo
        src={staticFile("output-preview.mp4")}
        startFrom={Math.round(film.from * 30)}
        muted
        style={{ width: "100%", height: "100%", objectFit: "contain" }}
      />
    ) : (
      <>
        {/* preload="metadata": the browser shows the film's first frame until Play. */}
        <Img
          src={staticFile("output-frame.jpg")}
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
        />
        <div
          style={{
            position: "absolute",
            left: 16,
            bottom: 14,
            display: "flex",
            alignItems: "center",
            gap: 10,
            color: "#fff",
            fontSize: 12,
          }}
        >
          <Mdi path={mdiPlay} size={22} />
          0:00 / 1:02
        </div>
      </>
    )}
  </div>
);

export const RenderPanel: React.FC<{ runId: string; state: RenderState }> = ({
  runId,
  state,
}) => (
  <div
    style={{
      borderTop: `1px solid ${UI.gray200}`,
      paddingTop: 24,
      display: "flex",
      flexDirection: "column",
      gap: 16,
    }}
  >
    <Heading size="tiny">Render</Heading>
    {state.job && (
      <div style={{ width: 768 }}>
        <JobPanel
          label={state.job.done ? "The film is ready." : state.job.label}
          elapsed={state.job.elapsed}
          command={RENDER_COMMAND(runId)}
          fraction={state.job.fraction}
          running={!state.job.done}
        />
      </div>
    )}
    {state.job?.done && state.film && (
      <>
        <Film film={state.film} />
        <div style={{ fontSize: 14, color: UI.primary }}>Open the film run</div>
      </>
    )}
    {(!state.job || state.job.done) && <Form state={state} />}
  </div>
);
