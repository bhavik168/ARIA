import { useRef } from "react";
import type { UploadState } from "../types";

// IS_DEMO is determined from URL query param — ?demo=1
const IS_DEMO = new URLSearchParams(window.location.search).get("demo") === "1";

interface IdleOverlayProps {
  onStartDemo: () => void;
  onStartBackend: () => void;
  onFileSelect: (file: File) => void;
  uploadState: UploadState;
}

const STATUS_ROWS: [string, string, boolean][] = [
  ["SYSTEM",         "● System Ready",             true],
  ["AUDIO",          "Waiting for a call",          false],
  ["TRANSCRIPT",     "No active session",           false],
  ["AGENT PIPELINE", "Standby — 7 agents idle",     false],
  ["RECOMMENDATION", "No incident in progress",     false],
  ["LIVE MAP",       "Awaiting incident location",  false],
  ["TIMELINE",       "No events",                   false],
];

const uploadLabels: Partial<Record<UploadState, string>> = {
  uploading:  "⟳ Uploading…",
  processing: "⟳ Starting session…",
  error:      "✗ Upload failed — try again",
};

export default function IdleOverlay({
  onStartDemo,
  onStartBackend,
  onFileSelect,
  uploadState,
}: IdleOverlayProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const uploadLabel = uploadLabels[uploadState] ?? null;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        zIndex: 10,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg-base)",
        gap: 28,
      }}
    >
      {/* Wordmark */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: 10,
            background: "linear-gradient(135deg, #dc2626 0%, #d97706 100%)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 26,
            fontWeight: 800,
            color: "#ffffff",
          }}
        >
          A
        </div>
        <div style={{ fontWeight: 700, letterSpacing: "0.2em", fontSize: 18 }}>ARIA</div>
        <div style={{ fontSize: 11, color: "var(--text-secondary)", letterSpacing: "0.12em" }}>
          DISPATCH CO-PILOT
        </div>
      </div>

      {/* Status grid */}
      <div
        style={{
          border: "1px solid var(--border-dim)",
          borderRadius: 6,
          background: "var(--bg-panel)",
          width: 380,
          overflow: "hidden",
        }}
      >
        {STATUS_ROWS.map(([label, value, isOk], i, arr) => (
          <div
            key={label}
            style={{
              display: "flex",
              alignItems: "baseline",
              justifyContent: "space-between",
              padding: "9px 14px",
              borderBottom: i < arr.length - 1 ? "1px solid var(--border-dim)" : "none",
            }}
          >
            <span
              style={{
                fontSize: 10,
                letterSpacing: "0.12em",
                fontWeight: 700,
                color: "var(--text-secondary)",
                textTransform: "uppercase",
              }}
            >
              {label}
            </span>
            <span
              className="mono"
              style={{ fontSize: 11, color: isOk ? "var(--ok)" : "var(--text-dim)" }}
            >
              {value}
            </span>
          </div>
        ))}
      </div>

      {/* Actions */}
      {IS_DEMO ? (
        <button
          className="btn btn-primary"
          onClick={onStartDemo}
          style={{ padding: "12px 32px", fontSize: 13, letterSpacing: "0.1em" }}
        >
          ▶ Start Demo
        </button>
      ) : (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 10,
            width: 380,
          }}
        >
          {/* Real audio upload */}
          <input
            ref={fileRef}
            type="file"
            accept="audio/*"
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onFileSelect(file);
            }}
          />
          <button
            className="btn btn-primary"
            onClick={() => fileRef.current?.click()}
            disabled={uploadState === "uploading" || uploadState === "processing"}
            style={{ width: "100%", padding: "12px 20px", fontSize: 13, letterSpacing: "0.08em" }}
          >
            {uploadLabel ?? "↑ Upload Audio File"}
          </button>
          {uploadState === "error" && (
            <div style={{ fontSize: 11, color: "var(--critical)" }}>{uploadLabel}</div>
          )}
          {/* Backend simulation (uses real Lambda pipeline, no audio file needed) */}
          <button
            className="btn btn-secondary"
            onClick={onStartBackend}
            disabled={uploadState === "uploading" || uploadState === "processing"}
            style={{ width: "100%", padding: "10px 20px", fontSize: 12 }}
          >
            ▶ Run Backend Demo (simulate via API)
          </button>
          <div style={{ fontSize: 10, color: "var(--text-dim)", textAlign: "center" }}>
            Requires VITE_API_BASE_URL and VITE_WS_URL configured in .env
          </div>
        </div>
      )}
    </div>
  );
}
