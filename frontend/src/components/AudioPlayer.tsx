import React from "react";
import Waveform from "./Waveform";
import icons from "./Icon";

interface AudioPlayerProps {
  playing: boolean;
  onTogglePlay: () => void;
  onStop: () => void;
  elapsedMs: number;
  totalMs: number;
  wordPulses: React.MutableRefObject<Array<{ at: number; idx: number }>>;
  demoMode: boolean;
  audioFileName: string | null;
}

export default function AudioPlayer({
  playing,
  onTogglePlay,
  onStop,
  elapsedMs,
  totalMs,
  wordPulses,
  demoMode,
  audioFileName,
}: AudioPlayerProps) {
  const totalS = Math.floor(elapsedMs / 1000);
  const mm = String(Math.floor(totalS / 60)).padStart(2, "0");
  const ss = String(totalS % 60).padStart(2, "0");
  const ttS = Math.floor(totalMs / 1000);
  const tmm = String(Math.floor(ttS / 60)).padStart(2, "0");
  const tss = String(ttS % 60).padStart(2, "0");

  const sourceLabel = demoMode
    ? "SIM_CARDIAC_ARREST.JSON"
    : audioFileName
    ? audioFileName.toUpperCase().slice(0, 28)
    : "AMAZON TRANSCRIBE · EN-US";

  return (
    <div className="panel-flush" style={{ padding: 12 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 4,
        }}
      >
        <span className="panel-header">911 Call Audio</span>
        <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>
          {sourceLabel}
        </span>
      </div>

      <div
        style={{
          background: "var(--bg-deep)",
          border: "1px solid var(--border-dim)",
          borderRadius: 4,
          padding: "6px 8px",
          marginTop: 8,
        }}
      >
        <Waveform playing={playing} paused={!playing} wordPulses={wordPulses} />
      </div>

      {/* Controls row */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
        {demoMode ? (
          <>
            <button
              className="btn"
              onClick={onTogglePlay}
              style={{
                width: 36,
                height: 36,
                borderRadius: 999,
                background: playing ? "rgba(59,130,246,0.15)" : "rgba(59,130,246,0.25)",
                border: "1px solid rgba(59,130,246,0.7)",
                color: "#1d4ed8",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
              title={playing ? "Pause (Space)" : "Play (Space)"}
            >
              {playing ? icons.pause({ size: 16 }) : icons.play({ size: 16 })}
            </button>
            <button
              className="btn"
              onClick={onStop}
              style={{
                width: 32,
                height: 32,
                borderRadius: 4,
                color: "var(--text-secondary)",
                border: "1px solid var(--border-bright)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
              title="Stop"
            >
              {icons.stop({ size: 12 })}
            </button>
            <div
              className="mono"
              style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-mono)" }}
            >
              {mm}:{ss}
              <span style={{ color: "var(--text-dim)" }}> / {tmm}:{tss}</span>
            </div>
          </>
        ) : (
          <>
            {/* Real mode: streaming indicator + stop */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "4px 10px",
                background: playing ? "rgba(37,99,235,0.08)" : "var(--bg-elevated)",
                border: "1px solid var(--border-dim)",
                borderRadius: 4,
                flex: 1,
              }}
            >
              <span style={{ color: playing ? "var(--running)" : "var(--text-dim)", fontSize: 11 }}>
                ●
              </span>
              <span
                className="mono"
                style={{
                  fontSize: 11,
                  color: playing ? "var(--running-text)" : "var(--text-dim)",
                  letterSpacing: "0.1em",
                }}
              >
                {playing ? "STREAMING" : "STANDBY"}
              </span>
              <span
                className="mono"
                style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-mono)" }}
              >
                {mm}:{ss}
              </span>
            </div>
            <button
              className="btn"
              onClick={onStop}
              style={{
                width: 32,
                height: 32,
                borderRadius: 4,
                color: "var(--text-secondary)",
                border: "1px solid var(--border-bright)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
              title="End Session"
            >
              {icons.stop({ size: 12 })}
            </button>
          </>
        )}
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginTop: 10,
          fontSize: 10,
          letterSpacing: "0.1em",
          color: "var(--text-secondary)",
          textTransform: "uppercase",
        }}
      >
        <span>Speakers</span>
        <span style={{ color: "#0369a1" }}>
          <span className="dot" style={{ background: "#2563eb", marginRight: 4 }} />
          Caller&nbsp;1
        </span>
        <span style={{ color: "#15803d" }}>
          <span className="dot" style={{ background: "#16a34a", marginRight: 4 }} />
          Dispatcher&nbsp;1
        </span>
        <span style={{ marginLeft: "auto", color: "var(--ok)" }}>● SPK&nbsp;DETECT</span>
      </div>
    </div>
  );
}
