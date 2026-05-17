// ARIA Dispatcher Dashboard — TypeScript interfaces

export type AgentId =
  | "stream"
  | "coordinator"
  | "navigation"
  | "medical"
  | "hazmat"
  | "report"
  | "haiku";

export type AgentState =
  | "idle"
  | "listening"
  | "triggered"
  | "running"
  | "complete"
  | "failed"
  | "timed_out"
  | "skipped";

export type AgentAccent =
  | "running"
  | "indigo"
  | "cyan"
  | "critical"
  | "hazmat"
  | "ok"
  | "yellow";

export type IconName =
  | "mic"
  | "brain"
  | "compass"
  | "heart"
  | "flame"
  | "doc"
  | "bolt"
  | "play"
  | "pause"
  | "stop"
  | "check"
  | "x"
  | "alert"
  | "ambulance"
  | "police"
  | "pin"
  | "cross"
  | "external"
  | "spinner"
  | "circle"
  | "arrowRight";

export interface Agent {
  id: AgentId;
  name: string;
  short: string;
  accent: AgentAccent;
  icon: IconName;
}

export type KeywordCategory = "medical" | "location" | "crime" | "fire" | null;

/** One transcript word/phrase entry */
export interface TranscriptEntry {
  t: number;
  speaker: string;
  text: string;
  kw: KeywordCategory;
}

/** One incident timeline entry */
export interface TimelineEntry {
  t: number;
  icon: string;
  label: string;
}

/** One agent log line */
export interface LogLine {
  ts: string;
  text: string;
}

/** Navigation agent result */
export interface NavData {
  unit: string;
  unit_type: string;
  eta_min: number;
  station: string;
  elapsed: string;
}

/** Medical agent result */
export interface MedData {
  hospital: string;
  eta_min: number;
  status: string;
  bay: string;
  protocol: string;
  elapsed: string;
  citations?: { source_name: string; doc_id?: string }[];
}

/** Hazmat agent result */
export interface HazData {
  summary: string;
  evacuation_radius_m?: number;
  gear?: string[];
  citations?: { source_name: string; doc_id?: string }[];
}

/** Map marker state */
export interface MapMarkers {
  unit: boolean;
  route: boolean;
  hospital: boolean;
}

export type UnitState = "staging" | "dispatched" | "en_route" | "on_scene";
export type UnitType = "ambulance" | "police" | "fire";

/** A dispatched unit */
export interface Unit {
  id: string;
  type: UnitType;
  eta_min: number;
  state: UnitState;
}

/** Upload state for audio file sessions */
export type UploadState = "idle" | "selecting" | "uploading" | "processing" | "error";

/** Toast notification */
export interface Toast {
  msg: string;
  color: "ok" | "urgent";
}

// ---- Simulation event types ----

export interface SimEventAgent {
  t: number;
  type: "agent";
  agent: AgentId;
  state: AgentState;
}

export interface SimEventLog {
  t: number;
  type: "log";
  agent: AgentId;
  line: LogLine;
}

export interface SimEventTimeline {
  t: number;
  type: "timeline";
  icon: string;
  label: string;
}

export interface SimEventRecSection {
  t: number;
  type: "rec_section";
  section: "navigation" | "medical" | "hazmat";
  payload: NavData | MedData | HazData;
}

export interface SimEventRecReady {
  t: number;
  type: "rec_ready";
  confidence: number;
  summary: string;
}

export interface SimEventPartialApproval {
  t: number;
  type: "partial_approval";
  value: boolean;
}

export interface SimEventApproved {
  t: number;
  type: "approved";
  value?: "partial" | "full";
  scope?: "partial" | "full";
}

export interface SimEventUnitState {
  t: number;
  type: "unit_state";
  unit: string;
  state: UnitState;
}

export interface SimEventMap {
  t: number;
  type: "map";
  marker: "unit" | "route" | "hospital";
  id?: string;
}

export interface SimEventSessionEnd {
  t: number;
  type: "session_end";
  report_url?: string;
}

export interface SimEventTranscript {
  t: number;
  type: "transcript";
  speaker: string;
  text: string;
  kw?: KeywordCategory;
}

export type DashboardEvent =
  | SimEventAgent
  | SimEventLog
  | SimEventTimeline
  | SimEventRecSection
  | SimEventRecReady
  | SimEventPartialApproval
  | SimEventApproved
  | SimEventUnitState
  | SimEventMap
  | SimEventSessionEnd
  | SimEventTranscript;
