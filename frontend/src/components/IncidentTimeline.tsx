import { useEffect, useRef } from "react";
import type { TimelineEntry } from "../types";

interface IncidentTimelineProps {
  entries: TimelineEntry[];
}

const iconColorMap: Record<string, string> = {
  "●": "var(--text-mono)",
  "◎": "var(--urgent)",
  "✓": "var(--ok)",
  "⚡": "#a16207",
  "⚠": "var(--urgent)",
  "✗": "var(--critical)",
};

function iconColor(icon: string): string {
  return iconColorMap[icon] ?? "var(--text-secondary)";
}

export default function IncidentTimeline({ entries }: IncidentTimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [entries.length]);

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        borderTop: "1px solid var(--border-dim)",
      }}
    >
      <div
        style={{
          padding: "12px 14px 6px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span className="panel-header">Incident Timeline</span>
        <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>
          WS:&nbsp;<span style={{ color: "var(--ok)" }}>● CONNECTED</span>
        </span>
      </div>
      <div
        ref={scrollRef}
        style={{ flex: 1, overflowY: "auto", padding: "4px 14px 14px" }}
      >
        {entries.length === 0 && (
          <div
            className="mono"
            style={{ fontSize: 11, color: "var(--text-dim)", fontStyle: "italic", padding: "8px 0" }}
          >
            Awaiting events…
          </div>
        )}
        {entries.map((e, i) => {
          const totalS = Math.floor(e.t);
          const mm = String(Math.floor(totalS / 60)).padStart(2, "0");
          const ss = String(totalS % 60).padStart(2, "0");
          return (
            <div
              key={i}
              className="mono"
              style={{
                display: "flex",
                gap: 10,
                padding: "4px 0",
                fontSize: 11.5,
                alignItems: "baseline",
                lineHeight: 1.4,
              }}
            >
              <span
                style={{
                  color: iconColor(e.icon),
                  width: 12,
                  textAlign: "center",
                  fontSize: 13,
                }}
              >
                {e.icon}
              </span>
              <span style={{ color: "var(--text-dim)", width: 44 }}>
                {mm}:{ss}
              </span>
              <span style={{ color: "var(--text-mono)", flex: 1 }}>{e.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
