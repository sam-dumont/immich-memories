import React from "react";
import { Img, staticFile } from "remotion";
import {
  mdiArrowLeft,
  mdiArrowULeftTop,
  mdiContentCut,
  mdiContentSaveOutline,
  mdiDeleteOutline,
  mdiPause,
  mdiPlay,
  mdiSwapHorizontal,
  mdiUndo,
} from "@mdi/js";
import { UI } from "../theme";
import { Mdi } from "./Mdi";
import { Badge, Button, Heading } from "./ui";
import { RenderPanel, type RenderState } from "./RenderPanel";
import { HEADER_H, MAIN_X } from "./AppShell";
import { TITLE_H } from "./WindowFrame";
import {
  CUT_CONTENT_SECONDS,
  CUT_FILM_SECONDS,
  POOL,
  SHOTS,
  STORIES,
  THESIS,
  type Shot,
} from "../fixture";

/**
 * web/src/routes/runs/[run_id]/+page.svelte and lib/ShotInspector.svelte: the
 * cut as a contact sheet in playback order (or as its weighed stories), the
 * picture under review beside it, and the edit bar once something changed.
 */

export const RUN_ID = "20260927_101204_7c1e";

// Fixed geometry, so the scenes' cursors land on what they click. Measured in
// the window's content area, the page scrolled to its top.
export const SHEET_W = 863;
export const INSPECTOR_X = SHEET_W + 32;
export const INSPECTOR_W = 384;
export const GRID_Y = 346;
export const CARD_W = (SHEET_W - 4 * 12) / 5;
export const CARD_H = 184;
export const ROW_Y = GRID_Y + 28 + 16;
export const PLAYER_H = INSPECTOR_W * 0.75;
export const TOGGLE_Y = 288;

/** Where shot `index`'s card sits, from the main column's left edge. */
export const cardAt = (index: number) => ({
  x: (index % 5) * (CARD_W + 12),
  y: ROW_Y + Math.floor(index / 5) * (CARD_H + 16),
});

export const clock = (seconds: number) => {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
};

const WEIGHTS: Record<string, string> = {
  dominant: "Main story",
  major: "Important",
  minor: "Supporting",
  glimpse: "Small moment",
};

/** The pool's other views of a shot's subject (home-rain-window-02 for -01), with what the cut did with each. */
export const alternativesOf = (shot: Shot) => {
  const subject = shot.picture.replace(/-\d+\.jpg$/, "");
  return POOL.filter(
    (card) =>
      card.picture !== shot.picture &&
      card.picture.replace(/-\d+\.jpg$/, "") === subject,
  );
};

export type RunPageState = {
  view: "sheet" | "stories";
  selected: number;
  removed: number[];
  /** Shot index → the picture now playing in its place. */
  swapped: Record<number, string>;
  /** The alternative open beside the shot in the inspector. */
  comparing?: string;
  /** The edit bar's height, once something changed: it keeps its place in the page while it floats. */
  barHeight?: number;
  /** The saved revision, listed under the sheet. */
  revision?: boolean;
  render?: RenderState;
  /** Scene frame, for the playing preview. */
  frame: number;
  press?: { remove?: number; swap?: number; stories?: number };
};

const muted: React.CSSProperties = { color: UI.gray600 };
const caps: React.CSSProperties = {
  fontSize: 12,
  lineHeight: "16px",
  fontWeight: 600,
  letterSpacing: "0.025em",
  textTransform: "uppercase",
  color: UI.gray600,
};

const Header: React.FC = () => (
  <div
    style={{ display: "flex", flexDirection: "column", gap: 12, height: 168 }}
  >
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 4,
        fontSize: 14,
        height: 20,
        ...muted,
      }}
    >
      <Mdi path={mdiArrowLeft} size={16} />
      Back to runs
    </div>
    <div style={{ display: "flex", alignItems: "center", gap: 12, height: 36 }}>
      <Heading size="large">Monthly Highlights</Heading>
      <Badge color="success">Completed</Badge>
    </div>
    <div
      style={{ display: "flex", gap: 12, fontSize: 14, height: 20, ...muted }}
    >
      <span>{RUN_ID}</span>
      <span>Manual</span>
      <span>Pictures: {SHOTS.length}</span>
      <span>Videos: {SHOTS.filter((shot) => shot.motion).length}</span>
      <span>{clock(CUT_CONTENT_SECONDS)} of pictures and video</span>
      <span>about {clock(CUT_FILM_SECONDS)} of film</span>
    </div>
    <div style={{ maxWidth: 896, fontSize: 18, lineHeight: "28px" }}>
      {THESIS}
    </div>
  </div>
);

const Toolbar: React.FC<{ view: RunPageState["view"]; pressed: number }> = ({
  view,
  pressed,
}) => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      height: 34,
      marginTop: 24,
    }}
  >
    <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
      <div
        style={{
          display: "flex",
          border: `1px solid ${UI.gray200}`,
          borderRadius: 999,
          padding: 2,
        }}
      >
        {(["sheet", "stories"] as const).map((value) => (
          <div
            key={value}
            style={{
              borderRadius: 999,
              padding: "4px 12px",
              fontSize: 14,
              lineHeight: "20px",
              background: view === value ? UI.primary : "transparent",
              color: view === value ? UI.light : UI.gray600,
              transform:
                value === "stories"
                  ? `scale(${1 - pressed * 0.05})`
                  : undefined,
            }}
          >
            {value === "sheet" ? "Contact sheet" : "Stories"}
          </div>
        ))}
      </div>
      {view === "sheet" && (
        <div style={{ display: "flex", gap: 8 }}>
          <Button size="small" round>
            All pictures
          </Button>
          <Button size="small" round variant="outline" color="secondary">
            Videos
          </Button>
          <Button size="small" round variant="outline" color="secondary">
            Stills
          </Button>
        </div>
      )}
    </div>
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <span style={{ fontSize: 14, ...muted }}>
        Order and timecodes from the saved cut.
      </span>
      <Button size="small" variant="outline">
        Pool
      </Button>
    </div>
  </div>
);

const Chip: React.FC<{
  children: React.ReactNode;
  style: React.CSSProperties;
}> = ({ children, style }) => (
  <span
    style={{
      position: "absolute",
      display: "flex",
      alignItems: "center",
      gap: 2,
      borderRadius: 4,
      padding: "0 6px",
      fontSize: 11,
      lineHeight: "16px",
      fontWeight: 600,
      fontVariantNumeric: "tabular-nums",
      ...style,
    }}
  >
    {children}
  </span>
);

const ShotCard: React.FC<{
  shot: Shot;
  index: number;
  selected: boolean;
  removed: boolean;
  playing: string;
  newDay: boolean;
}> = ({ shot, index, selected, removed, playing, newDay }) => (
  <div
    style={{
      width: CARD_W,
      height: CARD_H,
      boxSizing: "border-box",
      padding: 4,
      borderRadius: 12,
      display: "flex",
      flexDirection: "column",
      gap: 6,
      background: selected ? UI.primaryTint : "transparent",
      boxShadow: selected ? `0 0 0 2px ${UI.primary}` : "none",
    }}
  >
    <div
      style={{
        position: "relative",
        height: (CARD_W - 8) * 0.75,
        borderRadius: 8,
        overflow: "hidden",
        background: UI.gray100,
      }}
    >
      <Img
        src={staticFile(playing)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          opacity: removed ? 0.3 : 1,
          filter: removed ? "grayscale(1)" : undefined,
        }}
      />
      {removed && (
        <span
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: "50%",
            transform: "translateY(-50%)",
            textAlign: "center",
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          Removed
        </span>
      )}
      {!removed && playing !== shot.picture && (
        <Chip
          style={{ top: 4, right: 4, background: UI.primary, color: UI.light }}
        >
          Swapped
        </Chip>
      )}
      <Chip
        style={{
          top: 4,
          left: 4,
          background: "rgba(0,0,0,0.6)",
          color: "#fff",
        }}
      >
        {index + 1}
      </Chip>
      <Chip
        style={{
          bottom: 4,
          right: 4,
          background: "rgba(0,0,0,0.6)",
          color: "#fff",
          fontWeight: 400,
        }}
      >
        {shot.motion && <Mdi path={mdiPlay} size={12} />}
        {shot.seconds.toFixed(1)} s
      </Chip>
    </div>
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        padding: "0 2px",
        fontSize: 11,
        lineHeight: "16px",
        fontVariantNumeric: "tabular-nums",
        ...muted,
      }}
    >
      <span style={newDay ? { fontWeight: 600, color: UI.dark } : undefined}>
        {shot.day}
      </span>
      <span>{clock(shot.start)}</span>
    </div>
    <div
      style={{
        padding: "0 2px",
        fontSize: 12,
        lineHeight: "16px",
        display: "-webkit-box",
        WebkitLineClamp: 2,
        WebkitBoxOrient: "vertical",
        overflow: "hidden",
      }}
    >
      {shot.reason}
    </div>
  </div>
);

const Sheet: React.FC<{ state: RunPageState }> = ({ state }) => (
  <div style={{ width: SHEET_W, flexShrink: 0 }}>
    <div
      style={{
        height: 28,
        paddingTop: 8,
        fontSize: 14,
        lineHeight: "20px",
        fontWeight: 600,
      }}
    >
      {SHOTS[0].chapter}
    </div>
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(5, ${CARD_W}px)`,
        columnGap: 12,
        rowGap: 16,
        marginTop: 16,
      }}
    >
      {SHOTS.map((shot, i) => (
        <ShotCard
          key={shot.picture}
          shot={shot}
          index={i}
          selected={state.selected === i}
          removed={state.removed.includes(i)}
          playing={state.swapped[i] ?? shot.picture}
          newDay={i === 0 || SHOTS[i - 1].day !== shot.day}
        />
      ))}
    </div>
  </div>
);

const Stories: React.FC<{ selected: number }> = ({ selected }) => (
  <div
    style={{
      width: SHEET_W,
      flexShrink: 0,
      display: "flex",
      flexDirection: "column",
      gap: 16,
    }}
  >
    {STORIES.map((story) => {
      const carriers = SHOTS.filter((shot) => shot.story === story.title);
      return (
        <div
          key={story.title}
          style={{
            border: `1px solid ${UI.gray200}`,
            borderRadius: 16,
            padding: 16,
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
            <Heading size="tiny">{story.title}</Heading>
            <Badge
              color={story.weight === "dominant" ? "primary" : "secondary"}
            >
              {WEIGHTS[story.weight]}
            </Badge>
            <span style={{ fontSize: 14, ...muted }}>{carriers[0]?.day}</span>
            <span style={{ fontSize: 14, ...muted }}>
              Pictures: {carriers.length}
            </span>
          </div>
          <div style={{ fontSize: 14 }}>{story.purpose}</div>
          <div style={{ display: "flex", gap: 8 }}>
            {carriers.map((shot) => {
              const chosen = SHOTS.indexOf(shot) === selected;
              return (
                <div
                  key={shot.picture}
                  style={{
                    width: 122,
                    padding: 4,
                    borderRadius: 8,
                    display: "flex",
                    flexDirection: "column",
                    gap: 4,
                    background: chosen ? UI.primaryTint : "transparent",
                    boxShadow: chosen ? `0 0 0 2px ${UI.primary}` : "none",
                  }}
                >
                  <div
                    style={{
                      position: "relative",
                      height: 114 * 0.75,
                      borderRadius: 6,
                      overflow: "hidden",
                      background: UI.gray100,
                    }}
                  >
                    <Img
                      src={staticFile(shot.picture)}
                      style={{
                        width: "100%",
                        height: "100%",
                        objectFit: "contain",
                      }}
                    />
                    {shot.motion && (
                      <Chip
                        style={{
                          right: 4,
                          bottom: 4,
                          padding: 2,
                          background: "rgba(0,0,0,0.6)",
                          color: "#fff",
                        }}
                      >
                        <Mdi path={mdiPlay} size={12} />
                      </Chip>
                    )}
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      lineHeight: "14px",
                      height: 28,
                      overflow: "hidden",
                    }}
                  >
                    {shot.reason}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      );
    })}
  </div>
);

/** A playing <video controls>: the picture, a slow push, and the browser's own control strip. */
const Player: React.FC<{
  picture: string;
  frame: number;
  interval: [number, number];
}> = ({ picture, frame, interval }) => {
  const span = interval[1] - interval[0];
  const at = interval[0] + ((frame / 30) % span);
  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        overflow: "hidden",
      }}
    >
      <Img
        src={staticFile(picture)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          transform: `scale(${1 + ((at - interval[0]) / span) * 0.06})`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: 44,
          background: "linear-gradient(transparent, rgba(0,0,0,0.55))",
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 12px 0",
          color: "#fff",
          fontSize: 12,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        <Mdi path={mdiPause} size={18} />
        <span>0:{String(Math.floor(at)).padStart(2, "0")} / 0:08</span>
        <div
          style={{
            flex: 1,
            height: 3,
            borderRadius: 2,
            background: "rgba(255,255,255,0.35)",
          }}
        >
          <div
            style={{
              width: `${(at / 8) * 100}%`,
              height: "100%",
              borderRadius: 2,
              background: "#fff",
            }}
          />
        </div>
      </div>
    </div>
  );
};

// The stretch the cut plays of each video shot, in the clip's own seconds.
const STRETCH: [number, number] = [1.2, 4.75];

const Inspector: React.FC<{ state: RunPageState }> = ({ state }) => {
  const shot = SHOTS[state.selected];
  const playing = state.swapped[state.selected] ?? shot.picture;
  const swapped = playing !== shot.picture;
  const removed = state.removed.includes(state.selected);
  const alternatives = alternativesOf(shot);
  const compared = alternatives.find(
    (card) => card.picture === state.comparing,
  );
  const video = shot.motion && !swapped;

  return (
    <div
      style={{
        width: INSPECTOR_W,
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        gap: 20,
      }}
    >
      <div
        style={{
          height: PLAYER_H,
          borderRadius: 16,
          overflow: "hidden",
          background: UI.gray100,
        }}
      >
        {video ? (
          <Player picture={playing} frame={state.frame} interval={STRETCH} />
        ) : (
          <Img
            src={staticFile(playing)}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "contain",
              opacity: removed ? 0.4 : 1,
            }}
          />
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <Button
            size="small"
            variant="outline"
            color={removed ? "primary" : "danger"}
            icon={removed ? mdiArrowULeftTop : mdiDeleteOutline}
            pressed={state.press?.remove ?? 0}
          >
            {removed ? "Put it back" : "Remove from this cut"}
          </Button>
          {swapped && (
            <Button size="small" variant="outline" icon={mdiArrowULeftTop}>
              Keep the original
            </Button>
          )}
        </div>
        {!removed && video && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 14,
            }}
          >
            <Button size="small" variant="ghost" icon={mdiContentCut}>
              Start here
            </Button>
            <Button size="small" variant="ghost" icon={mdiContentCut}>
              End here
            </Button>
            <span style={{ fontVariantNumeric: "tabular-nums" }}>
              1.2–4.8 s
            </span>
          </div>
        )}
        {!removed && !shot.motion && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 14,
              height: 30,
            }}
          >
            Screen time (seconds)
            <div
              style={{
                width: 80,
                boxSizing: "border-box",
                border: `1px solid ${UI.gray300}`,
                borderRadius: 6,
                padding: "4px 8px",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {shot.seconds.toFixed(1)}
            </div>
          </div>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            fontSize: 14,
            fontVariantNumeric: "tabular-nums",
            ...muted,
          }}
        >
          <span style={{ fontWeight: 600, color: UI.dark }}>
            #{state.selected + 1}
          </span>
          <span>{clock(shot.start)}</span>
          <span>{shot.day}</span>
          <span>{shot.seconds.toFixed(1)} s on screen</span>
          <Badge size="tiny" color={shot.motion ? "info" : "secondary"}>
            {shot.motion ? "Video" : "Still"}
          </Badge>
        </div>
        <Heading size="small">{shot.story}</Heading>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={caps}>Why this picture</div>
        <div style={{ fontSize: 16, lineHeight: "24px" }}>{shot.reason}</div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={caps}>How the rules got here</div>
        <div style={{ fontSize: 14, lineHeight: "20px" }}>
          Kept at the picture review
        </div>
        <div style={{ fontSize: 14, lineHeight: "20px", ...muted }}>
          {shot.motion ? "video" : "still"}, {shot.day}
        </div>
      </div>

      {alternatives.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={caps}>Other pictures of this moment</div>
          <div style={{ fontSize: 12, lineHeight: "16px", ...muted }}>
            Eligible when this shot was chosen. Open one to compare.
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {alternatives.map((card) => (
              <div
                key={card.picture}
                style={{
                  width: 96,
                  height: 80,
                  borderRadius: 8,
                  overflow: "hidden",
                  background: UI.gray100,
                  boxShadow:
                    card.picture === state.comparing
                      ? `0 0 0 2px ${UI.primary}`
                      : "none",
                }}
              >
                <Img
                  src={staticFile(card.picture)}
                  style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "contain",
                  }}
                />
              </div>
            ))}
          </div>
          {compared && (
            <>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 8,
                }}
              >
                {[
                  {
                    picture: shot.picture,
                    caption: (
                      <span style={{ fontWeight: 500 }}>In the cut</span>
                    ),
                  },
                  {
                    picture: compared.picture,
                    caption: (
                      <>
                        <span style={{ fontWeight: 500 }}>
                          still, {shot.day}
                        </span>{" "}
                        {compared.outcome}
                      </>
                    ),
                  },
                ].map((figure) => (
                  <div
                    key={figure.picture}
                    style={{ display: "flex", flexDirection: "column", gap: 4 }}
                  >
                    <div
                      style={{
                        height: 188 * 0.75,
                        borderRadius: 8,
                        overflow: "hidden",
                        background: UI.gray100,
                      }}
                    >
                      <Img
                        src={staticFile(figure.picture)}
                        style={{
                          width: "100%",
                          height: "100%",
                          objectFit: "contain",
                        }}
                      />
                    </div>
                    <div style={{ fontSize: 12, lineHeight: "16px" }}>
                      {figure.caption}
                    </div>
                  </div>
                ))}
              </div>
              {playing !== compared.picture && (
                <Button
                  size="small"
                  variant="outline"
                  icon={mdiSwapHorizontal}
                  pressed={state.press?.swap ?? 0}
                >
                  Use this picture instead
                </Button>
              )}
            </>
          )}
          <div style={{ fontSize: 14, color: UI.primary }}>
            Browse the whole pool
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={caps}>Model polish</div>
        <div style={{ fontSize: 14, ...muted }}>
          No model read this cut: the rules chose every picture.
        </div>
      </div>
    </div>
  );
};

/** Where the sheet's four rows end, and so where the edit bar sits in the page. */
export const SHEET_BOTTOM = ROW_Y + 4 * (CARD_H + 16) - 16;
export const BAR_Y = SHEET_BOTTOM + 24;
export const BAR_H = 62;
export const BAR_SAVED_H = BAR_H + 32;

const Revisions: React.FC<{ seconds: number }> = ({ seconds }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
    <Heading size="tiny">Revisions</Heading>
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        fontSize: 14,
        fontVariantNumeric: "tabular-nums",
      }}
    >
      <span style={{ fontWeight: 500 }}>Revision 1</span>
      <span style={muted}>Sep 27, 2026, 10:14 AM</span>
      <span>{clock(seconds)}</span>
      <Button size="tiny" variant="ghost">
        Open
      </Button>
    </div>
  </div>
);

const RunDetails: React.FC = () => (
  <div
    style={{
      borderTop: `1px solid ${UI.gray200}`,
      paddingTop: 24,
      display: "flex",
      flexDirection: "column",
      gap: 12,
      fontSize: 14,
    }}
  >
    <Heading size="tiny">Run details</Heading>
    <div>Immich delivery: not requested</div>
  </div>
);

/** The whole run page: header, sheet and inspector, then revisions, the render panel and the run's details. */
export const RunPage: React.FC<{ state: RunPageState }> = ({ state }) => (
  <div style={{ display: "flex", flexDirection: "column" }}>
    <Header />
    <Toolbar view={state.view} pressed={state.press?.stories ?? 0} />
    <div
      style={{
        display: "flex",
        gap: 32,
        marginTop: 24,
        alignItems: "flex-start",
      }}
    >
      {state.view === "sheet" ? (
        <Sheet state={state} />
      ) : (
        <Stories selected={state.selected} />
      )}
      <Inspector state={state} />
    </div>
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 24,
        marginTop: 24,
      }}
    >
      {state.barHeight !== undefined && (
        <div style={{ height: state.barHeight }} />
      )}
      {state.revision && <Revisions seconds={contentSeconds(state.removed)} />}
      <RenderPanel
        runId={RUN_ID}
        state={state.render ?? { revision: false, addDate: false }}
      />
      <RunDetails />
    </div>
  </div>
);

/**
 * The edit bar where `sticky bottom-4` puts it: in its place in the page, or
 * floating 16 px above the viewport's bottom while that place is below it.
 */
const barTop = (
  scroll: number,
  height: number,
  natural: number,
  viewport = 864,
) => Math.min(natural - scroll, viewport - 16 - height);

/** The edit bar laid over the window's content area, clipped to the page below the header. */
export const FloatingEditBar: React.FC<{
  scroll: number;
  natural?: number;
  count: number;
  removed: number[];
  budget: number;
  saved: boolean;
  savePressed: number;
}> = ({
  scroll,
  natural = BAR_Y,
  count,
  removed,
  budget,
  saved,
  savePressed,
}) => (
  <div
    style={{
      position: "absolute",
      left: 0,
      top: TITLE_H + HEADER_H,
      width: 1600,
      height: 864 - HEADER_H,
      overflow: "hidden",
      pointerEvents: "none",
    }}
  >
    <div
      style={{
        position: "absolute",
        left: MAIN_X,
        width: 1279,
        top: barTop(scroll, saved ? BAR_SAVED_H : BAR_H, natural) - HEADER_H,
      }}
    >
      <EditBar
        count={count}
        seconds={contentSeconds(removed)}
        budget={budget}
        saved={saved}
        savePressed={savePressed}
      />
    </div>
  </div>
);

/** The seconds the pictures now fill, after removals: the edit bar's first number. */
export const contentSeconds = (removed: number[]) =>
  removed.reduce((sum, i) => sum - SHOTS[i].seconds, CUT_CONTENT_SECONDS);

/** The sticky edit bar at the bottom of the viewport, as the page shows it once there is a change. */
export const EditBar: React.FC<{
  count: number;
  seconds: number;
  budget: number;
  saved: boolean;
  savePressed: number;
}> = ({ count, seconds, budget, saved, savePressed }) => (
  <div
    style={{
      display: "flex",
      flexWrap: "wrap",
      alignItems: "center",
      columnGap: 12,
      rowGap: 12,
      border: `1px solid ${UI.gray200}`,
      borderRadius: 16,
      padding: 12,
      background: "rgba(255,255,255,0.95)",
      boxShadow:
        "0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1)",
    }}
  >
    <span style={{ fontSize: 14, fontVariantNumeric: "tabular-nums" }}>
      Changes: {count} · {clock(seconds)} of {clock(budget)} the titles leave
    </span>
    <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
      <Button size="small" variant="ghost" icon={mdiUndo}>
        Undo
      </Button>
      <Button size="small" variant="ghost">
        Discard changes
      </Button>
      <Button
        size="small"
        icon={mdiContentSaveOutline}
        disabled={saved}
        pressed={savePressed}
      >
        Save revision
      </Button>
    </div>
    {saved && (
      <span style={{ width: "100%", fontSize: 14, color: UI.success }}>
        Saved as revision 1.
      </span>
    )}
  </div>
);
