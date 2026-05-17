import React, { useEffect, useRef, useMemo } from "react";
import type { TranscriptEntry } from "../types";

interface TranscriptFeedProps {
  entries: TranscriptEntry[];
  live: boolean;
}

interface TranscriptGroup {
  speaker: string;
  t: number;
  endT: number;
  words: TranscriptEntry[];
}

export default function TranscriptFeed({ entries, live }: TranscriptFeedProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [entries.length]);

  // Group by consecutive speaker
  const groups = useMemo<TranscriptGroup[]>(() => {
    const out: TranscriptGroup[] = [];
    for (const e of entries) {
      const last = out[out.length - 1];
      if (last && last.speaker === e.speaker && e.t - last.endT < 2.5) {
        last.words.push(e);
        last.endT = e.t;
      } else {
        out.push({ speaker: e.speaker, t: e.t, endT: e.t, words: [e] });
      }
    }
    return out;
  }, [entries]);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div
        style={{
          padding: "12px 14px 6px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          borderBottom: "1px solid var(--border-dim)",
        }}
      >
        <span className="panel-header">Live Transcript</span>
        <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>
          AMAZON&nbsp;TRANSCRIBE&nbsp;·&nbsp;EN-US
        </span>
      </div>

      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "12px 14px",
          fontSize: 13.5,
          lineHeight: 1.55,
        }}
      >
        {groups.length === 0 && (
          <div style={{ color: "var(--text-dim)", fontSize: 12, fontStyle: "italic" }}>
            Awaiting first word…
          </div>
        )}
        {groups.map((g, gi) => {
          const isCaller = g.speaker === "CALLER";
          const sMm = String(Math.floor(g.t / 60)).padStart(2, "0");
          const sSs = String(Math.floor(g.t % 60)).padStart(2, "0");
          const isLastGroup = gi === groups.length - 1;
          return (
            <div key={gi} style={{ marginBottom: 14 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: 8,
                  marginBottom: 4,
                  fontSize: 10,
                  letterSpacing: "0.12em",
                  fontWeight: 600,
                }}
              >
                <span style={{ color: isCaller ? "#0369a1" : "#15803d" }}>{g.speaker}</span>
                <span className="mono" style={{ color: "var(--text-dim)", fontSize: 10 }}>
                  {sMm}:{sSs}
                </span>
              </div>
              <div style={{ color: isCaller ? "var(--text-primary)" : "var(--text-mono)" }}>
                {g.words.map((w, wi) => {
                  const isLastWord = isLastGroup && wi === g.words.length - 1;
                  const cls = w.kw ? `kw kw-${w.kw}` : "";
                  return (
                    <React.Fragment key={wi}>
                      <span className={"word-in " + cls}>{w.text}</span>
                      {!isLastWord && " "}
                      {isLastWord && live && (
                        <span
                          className="cursor-blink mono"
                          style={{ color: "#0f172a", marginLeft: 2 }}
                        >
                          ▌
                        </span>
                      )}
                    </React.Fragment>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
