import icons from "./Icon";
import type { Unit, UnitState, UnitType } from "../types";

interface DispatchedUnitsProps {
  units: Unit[];
  partialApproved: boolean;
}

const stateMap: Record<UnitState, { icon: string; label: string; color: string }> = {
  staging:    { icon: "◌", label: "STAGING",  color: "var(--text-secondary)" },
  dispatched: { icon: "▶", label: "EN ROUTE", color: "#1d4ed8" },
  en_route:   { icon: "▶", label: "EN ROUTE", color: "#1d4ed8" },
  on_scene:   { icon: "●", label: "ON SCENE", color: "var(--ok)" },
};

const typeColor: Record<UnitType, string> = {
  ambulance: "#1d4ed8",
  police:    "#7e22ce",
  fire:      "#c2410c",
};

export default function DispatchedUnits({ units }: DispatchedUnitsProps) {
  if (!units || units.length === 0) return null;

  return (
    <div
      style={{
        margin: "0 14px 12px",
        padding: "10px 12px",
        background: "var(--bg-deep)",
        border: "1px solid var(--border-dim)",
        borderRadius: 6,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <span className="panel-header">Dispatched Units</span>
        <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>
          ({units.length} {units.length === 1 ? "unit" : "units"})
        </span>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${Math.min(3, units.length)}, 1fr)`,
          gap: 8,
        }}
      >
        {units.map((u) => {
          const s = stateMap[u.state] ?? stateMap.staging;
          const color = typeColor[u.type] ?? "#1d4ed8";
          const unitIcon =
            u.type === "ambulance"
              ? icons.ambulance({ size: 16 })
              : u.type === "police"
              ? icons.police({ size: 16 })
              : icons.pin({ size: 16 });

          return (
            <div key={u.id} className="unit-card">
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                <span style={{ color }}>{unitIcon}</span>
                <span className="mono" style={{ fontWeight: 600, fontSize: 12 }}>
                  {u.id}
                </span>
              </div>
              <div
                style={{
                  fontSize: 9.5,
                  letterSpacing: "0.08em",
                  color: "var(--text-secondary)",
                  textTransform: "uppercase",
                  marginBottom: 4,
                }}
              >
                {u.type}
              </div>
              <div className="mono" style={{ fontSize: 11, color: "var(--text-mono)", marginBottom: 4 }}>
                ETA {u.eta_min} min
              </div>
              <div
                className="mono"
                style={{
                  fontSize: 10,
                  color: s.color,
                  letterSpacing: "0.08em",
                  fontWeight: 600,
                }}
              >
                {s.icon}&nbsp;{s.label}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
