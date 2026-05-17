import { useState } from "react";

interface OverrideSubmitPayload {
  reason: string;
  notes: string;
}

interface OverrideModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (payload: OverrideSubmitPayload) => void;
  recommendation: string;
}

const REASONS = [
  "Wrong unit type",
  "Better route known",
  "Hospital preference",
  "Protocol disagreement",
  "Other",
];

export default function OverrideModal({
  open,
  onClose,
  onSubmit,
  recommendation,
}: OverrideModalProps) {
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");

  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 520,
          background: "var(--bg-panel)",
          border: "1px solid var(--border-bright)",
          borderRadius: 8,
          padding: 22,
          boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 4,
          }}
        >
          <div
            style={{
              fontSize: 13,
              fontWeight: 700,
              letterSpacing: "0.1em",
              color: "var(--text-primary)",
            }}
          >
            OVERRIDE&nbsp;ARIA&nbsp;RECOMMENDATION
          </div>
          <button className="btn" onClick={onClose} style={{ color: "var(--text-secondary)" }}>
            ✕
          </button>
        </div>
        <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 18 }}>
          ARIA recommended:{" "}
          <span className="mono" style={{ color: "var(--text-primary)" }}>
            {recommendation}
          </span>
        </div>

        <label
          style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            color: "var(--text-secondary)",
            textTransform: "uppercase",
          }}
        >
          Reason for override
        </label>
        <div
          style={{
            marginTop: 6,
            marginBottom: 16,
            background: "var(--bg-deep)",
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
          }}
        >
          {REASONS.map((r, idx) => (
            <div
              key={r}
              onClick={() => setReason(r)}
              style={{
                padding: "8px 12px",
                borderBottom:
                  idx < REASONS.length - 1 ? "1px solid var(--border-dim)" : "none",
                cursor: "pointer",
                fontSize: 12.5,
                color: reason === r ? "#a16207" : "var(--text-mono)",
                background: reason === r ? "rgba(245,158,11,0.08)" : "transparent",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 999,
                  border: `1px solid ${reason === r ? "var(--urgent)" : "var(--border-bright)"}`,
                  background: reason === r ? "var(--urgent)" : "transparent",
                  flexShrink: 0,
                }}
              />
              {r}
            </div>
          ))}
        </div>

        <label
          style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            color: "var(--text-secondary)",
            textTransform: "uppercase",
          }}
        >
          Notes (optional)
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          placeholder="e.g. caller reports patient is at upstairs unit B, send ladder access"
          style={{
            width: "100%",
            marginTop: 6,
            background: "var(--bg-deep)",
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            color: "var(--text-primary)",
            padding: 10,
            fontFamily: "inherit",
            fontSize: 12,
            resize: "vertical",
          }}
        />

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 10,
            marginTop: 18,
          }}
        >
          <button className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={!reason}
            onClick={() => onSubmit({ reason, notes })}
            style={{ opacity: reason ? 1 : 0.4 }}
          >
            Submit Override
          </button>
        </div>
      </div>
    </div>
  );
}
