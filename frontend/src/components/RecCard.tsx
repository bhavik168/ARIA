import React from "react";
import icons from "./Icon";
import type { NavData, MedData, HazData, AgentState } from "../types";

interface RecState {
  navigation: AgentState;
  medical: AgentState;
  hazmat: AgentState;
}

interface RecCardProps {
  severity: "critical" | "urgent" | "nonurgent";
  summary: string;
  address: string;
  recState: RecState;
  navData: NavData | null;
  medData: MedData | null;
  hazState: AgentState;
  hazData: HazData | null;
  confidence: number;
  reasoning: string;
  onDispatch: () => void;
  onApproveAll: () => void;
  onOverride: () => void;
  partialApproved: boolean;
  fullyApproved: boolean;
  units: unknown[];
  reportUrl?: string | null;
}

function Skeleton({ rows = 2 }: { rows?: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "6px 0" }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="sk" style={{ width: i === 0 ? "85%" : "60%", height: 9 }} />
      ))}
    </div>
  );
}

interface SectionProps {
  name: string;
  status: string;
  statusColor: string;
  elapsedLabel?: string;
  children: React.ReactNode;
}

function Section({ name, status, statusColor, elapsedLabel, children }: SectionProps) {
  return (
    <div style={{ borderTop: "1px solid var(--border-dim)", padding: "12px 16px" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 8,
          fontSize: 10,
          letterSpacing: "0.14em",
          fontWeight: 700,
        }}
      >
        <span style={{ color: "var(--text-secondary)" }}>{name}</span>
        <span className="mono" style={{ color: statusColor, fontSize: 10, letterSpacing: "0.1em" }}>
          {status}
          {elapsedLabel ? ` · ${elapsedLabel}` : ""}
        </span>
      </div>
      {children}
    </div>
  );
}

const sevPillStyles: Record<string, { bg: string; color: string; border: string }> = {
  critical:  { bg: "rgba(239,68,68,0.15)",  color: "#b91c1c", border: "rgba(239,68,68,0.7)" },
  urgent:    { bg: "rgba(245,158,11,0.15)", color: "#a16207", border: "rgba(245,158,11,0.7)" },
  nonurgent: { bg: "rgba(34,197,94,0.15)",  color: "#15803d", border: "rgba(34,197,94,0.7)" },
};

export default function RecCard({
  severity,
  summary,
  address,
  recState,
  navData,
  medData,
  hazState,
  hazData,
  confidence,
  reasoning,
  onDispatch,
  onApproveAll,
  onOverride,
  partialApproved,
  fullyApproved,
  reportUrl,
}: RecCardProps) {
  const sevPillStyle = sevPillStyles[severity] ?? sevPillStyles.critical;

  const navStatus = navData
    ? "✓"
    : recState.navigation === "running"
    ? "⟳ RUNNING"
    : "◌ PENDING";
  const navStatusColor = navData
    ? "var(--ok)"
    : recState.navigation === "running"
    ? "#1d4ed8"
    : "var(--text-dim)";

  const medStatus = medData
    ? "✓"
    : recState.medical === "running"
    ? "⟳ RUNNING"
    : "◌ PENDING";
  const medStatusColor = medData
    ? "var(--ok)"
    : recState.medical === "running"
    ? "#1d4ed8"
    : "var(--text-dim)";

  const hazStatus =
    hazState === "skipped"
      ? "◌ NOT TRIGGERED"
      : hazState === "complete"
      ? "✓"
      : hazState === "running"
      ? "⟳ RUNNING"
      : "◌ PENDING";
  const hazStatusColor =
    hazState === "skipped"
      ? "var(--text-dim)"
      : hazState === "complete"
      ? "var(--ok)"
      : "#1d4ed8";

  return (
    <div
      className="panel"
      style={{
        margin: "0 14px 14px",
        background: "var(--bg-panel)",
        border:
          severity === "critical"
            ? "1.5px solid rgba(220,38,38,0.3)"
            : "1px solid var(--border-dim)",
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div style={{ padding: "14px 16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <span
            style={{
              padding: "3px 9px",
              fontSize: 10,
              letterSpacing: "0.14em",
              fontWeight: 700,
              borderRadius: 999,
              background: sevPillStyle.bg,
              color: sevPillStyle.color,
              border: `1px solid ${sevPillStyle.border}`,
            }}
          >
            <span className="dot" style={{ marginRight: 5, color: "var(--critical)" }} />
            {severity.toUpperCase()}
          </span>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)" }}>
            {summary}
          </span>
        </div>
        <div
          style={{
            color: "var(--text-mono)",
            fontSize: 12.5,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <span style={{ color: "var(--urgent)" }}>{icons.pin({ size: 13 })}</span>
          {address}
        </div>
      </div>

      {/* NAVIGATION */}
      <Section
        name="NAVIGATION"
        status={navStatus}
        statusColor={navStatusColor}
        elapsedLabel={navData?.elapsed}
      >
        {!navData ? (
          <Skeleton />
        ) : (
          <div
            style={{
              background: "var(--bg-elevated)",
              border: "1px solid var(--border-dim)",
              borderRadius: 4,
              padding: "10px 12px",
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}
          >
            <span style={{ color: "#1d4ed8" }}>{icons.ambulance({ size: 22 })}</span>
            <div style={{ flex: 1 }}>
              <div className="mono" style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>
                {navData.unit} · {navData.unit_type} ·{" "}
                <span style={{ color: "#15803d" }}>ETA {navData.eta_min} min</span>
              </div>
              <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                {navData.station} → live traffic via Google Maps
              </div>
            </div>
            <a
              href="#"
              style={{
                color: "#0369a1",
                fontSize: 11,
                textDecoration: "none",
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              View&nbsp;Route {icons.external({ size: 11 })}
            </a>
          </div>
        )}

        {/* Partial approval button (Phase 1: static border, no dispatch-pulse) */}
        {navData && !partialApproved && (
          <button
            className="btn btn-dispatch"
            onClick={onDispatch}
            style={{ marginTop: 10 }}
          >
            ⚡&nbsp;&nbsp;Dispatch&nbsp;Unit&nbsp;Now
          </button>
        )}
        {partialApproved && (
          <div
            style={{
              marginTop: 10,
              padding: "8px 10px",
              background: "rgba(34,197,94,0.08)",
              border: "1px solid rgba(34,197,94,0.4)",
              borderRadius: 4,
              fontSize: 11.5,
              color: "#15803d",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span style={{ color: "var(--ok)" }}>{icons.check({ size: 14, stroke: 2.5 })}</span>
            Unit dispatched · logged to DynamoDB
          </div>
        )}
      </Section>

      {/* MEDICAL */}
      <Section
        name="MEDICAL"
        status={medStatus}
        statusColor={medStatusColor}
        elapsedLabel={medData?.elapsed}
      >
        {!medData ? (
          <Skeleton />
        ) : (
          <div
            style={{
              background: "var(--bg-elevated)",
              border: "1px solid var(--border-dim)",
              borderRadius: 4,
              padding: "10px 12px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <span style={{ color: "var(--ok)" }}>{icons.cross({ size: 16 })}</span>
              <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>
                {medData.hospital} ·{" "}
                <span style={{ color: "#15803d" }}>ETA {medData.eta_min} min</span>
              </span>
            </div>
            <div
              style={{
                fontSize: 11.5,
                color: "var(--text-mono)",
                marginLeft: 26,
                lineHeight: 1.5,
              }}
            >
              <div>
                <span className="dot" style={{ color: "var(--ok)" }} /> {medData.status} ·{" "}
                {medData.bay}
              </div>
              <div style={{ color: "var(--text-secondary)" }}>Protocol: {medData.protocol}</div>
              {medData.citations && medData.citations.length > 0 && (
                <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 4 }}>
                  Source: {medData.citations.map((c) => c.source_name).join(" · ")}
                </div>
              )}
            </div>
          </div>
        )}
      </Section>

      {/* FIRE/HAZMAT */}
      <Section name="FIRE / HAZMAT" status={hazStatus} statusColor={hazStatusColor}>
        {hazState === "skipped" && (
          <div style={{ fontSize: 11.5, color: "var(--text-dim)", fontStyle: "italic" }}>
            No hazmat or fire keywords detected. Agent skipped for this incident.
          </div>
        )}
        {hazState === "running" && <Skeleton rows={1} />}
        {hazState === "complete" && hazData && (
          <div style={{ fontSize: 12, color: "var(--text-mono)" }}>
            <div>{hazData.summary}</div>
            {hazData.evacuation_radius_m != null && (
              <div style={{ marginTop: 6, display: "flex", gap: 12 }}>
                <span
                  style={{
                    padding: "2px 8px",
                    background: "var(--hazmat-text)",
                    color: "#fff",
                    borderRadius: 3,
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: "0.08em",
                  }}
                >
                  EVAC {hazData.evacuation_radius_m}m
                </span>
                {hazData.gear && hazData.gear.length > 0 && (
                  <span style={{ fontSize: 10, color: "var(--text-secondary)", alignSelf: "center" }}>
                    PPE: {hazData.gear.join(", ")}
                  </span>
                )}
              </div>
            )}
            {hazData.citations && hazData.citations.length > 0 && (
              <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 4 }}>
                Source: {hazData.citations.map((c) => c.source_name).join(" · ")}
              </div>
            )}
          </div>
        )}
      </Section>

      {/* CONFIDENCE */}
      <div
        style={{
          borderTop: "1px solid var(--border-dim)",
          padding: "12px 16px",
          background: "rgba(15,23,42,0.4)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <span className="panel-header">AI Confidence</span>
          {confidence > 0 ? (
            <>
              <div
                style={{
                  flex: 1,
                  height: 6,
                  borderRadius: 3,
                  background: "var(--bg-deep)",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    width: `${confidence * 100}%`,
                    background: "linear-gradient(90deg, #15803d 0%, #16a34a 100%)",
                    transition: "width 0.6s ease-out",
                  }}
                />
              </div>
              <span className="mono" style={{ fontSize: 11, color: "#15803d", fontWeight: 600 }}>
                {(confidence * 100).toFixed(0)}% · HIGH
              </span>
            </>
          ) : (
            <div className="sk" style={{ flex: 1, height: 6 }} />
          )}
        </div>
        {reasoning ? (
          <div style={{ fontSize: 12, color: "var(--text-mono)", lineHeight: 1.5 }}>
            {reasoning}
          </div>
        ) : (
          <Skeleton rows={2} />
        )}
      </div>

      {/* Action buttons */}
      <div
        style={{
          borderTop: "1px solid var(--border-dim)",
          padding: 14,
          display: "flex",
          gap: 10,
        }}
      >
        <button
          className="btn btn-primary"
          onClick={onApproveAll}
          disabled={!reasoning || fullyApproved}
          style={{ flex: 1, opacity: !reasoning || fullyApproved ? 0.5 : 1 }}
        >
          {fullyApproved ? "✓ Approved" : "✓ Approve All"}
        </button>
        <button className="btn btn-secondary" onClick={onOverride}>
          ↩ Override
        </button>
      </div>

      {/* After-action report download */}
      {reportUrl && (
        <div
          style={{
            borderTop: "1px solid var(--ok-border)",
            padding: "10px 14px",
            background: "var(--ok-bg)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span style={{ fontSize: 11.5, color: "var(--ok-text-deep)", fontWeight: 600 }}>
            ✓ After-action report ready
          </span>
          <a
            href={reportUrl}
            target="_blank"
            rel="noreferrer"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              padding: "5px 12px",
              background: "var(--bg-panel)",
              border: "1px solid var(--ok-border)",
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 700,
              color: "var(--ok-text-deep)",
              letterSpacing: "0.06em",
              textDecoration: "none",
            }}
          >
            ↓ Download Report
          </a>
        </div>
      )}
    </div>
  );
}
