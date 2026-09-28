import React from "react";
import { Img, staticFile } from "remotion";
import { mdiContentCopy, mdiStop } from "@mdi/js";
import { UI } from "../theme";
import { Button, CommandLine, ProgressBar } from "./ui";

/** web/src/lib/JobPanel.svelte: a running job's stage, bar, count, estimate and the pictures just read. */
export const JobPanel: React.FC<{
  label: string;
  elapsed: string;
  command: string;
  fraction?: number;
  done?: number;
  total?: number;
  /** The stage's own estimate, already worded ("~12s left in this stage"). */
  remaining?: string;
  /** The pictures just read, oldest first; the panel shows the last eight. */
  pictures?: string[];
  /** The newest picture's entry, 0..1, so the strip slides rather than jumps. */
  arriving?: number;
  running?: boolean;
}> = ({
  label,
  elapsed,
  command,
  fraction = 0,
  done,
  total,
  remaining,
  pictures = [],
  arriving = 1,
  running = true,
}) => {
  const shown = pictures.slice(-8);
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        border: `1px solid ${UI.gray200}`,
        borderRadius: 16,
        padding: 20,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span style={{ fontSize: 16, fontWeight: 500 }}>{label}</span>
        <span
          style={{
            fontSize: 14,
            color: UI.gray600,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {elapsed}
        </span>
      </div>

      {running && <ProgressBar fraction={fraction} />}
      {running && total !== undefined && (
        <div
          style={{
            fontSize: 14,
            color: UI.gray600,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {done ?? 0} of {total}
          {remaining ? ` · ${remaining}` : ""}
        </div>
      )}
      {running && shown.length > 0 && (
        <div
          style={{ display: "flex", gap: 8, overflow: "hidden", height: 64 }}
        >
          {shown.map((picture, i) => {
            const newest = i === shown.length - 1;
            return (
              <Img
                key={`${picture}-${pictures.length - shown.length + i}`}
                src={staticFile(picture)}
                style={{
                  width: 64,
                  height: 64,
                  flexShrink: 0,
                  borderRadius: 8,
                  objectFit: "cover",
                  opacity: newest ? arriving : 1,
                  transform: newest
                    ? `scale(${0.85 + 0.15 * arriving})`
                    : undefined,
                }}
              />
            );
          })}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <CommandLine style={{ flex: 1, minWidth: 0, padding: "4px 8px" }}>
          {command}
        </CommandLine>
        <Button size="small" variant="ghost" icon={mdiContentCopy}>
          Copy as CLI command
        </Button>
        {running && (
          <Button size="small" variant="outline" color="danger" icon={mdiStop}>
            Cancel
          </Button>
        )}
      </div>
    </div>
  );
};

/** The panel's own clock: "48s", then "1m 05s". */
export const elapsedLabel = (seconds: number) => {
  const whole = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(whole / 60);
  return minutes
    ? `${minutes}m ${String(whole % 60).padStart(2, "0")}s`
    : `${whole}s`;
};
