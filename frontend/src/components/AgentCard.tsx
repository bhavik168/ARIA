import icons from "./Icon";
import type { Agent, AgentState } from "../types";

interface AgentCardProps {
  agent: Agent;
  state: AgentState;
  onClick: () => void;
  selected: boolean;
  elapsedMs?: number;
}

const accentColors: Record<string, string> = {
  running:  "#2563eb",
  indigo:   "#4338ca",
  cyan:     "#0e7490",
  critical: "#dc2626",
  hazmat:   "#c2410c",
  ok:       "#16a34a",
  yellow:   "#b45309",
};

const stateLabels: Record<AgentState, { dot: string; label: string; color: string }> = {
  idle:      { dot: "○", label: "IDLE",      color: "var(--text-dim)" },
  listening: { dot: "●", label: "LISTENING", color: "#1d4ed8" },
  triggered: { dot: "◎", label: "TRIGGERED", color: "#a16207" },
  running:   { dot: "⟳", label: "RUNNING",   color: "#1d4ed8" },
  complete:  { dot: "✓", label: "COMPLETE",  color: "#15803d" },
  timed_out: { dot: "⚠", label: "TIMED OUT", color: "#a16207" },
  failed:    { dot: "✗", label: "FAILED",    color: "#b91c1c" },
  skipped:   { dot: "—", label: "SKIPPED",   color: "var(--text-dim)" },
};

export default function AgentCard({ agent, state, onClick, selected }: AgentCardProps) {
  const accent = accentColors[agent.accent] ?? "#2563eb";
  const sl = stateLabels[state] ?? stateLabels.idle;
  const iconFn = icons[agent.icon];
  const iconEl = iconFn ? iconFn({ size: 28, stroke: 1.6 }) : null;

  const isInactive = state === "idle" || state === "skipped";

  return (
    <div
      className={`agent-card state-${state} clickable${selected ? " selected" : ""}`}
      onClick={onClick}
      style={{ height: 124, display: "flex", flexDirection: "column" }}
    >
      {/* Icon area */}
      <div
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          position: "relative",
          color: accent,
        }}
      >
        <div
          style={{
            opacity: isInactive ? 0.5 : 1,
            color: isInactive ? "var(--text-dim)" : accent,
          }}
        >
          {iconEl}
        </div>

        {/* Checkmark badge for complete */}
        {state === "complete" && (
          <div
            style={{
              position: "absolute",
              bottom: 8,
              right: 12,
              width: 18,
              height: 18,
              borderRadius: 999,
              background: "var(--ok)",
              color: "#0a0d12",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 11,
              fontWeight: 800,
            }}
          >
            {icons.check({ size: 11, stroke: 3 })}
          </div>
        )}
      </div>

      {/* 2px bottom bar for running state (Phase 1 — no spin ring) */}
      {state === "running" && (
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: 2,
            background: accent,
            borderRadius: "0 0 6px 6px",
            opacity: 0.7,
          }}
        />
      )}

      {/* Name */}
      <div
        className="no-select"
        style={{
          fontSize: 10.5,
          letterSpacing: "0.1em",
          textAlign: "center",
          fontWeight: 600,
          color: isInactive ? "var(--text-dim)" : "var(--text-primary)",
          padding: "0 4px",
        }}
      >
        {agent.short}
      </div>

      {/* State badge */}
      <div
        className="mono"
        style={{
          fontSize: 9.5,
          letterSpacing: "0.1em",
          textAlign: "center",
          color: sl.color,
          marginTop: 4,
          marginBottom: 6,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 4,
        }}
      >
        <span style={{ display: "inline-block" }}>{sl.dot}</span>
        {sl.label}
      </div>
    </div>
  );
}
