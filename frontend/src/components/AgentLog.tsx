import { useEffect, useRef } from "react";
import type { Agent, AgentId, AgentState, LogLine } from "../types";

interface AgentLogProps {
  agentId: AgentId | null;
  agent: Agent | null;
  logs: LogLine[];
  state: AgentState | null;
  onClose: () => void;
}

export default function AgentLog({ agentId, agent, logs, state, onClose }: AgentLogProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  if (!agentId || !agent) return null;

  return (
    <div
      style={{
        margin: "0 14px 12px",
        background: "var(--bg-deep)",
        border: "1px solid var(--border-dim)",
        borderRadius: 6,
        overflow: "hidden",
        maxHeight: 200,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          padding: "8px 12px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          borderBottom: "1px solid var(--border-dim)",
          background: "var(--bg-panel)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 11,
            letterSpacing: "0.1em",
            fontWeight: 600,
          }}
        >
          <span style={{ color: "#1d4ed8" }}>{agent.short}</span>
          <span style={{ color: "var(--text-dim)" }}>LOG</span>
          {state === "running" && (
            <span className="mono" style={{ fontSize: 10, color: "#a16207" }}>
              ● STREAMING
            </span>
          )}
          {state === "complete" && (
            <span className="mono" style={{ fontSize: 10, color: "var(--ok)" }}>
              ✓ COMPLETE
            </span>
          )}
        </div>
        <button
          className="btn"
          onClick={onClose}
          style={{ color: "var(--text-secondary)", fontSize: 11 }}
        >
          ✕ close
        </button>
      </div>
      <div
        ref={scrollRef}
        className="mono"
        style={{
          flex: 1,
          padding: "8px 12px",
          overflowY: "auto",
          fontSize: 11,
          lineHeight: 1.7,
          color: "var(--text-mono)",
        }}
      >
        {logs.length === 0 && (
          <div style={{ color: "var(--text-dim)", fontStyle: "italic" }}>
            No log entries yet. Agent is {state}.
          </div>
        )}
        {logs.map((l, i) => {
          const isOk = /COMPLETE|✓|accepting|found|best/i.test(l.text);
          const isWarn = /timeout|warn|redirect/i.test(l.text);
          const isErr = /error|fail|✗/i.test(l.text);
          let mark = "·";
          let markColor = "var(--text-dim)";
          if (isErr) {
            mark = "✗";
            markColor = "var(--critical)";
          } else if (isWarn) {
            mark = "!";
            markColor = "var(--urgent)";
          } else if (isOk) {
            mark = "✓";
            markColor = "var(--ok)";
          }
          return (
            <div key={i} style={{ display: "flex", gap: 8 }}>
              <span style={{ color: "#475569" }}>{l.ts}</span>
              <span style={{ color: markColor, width: 10, textAlign: "center" }}>{mark}</span>
              <span style={{ flex: 1 }}>{l.text}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
