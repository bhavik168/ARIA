// ARIA — Main App, wires simulation OR real backend to UI state

import { useState, useEffect, useRef, useCallback } from "react";

import TopBar from "./components/TopBar";
import AudioPlayer from "./components/AudioPlayer";
import TranscriptFeed from "./components/TranscriptFeed";
import AgentGrid from "./components/AgentGrid";
import AgentLog from "./components/AgentLog";
import DispatchedUnits from "./components/DispatchedUnits";
import RecCard from "./components/RecCard";
import LiveMap from "./components/LiveMap";
import IncidentTimeline from "./components/IncidentTimeline";
import OverrideModal from "./components/OverrideModal";
import IdleOverlay from "./components/IdleOverlay";

import { TRANSCRIPT, AGENTS, EVENTS, SCENARIO_DURATION } from "./data/simulation";

import type {
  AgentId,
  AgentState,
  TranscriptEntry,
  TimelineEntry,
  LogLine,
  NavData,
  MedData,
  HazData,
  MapMarkers,
  Unit,
  UploadState,
  Toast,
  DashboardEvent,
} from "./types";

// Read API config from Vite env vars
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const WS_BASE  = (import.meta.env.VITE_WS_URL ?? "").replace(/\/$/, "");

// ?demo=1  →  local frontend simulation, no backend required
const IS_DEMO = new URLSearchParams(window.location.search).get("demo") === "1";

type AgentStates = Record<AgentId, AgentState>;
type AgentLogs   = Record<AgentId, LogLine[]>;

function makeInitialAgentStates(): AgentStates {
  const o: Partial<AgentStates> = {};
  for (const a of AGENTS) o[a.id] = "idle";
  return o as AgentStates;
}

export default function App() {
  // ---- Session state ----
  const [sessionActive, setSessionActive] = useState(false);
  const [incidentId, setIncidentId]       = useState<string | null>(null);
  const [uploadState, setUploadState]     = useState<UploadState>("idle");
  const [audioFileName, setAudioFileName] = useState<string | null>(null);

  // WebSocket + polling refs
  const wsRef   = useRef<WebSocket | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---- Simulation clock ----
  const [elapsedMs, setElapsedMs] = useState(0);
  const [playing, setPlaying]     = useState(false);
  const startedAtRef         = useRef(performance.now());
  const elapsedAtPauseRef    = useRef(0);
  const eventCursorRef       = useRef(0);
  const transcriptCursorRef  = useRef(0);

  // ---- Dashboard state ----
  const [transcript,      setTranscript]      = useState<TranscriptEntry[]>([]);
  const [agentStates,     setAgentStates]     = useState<AgentStates>(makeInitialAgentStates);
  const [agentLogs,       setAgentLogs]       = useState<AgentLogs>({} as AgentLogs);
  const [timeline,        setTimeline]        = useState<TimelineEntry[]>([]);
  const [navData,         setNavData]         = useState<NavData | null>(null);
  const [medData,         setMedData]         = useState<MedData | null>(null);
  const [hazData,         setHazData]         = useState<HazData | null>(null);
  const [confidence,      setConfidence]      = useState(0);
  const [reasoning,       setReasoning]       = useState("");
  const [partialApproved, setPartialApproved] = useState(false);
  const [fullyApproved,   setFullyApproved]   = useState(false);
  const [units,           setUnits]           = useState<Unit[]>([]);
  const [mapMarkers,      setMapMarkers]      = useState<MapMarkers>({ unit: false, route: false, hospital: false });
  const [selectedAgent,   setSelectedAgent]   = useState<AgentId | null>(null);
  const [overrideOpen,    setOverrideOpen]    = useState(false);
  const [toast,           setToast]           = useState<Toast | null>(null);
  const [sessionComplete, setSessionComplete] = useState(false);
  const [reportUrl,       setReportUrl]       = useState<string | null>(null);
  const wordPulses = useRef<Array<{ at: number; idx: number }>>([]);

  // =========================================================================
  // TOAST
  // =========================================================================
  function showToast(msg: string, color: "ok" | "urgent") {
    setToast({ msg, color });
    setTimeout(() => setToast(null), 3400);
  }

  // =========================================================================
  // RESET
  // =========================================================================
  const reset = useCallback(() => {
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }

    startedAtRef.current        = performance.now();
    elapsedAtPauseRef.current   = 0;
    eventCursorRef.current      = 0;
    transcriptCursorRef.current = 0;

    setElapsedMs(0);
    setTranscript([]);
    setAgentStates(makeInitialAgentStates());
    setAgentLogs({} as AgentLogs);
    setTimeline([]);
    setNavData(null);
    setMedData(null);
    setHazData(null);
    setConfidence(0);
    setReasoning("");
    setPartialApproved(false);
    setFullyApproved(false);
    setUnits([]);
    setMapMarkers({ unit: false, route: false, hospital: false });
    setPlaying(false);
    setSessionActive(false);
    setIncidentId(null);
    setUploadState("idle");
    setAudioFileName(null);
    setSessionComplete(false);
    setReportUrl(null);
    wordPulses.current = [];
  }, []);

  // =========================================================================
  // EVENT HANDLER — shared by simulation clock AND WebSocket messages
  // =========================================================================
  // Defined with useCallback so startPolling/openWebSocket can reference it
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const handleEvent = useCallback((ev: DashboardEvent) => {
    switch (ev.type) {
      case "agent":
        setAgentStates((prev) => ({ ...prev, [ev.agent]: ev.state }));
        break;
      case "log":
        setAgentLogs((prev) => {
          const arr = prev[ev.agent] ? [...prev[ev.agent]] : [];
          arr.push(ev.line);
          return { ...prev, [ev.agent]: arr };
        });
        break;
      case "transcript":
        setTranscript((prev) => [
          ...prev,
          { t: ev.t ?? 0, speaker: ev.speaker, text: ev.text, kw: ev.kw ?? null },
        ]);
        wordPulses.current.push({ at: performance.now(), idx: Math.floor(Math.random() * 56) });
        break;
      case "timeline":
        setTimeline((prev) => [...prev, { t: ev.t ?? 0, icon: ev.icon, label: ev.label }]);
        break;
      case "rec_section": {
        // Normalize real backend field names → frontend types
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const p = ev.payload as any;
        if (ev.section === "navigation") {
          setNavData({
            unit:      p.unit      ?? p.unit_id   ?? "",
            unit_type: p.unit_type ?? "",
            eta_min:   p.eta_min   ?? 0,
            station:   p.station   ?? "",
            elapsed:   p.elapsed   ?? (p.elapsed_ms != null ? `${(p.elapsed_ms / 1000).toFixed(1)}s` : ""),
          } as NavData);
        } else if (ev.section === "medical") {
          setMedData({
            hospital:   p.hospital   ?? p.hospital_name ?? "",
            eta_min:    p.eta_min    ?? 0,
            status:     p.status     ?? "",
            bay:        p.bay        ?? "",
            protocol:   p.protocol   ?? p.protocol_text ?? "",
            elapsed:    p.elapsed    ?? (p.elapsed_ms != null ? `${(p.elapsed_ms / 1000).toFixed(1)}s` : ""),
            citations:  p.citations  ?? undefined,
          } as MedData);
        } else if (ev.section === "hazmat") {
          setHazData({
            summary:              p.summary              ?? "",
            evacuation_radius_m:  p.evacuation_radius_m  ?? undefined,
            gear:                 p.gear                 ?? undefined,
            citations:            p.citations            ?? undefined,
          } as HazData);
        }
        break;
      }
      case "partial_approval":
        // handled via rec_ready / approved events
        break;
      case "rec_ready":
        setReasoning(ev.summary);
        animateConfidence(ev.confidence);
        break;
      case "approved":
        if (ev.value === "partial" || ev.scope === "partial") {
          setPartialApproved(true);
          setUnits((prev) => {
            if (prev.find((u) => u.id === "MED-1")) return prev;
            return [{ id: "MED-1", type: "ambulance", eta_min: 4, state: "dispatched" }];
          });
        }
        if (ev.value === "full" || ev.scope === "full") {
          setFullyApproved(true);
          setPartialApproved(true);
        }
        break;
      case "unit_state":
        setUnits((prev) => {
          const found = prev.find((u) => u.id === ev.unit);
          if (found) return prev.map((u) => (u.id === ev.unit ? { ...u, state: ev.state } : u));
          if (ev.unit === "MED-3")
            return [...prev, { id: "MED-3", type: "ambulance", eta_min: 7, state: ev.state }];
          return prev;
        });
        break;
      case "map":
        if (ev.marker === "unit")     setMapMarkers((m) => ({ ...m, unit: true }));
        if (ev.marker === "route")    setMapMarkers((m) => ({ ...m, route: true }));
        if (ev.marker === "hospital") setMapMarkers((m) => ({ ...m, hospital: true }));
        break;
      case "session_end":
        setSessionComplete(true);
        setTimeline((prev) => [
          ...prev,
          { t: ev.t ?? 0, icon: "✓", label: "Session complete — report generated → S3" },
        ]);
        if (ev.report_url) {
          setReportUrl(ev.report_url);
          showToast("After-action report ready — download in RecCard", "ok");
        }
        break;
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // =========================================================================
  // POLLING FALLBACK
  // =========================================================================
  const startPolling = useCallback((iid: string) => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`${API_BASE}/session/${iid}/status`);
        if (!r.ok) return;
        const data = await r.json() as { status: string };
        if (data.status === "complete" || data.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch (_) {
        // ignore
      }
    }, 3000);
  }, []);

  // =========================================================================
  // WEBSOCKET
  // =========================================================================
  const openWebSocket = useCallback((iid: string, wsUrl?: string) => {
    const url = `${wsUrl ?? WS_BASE}?incident_id=${iid}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setTimeline((prev) => [...prev, { t: 0, icon: "●", label: "WebSocket connected" }]);
    };

    ws.onmessage = (msg) => {
      try {
        const ev = JSON.parse(msg.data as string) as DashboardEvent;
        handleEvent(ev);
      } catch (_) {
        // ignore malformed
      }
    };

    ws.onclose = () => {
      if (wsRef.current === ws) startPolling(iid);
    };

    ws.onerror = () => ws.close();
  }, [handleEvent, startPolling]);

  // =========================================================================
  // SESSION START — DEMO (local simulation, no backend)
  // =========================================================================
  const startDemoSession = useCallback(() => {
    reset();
    setSessionActive(true);
    setPlaying(true);
    startedAtRef.current = performance.now();
  }, [reset]);

  // =========================================================================
  // SESSION START — BACKEND SIMULATION (real Lambda pipeline, sim transcript)
  // =========================================================================
  const startBackendSession = useCallback(async () => {
    if (!API_BASE || !WS_BASE) {
      showToast("VITE_API_BASE_URL / VITE_WS_URL not configured in .env", "urgent");
      return;
    }
    setUploadState("processing");
    try {
      // Convert TRANSCRIPT to backend format: [{ word, speaker, delay_ms }]
      const backendTranscript: { word: string; speaker: string; delay_ms: number }[] = [];
      let prevT = 0;
      for (const entry of TRANSCRIPT) {
        const { t, speaker, text } = entry;
        const words = text.split(/\s+/).filter(Boolean);
        const delayPerWord =
          words.length > 0 ? Math.round(((t - prevT) * 1000) / words.length) : 300;
        for (const word of words) {
          backendTranscript.push({
            word,
            speaker: speaker === "DISPATCHER" ? "dispatcher" : "caller",
            delay_ms: Math.max(50, delayPerWord),
          });
        }
        prevT = t;
      }

      const r = await fetch(`${API_BASE}/session/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ simulation_transcript: backendTranscript }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const { incident_id, websocket_url } = await r.json() as {
        incident_id: string;
        websocket_url: string;
      };

      reset();
      setIncidentId(incident_id);
      setSessionActive(true);
      setPlaying(true);
      startedAtRef.current = performance.now();
      openWebSocket(incident_id, websocket_url);
    } catch (err) {
      setUploadState("error");
      showToast(`Session start failed: ${(err as Error).message}`, "urgent");
    }
  }, [reset, openWebSocket]);

  // =========================================================================
  // SESSION START — REAL AUDIO (file upload → S3 → Transcribe → WebSocket)
  // =========================================================================
  const startAudioSession = useCallback(async (audioFile: File) => {
    if (!API_BASE || !WS_BASE) {
      showToast("VITE_API_BASE_URL / VITE_WS_URL not configured in .env", "urgent");
      return;
    }
    setAudioFileName(audioFile.name);
    setUploadState("uploading");
    try {
      // 1. Get pre-signed S3 upload URL
      const presignRes = await fetch(`${API_BASE}/session/presign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: audioFile.name,
          content_type: audioFile.type || "audio/wav",
        }),
      });
      if (!presignRes.ok) throw new Error(`Presign failed: HTTP ${presignRes.status}`);
      const { upload_url, audio_key } = await presignRes.json() as {
        upload_url: string;
        audio_key: string;
      };

      // 2. Upload audio directly to S3
      const uploadRes = await fetch(upload_url, {
        method: "PUT",
        headers: { "Content-Type": audioFile.type || "audio/wav" },
        body: audioFile,
      });
      if (!uploadRes.ok) throw new Error(`S3 upload failed: HTTP ${uploadRes.status}`);

      setUploadState("processing");

      // 3. Start session with the uploaded file key
      const startRes = await fetch(`${API_BASE}/session/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audio_file_key: audio_key }),
      });
      if (!startRes.ok) throw new Error(`Session start failed: HTTP ${startRes.status}`);
      const { incident_id, websocket_url } = await startRes.json() as {
        incident_id: string;
        websocket_url: string;
      };

      // 4. Activate session and open WebSocket
      reset();
      setIncidentId(incident_id);
      setAudioFileName(audioFile.name);
      setSessionActive(true);
      setPlaying(true);
      startedAtRef.current = performance.now();
      openWebSocket(incident_id, websocket_url);
    } catch (err) {
      setUploadState("error");
      showToast(`Audio session failed: ${(err as Error).message}`, "urgent");
    }
  }, [reset, openWebSocket]);

  // =========================================================================
  // SIMULATION CLOCK (demo mode only)
  // =========================================================================
  useEffect(() => {
    let raf: number;
    const loop = () => {
      if (playing) {
        const now = performance.now();
        const e = elapsedAtPauseRef.current + (now - startedAtRef.current);
        const eClamped = IS_DEMO
          ? Math.min(e, SCENARIO_DURATION * 1000 + 3000)
          : e;
        setElapsedMs(eClamped);
        if (IS_DEMO) processSimulation(eClamped / 1000);
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  function processSimulation(t: number) {
    while (
      transcriptCursorRef.current < TRANSCRIPT.length &&
      TRANSCRIPT[transcriptCursorRef.current].t <= t
    ) {
      const entry = TRANSCRIPT[transcriptCursorRef.current];
      setTranscript((prev) => [...prev, entry]);
      const burst = Math.max(1, Math.min(6, entry.text.split(/\s+/).length));
      for (let k = 0; k < burst; k++) {
        wordPulses.current.push({
          at: performance.now() + k * 60,
          idx: Math.floor(Math.random() * 56),
        });
      }
      transcriptCursorRef.current++;
    }
    while (
      eventCursorRef.current < EVENTS.length &&
      EVENTS[eventCursorRef.current].t <= t
    ) {
      handleEvent(EVENTS[eventCursorRef.current]);
      eventCursorRef.current++;
    }
  }

  // =========================================================================
  // CONFIDENCE ANIMATION
  // =========================================================================
  const confTargetRef = useRef(0);
  const confRafRef    = useRef<number | null>(null);

  function animateConfidence(target: number) {
    confTargetRef.current = target;
    if (confRafRef.current) cancelAnimationFrame(confRafRef.current);
    const step = () => {
      setConfidence((c) => {
        const diff = confTargetRef.current - c;
        if (Math.abs(diff) < 0.005) return confTargetRef.current;
        confRafRef.current = requestAnimationFrame(step);
        return c + diff * 0.08;
      });
    };
    step();
  }

  // =========================================================================
  // PLAY / PAUSE / STOP (demo mode controls)
  // =========================================================================
  const togglePlay = useCallback(() => {
    if (playing) {
      elapsedAtPauseRef.current += performance.now() - startedAtRef.current;
      setPlaying(false);
    } else {
      startedAtRef.current = performance.now();
      setPlaying(true);
    }
  }, [playing]);

  const onStop = useCallback(() => reset(), [reset]);

  // Spacebar shortcut (demo mode only)
  useEffect(() => {
    if (!IS_DEMO) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        e.code === "Space" &&
        target.tagName !== "TEXTAREA" &&
        target.tagName !== "INPUT"
      ) {
        e.preventDefault();
        togglePlay();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [togglePlay]);

  // =========================================================================
  // DISPATCHER ACTIONS
  // =========================================================================
  const onDispatch = async () => {
    if (partialApproved) return;
    if (!IS_DEMO && incidentId) {
      try {
        await fetch(`${API_BASE}/session/${incidentId}/approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scope: "partial" }),
        });
        // State update comes back via WebSocket event { type: "approved", scope: "partial" }
      } catch (err) {
        showToast(`Approve failed: ${(err as Error).message}`, "urgent");
      }
      return;
    }
    // Demo mode — local state update
    setPartialApproved(true);
    setTimeline((prev) => [
      ...prev,
      { t: elapsedMs / 1000, icon: "⚡", label: "Dispatcher approved — DISPATCH UNIT NOW" },
      { t: elapsedMs / 1000 + 0.2, icon: "✓", label: "Dispatch event logged → DynamoDB" },
    ]);
    setUnits((prev) => {
      if (prev.find((u) => u.id === "MED-1")) return prev;
      return [{ id: "MED-1", type: "ambulance", eta_min: 4, state: "dispatched" }];
    });
    showToast("Unit MED-1 dispatched · logged to DynamoDB", "ok");
  };

  const onApproveAll = async () => {
    if (!IS_DEMO && incidentId) {
      try {
        await fetch(`${API_BASE}/session/${incidentId}/approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scope: "full" }),
        });
      } catch (err) {
        showToast(`Approve failed: ${(err as Error).message}`, "urgent");
      }
      return;
    }
    setFullyApproved(true);
    if (!partialApproved) setPartialApproved(true);
    setTimeline((prev) => [
      ...prev,
      { t: elapsedMs / 1000, icon: "✓", label: "Dispatcher approved — APPROVE ALL" },
    ]);
    showToast("Recommendation approved · Report Agent generating after-action", "ok");
  };

  const onOverride = () => setOverrideOpen(true);

  const onOverrideSubmit = async ({ reason, notes }: { reason: string; notes: string }) => {
    setOverrideOpen(false);
    if (!IS_DEMO && incidentId) {
      try {
        await fetch(`${API_BASE}/session/${incidentId}/override`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason, notes }),
        });
        setTimeline((prev) => [
          ...prev,
          { t: elapsedMs / 1000, icon: "⚡", label: `Override logged — ${reason}` },
        ]);
        showToast(`Override submitted: ${reason}`, "urgent");
      } catch (err) {
        showToast(`Override failed: ${(err as Error).message}`, "urgent");
      }
      return;
    }
    setTimeline((prev) => [
      ...prev,
      { t: elapsedMs / 1000, icon: "⚡", label: `Override logged — ${reason}` },
    ]);
    showToast(`Override submitted: ${reason}`, "urgent");
  };

  // =========================================================================
  // DERIVED STATE
  // =========================================================================
  const selectedAgentObj = selectedAgent ? AGENTS.find((a) => a.id === selectedAgent) ?? null : null;
  const selectedLogs     = selectedAgent ? (agentLogs[selectedAgent] ?? []) : [];
  const selectedState    = selectedAgent ? agentStates[selectedAgent] ?? null : null;
  const recState = {
    navigation: agentStates.navigation,
    medical:    agentStates.medical,
    hazmat:     agentStates.hazmat,
  };

  // =========================================================================
  // RENDER
  // =========================================================================
  return (
    <div className="app-grid" style={{ position: "relative" }}>
      {!sessionActive && (
        <IdleOverlay
          onStartDemo={startDemoSession}
          onStartBackend={startBackendSession}
          onFileSelect={startAudioSession}
          uploadState={uploadState}
        />
      )}

      <TopBar
        elapsedMs={elapsedMs}
        severity="critical"
        incidentId={
          incidentId
            ? `INC-${incidentId.slice(0, 8).toUpperCase()}`
            : "INC-20260516-001"
        }
        live={playing}
        sessionComplete={sessionComplete}
      />

      {/* LEFT COLUMN */}
      <div className="col">
        <AudioPlayer
          playing={playing}
          onTogglePlay={togglePlay}
          onStop={onStop}
          elapsedMs={Math.min(elapsedMs, 163000)}
          totalMs={163000}
          wordPulses={wordPulses}
          demoMode={IS_DEMO}
          audioFileName={audioFileName}
        />
        <TranscriptFeed entries={transcript} live={playing} />
      </div>

      {/* CENTER COLUMN */}
      <div className="col" style={{ overflowY: "auto" }}>
        <AgentGrid
          agents={AGENTS}
          agentStates={agentStates}
          selected={selectedAgent}
          onSelect={setSelectedAgent}
        />
        {selectedAgent && (
          <AgentLog
            agentId={selectedAgent}
            agent={selectedAgentObj}
            logs={selectedLogs}
            state={selectedState}
            onClose={() => setSelectedAgent(null)}
          />
        )}
        {units.length > 0 && (
          <DispatchedUnits units={units} partialApproved={partialApproved} />
        )}
        <RecCard
          severity="critical"
          summary="Cardiac arrest — male, ~50s"
          address="1420 East Pike Street, Capitol Hill, Seattle WA"
          recState={recState}
          navData={navData}
          medData={medData}
          hazState={agentStates.hazmat}
          hazData={hazData}
          confidence={confidence}
          reasoning={reasoning}
          onDispatch={onDispatch}
          onApproveAll={onApproveAll}
          onOverride={onOverride}
          partialApproved={partialApproved}
          fullyApproved={fullyApproved}
          units={units}
          reportUrl={reportUrl}
        />
      </div>

      {/* RIGHT COLUMN */}
      <div className="col" style={{ borderRight: "none" }}>
        <div style={{ padding: 14 }}>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              justifyContent: "space-between",
              marginBottom: 10,
            }}
          >
            <span className="panel-header">Live Map</span>
            <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>
              MAPBOX&nbsp;GL&nbsp;JS
            </span>
          </div>
          <LiveMap
            markers={mapMarkers}
            showRoute={mapMarkers.route}
            showHospital={mapMarkers.hospital}
          />
        </div>
        <IncidentTimeline entries={timeline} />
      </div>

      {/* Override modal */}
      <OverrideModal
        open={overrideOpen}
        onClose={() => setOverrideOpen(false)}
        onSubmit={onOverrideSubmit}
        recommendation="MED-1 · Ambulance · 4 min ETA"
      />

      {/* Toast */}
      {toast && (
        <div
          style={{
            position: "fixed",
            bottom: 24,
            left: "50%",
            transform: "translateX(-50%)",
            padding: "10px 18px",
            background: "var(--bg-panel)",
            border: `1px solid ${
              toast.color === "ok" ? "rgba(34,197,94,0.6)" : "rgba(245,158,11,0.6)"
            }`,
            borderRadius: 6,
            color: toast.color === "ok" ? "#15803d" : "#a16207",
            fontSize: 12.5,
            letterSpacing: "0.04em",
            zIndex: 200,
            boxShadow: "0 12px 32px rgba(0,0,0,0.5)",
          }}
        >
          {toast.msg}
        </div>
      )}
    </div>
  );
}
