import React, { useEffect, useRef, useState } from "react";
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
  audioObjectUrl?: string | null;
}

function fmt(ms: number) {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
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
  audioObjectUrl,
}: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [audioPlaying, setAudioPlaying] = useState(false);
  const [audioCurrent, setAudioCurrent] = useState(0);   // ms
  const [audioDuration, setAudioDuration] = useState(0); // ms

  // Sync audio element src when URL changes
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    if (audioObjectUrl) {
      el.src = audioObjectUrl;
      el.load();
    } else {
      el.src = "";
    }
  }, [audioObjectUrl]);

  // Wire audio element events
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const onPlay    = () => setAudioPlaying(true);
    const onPause   = () => setAudioPlaying(false);
    const onEnded   = () => setAudioPlaying(false);
    const onLoaded  = () => setAudioDuration(el.duration * 1000);
    const onTime    = () => setAudioCurrent(el.currentTime * 1000);
    el.addEventListener("play",             onPlay);
    el.addEventListener("pause",            onPause);
    el.addEventListener("ended",            onEnded);
    el.addEventListener("loadedmetadata",   onLoaded);
    el.addEventListener("timeupdate",       onTime);
    return () => {
      el.removeEventListener("play",           onPlay);
      el.removeEventListener("pause",          onPause);
      el.removeEventListener("ended",          onEnded);
      el.removeEventListener("loadedmetadata", onLoaded);
      el.removeEventListener("timeupdate",     onTime);
    };
  }, []);

  const toggleAudio = () => {
    // Notify parent first (triggers pipeline on first press)
    onTogglePlay();
    // Then drive the local audio element
    const el = audioRef.current;
    if (!el || !audioObjectUrl) return;
    audioPlaying ? el.pause() : el.play();
  };

  const sourceLabel = demoMode
    ? "SIM_CARDIAC_ARREST.JSON"
    : audioFileName
    ? audioFileName.toUpperCase().slice(0, 28)
    : "AMAZON TRANSCRIBE · EN-US";

  const hasAudio = Boolean(audioObjectUrl);

  return (
    <div className="panel-flush" style={{ padding: 12 }}>
      {/* hidden audio element */}
      <audio ref={audioRef} preload="metadata" />

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
        <Waveform playing={demoMode ? playing : audioPlaying} paused={demoMode ? !playing : !audioPlaying} wordPulses={wordPulses} />
      </div>

      {/* Controls row */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
        {demoMode ? (
          <>
            <button
              className="btn"
              onClick={onTogglePlay}
              style={{
                width: 36, height: 36, borderRadius: 999,
                background: playing ? "rgba(59,130,246,0.15)" : "rgba(59,130,246,0.25)",
                border: "1px solid rgba(59,130,246,0.7)",
                color: "#1d4ed8",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}
              title={playing ? "Pause (Space)" : "Play (Space)"}
            >
              {playing ? icons.pause({ size: 16 }) : icons.play({ size: 16 })}
            </button>
            <button
              className="btn"
              onClick={onStop}
              style={{
                width: 32, height: 32, borderRadius: 4,
                color: "var(--text-secondary)",
                border: "1px solid var(--border-bright)",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}
              title="Stop"
            >
              {icons.stop({ size: 12 })}
            </button>
            <div className="mono" style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-mono)" }}>
              {fmt(elapsedMs)}
              <span style={{ color: "var(--text-dim)" }}> / {fmt(totalMs)}</span>
            </div>
          </>
        ) : (
          <>
            {/* Play/pause the real audio file */}
            <button
              className="btn"
              onClick={toggleAudio}
              disabled={!hasAudio}
              style={{
                width: 36, height: 36, borderRadius: 999,
                background: audioPlaying ? "rgba(59,130,246,0.15)" : "rgba(59,130,246,0.25)",
                border: `1px solid ${hasAudio ? "rgba(59,130,246,0.7)" : "var(--border-dim)"}`,
                color: hasAudio ? "#1d4ed8" : "var(--text-dim)",
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: hasAudio ? "pointer" : "default",
              }}
              title={audioPlaying ? "Pause" : "Play audio"}
            >
              {audioPlaying ? icons.pause({ size: 16 }) : icons.play({ size: 16 })}
            </button>

            {/* Streaming / time indicator */}
            <div
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "4px 10px",
                background: playing ? "rgba(37,99,235,0.08)" : "var(--bg-elevated)",
                border: "1px solid var(--border-dim)",
                borderRadius: 4, flex: 1,
              }}
            >
              <span style={{ color: playing ? "var(--running)" : "var(--text-dim)", fontSize: 11 }}>●</span>
              <span
                className="mono"
                style={{ fontSize: 11, color: playing ? "var(--running-text)" : "var(--text-dim)", letterSpacing: "0.1em" }}
              >
                {playing ? "STREAMING" : "STANDBY"}
              </span>
              <span className="mono" style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-mono)" }}>
                {hasAudio
                  ? `${fmt(audioCurrent)} / ${audioDuration > 0 ? fmt(audioDuration) : "--:--"}`
                  : fmt(elapsedMs)}
              </span>
            </div>

            <button
              className="btn"
              onClick={onStop}
              style={{
                width: 32, height: 32, borderRadius: 4,
                color: "var(--text-secondary)",
                border: "1px solid var(--border-bright)",
                display: "flex", alignItems: "center", justifyContent: "center",
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
          display: "flex", alignItems: "center", gap: 12,
          marginTop: 10, fontSize: 10, letterSpacing: "0.1em",
          color: "var(--text-secondary)", textTransform: "uppercase",
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
