interface TopBarProps {
  elapsedMs: number;
  severity: "critical" | "urgent" | "nonurgent";
  incidentId: string;
  live: boolean;
  sessionComplete?: boolean;
}

export default function TopBar({ elapsedMs, severity, incidentId, live, sessionComplete }: TopBarProps) {
  const totalS = Math.floor(elapsedMs / 1000);
  const mm = String(Math.floor(totalS / 60)).padStart(2, "0");
  const ss = String(totalS % 60).padStart(2, "0");
  const cs = String(Math.floor((elapsedMs % 1000) / 10)).padStart(2, "0");

  const sevMap: Record<string, { cls: string; label: string }> = {
    critical:  { cls: "sev-critical", label: "CRITICAL" },
    urgent:    { cls: "",             label: "URGENT" },
    nonurgent: { cls: "",             label: "NON-URGENT" },
  };
  const sev = sevMap[severity] ?? sevMap.critical;

  return (
    <header
      className="topbar no-select"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 20,
        padding: "0 18px",
        background: "var(--bg-deep)",
        borderBottom: "1px solid var(--border-dim)",
        height: 56,
      }}
    >
      {/* ARIA wordmark */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div
          style={{
            width: 22,
            height: 22,
            borderRadius: 4,
            background: "linear-gradient(135deg, #dc2626 0%, #d97706 100%)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 12,
            fontWeight: 800,
            color: "#0a0d12",
          }}
        >
          A
        </div>
        <div style={{ fontWeight: 700, letterSpacing: "0.18em", fontSize: 14 }}>ARIA</div>
        <div style={{ fontSize: 10, color: "var(--text-dim)", letterSpacing: "0.1em", marginTop: 2 }}>
          DISPATCH&nbsp;CO-PILOT
        </div>
      </div>

      <div style={{ width: 1, height: 24, background: "var(--border-dim)" }} />

      <span className="mono" style={{ color: "var(--text-secondary)", fontSize: 12 }}>
        {incidentId}
      </span>

      <span
        className={"mono " + sev.cls}
        style={{
          padding: "4px 10px",
          fontSize: 11,
          letterSpacing: "0.12em",
          fontWeight: 600,
          borderRadius: 999,
        }}
      >
        <span className="dot" style={{ marginRight: 6, color: "var(--critical)" }} />
        {sev.label}
      </span>

      <div style={{ flex: 1 }} />

      {/* Timer */}
      <div className="mono" style={{ fontSize: 18, fontWeight: 500, letterSpacing: "0.04em" }}>
        <span style={{ color: "var(--text-secondary)", fontSize: 10, marginRight: 8, letterSpacing: "0.15em" }}>
          T+
        </span>
        {mm}:{ss}
        <span style={{ color: "var(--text-secondary)" }}>.{cs}</span>
      </div>

      {/* Session complete banner OR live indicator */}
      {sessionComplete ? (
        <div
          className="mono"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "4px 12px",
            background: "var(--ok-bg)",
            border: "1px solid var(--ok-border)",
            borderRadius: 999,
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.12em",
            color: "var(--ok-text-deep)",
          }}
        >
          <span className="dot" style={{ color: "var(--ok)" }} />
          SESSION COMPLETE
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="dot" style={{ color: live ? "var(--ok)" : "var(--text-dim)" }} />
          <span
            className="mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.15em",
              fontWeight: 600,
              color: live ? "var(--ok)" : "var(--text-dim)",
            }}
          >
            {live ? "LIVE" : "OFFLINE"}
          </span>
        </div>
      )}

      <div style={{ width: 1, height: 24, background: "var(--border-dim)" }} />
      <div className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
        DISP&nbsp;<span style={{ color: "var(--text-mono)" }}>K.&nbsp;OKONKWO</span> · CH-3
      </div>
    </header>
  );
}
