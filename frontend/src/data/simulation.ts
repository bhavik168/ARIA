// ARIA simulation engine — cardiac arrest scenario, T+0 to T+18s
// Each entry has a `t` (seconds from session start) and a payload.

import type {
  Agent,
  TranscriptEntry,
  DashboardEvent,
  KeywordCategory,
} from "../types";

// --- Scenario: Cardiac arrest at 1420 East Pike Street, Capitol Hill ---

// Raw format: [t, speaker, text, keywordCategory?, keywordWords?]
type RawTranscriptRow = [number, string, string, KeywordCategory?, string?];

const RAW_TRANSCRIPT: RawTranscriptRow[] = [
  [0.6,  "CALLER",     "Help,",                           null],
  [1.0,  "CALLER",     "there's a man",                   null],
  [1.6,  "CALLER",     "on the floor",                    null],
  [2.4,  "CALLER",     "at 1420 East Pike Street—",       "location", "1420 East Pike Street"],
  [3.6,  "CALLER",     "he's not breathing,",             "medical",  "not breathing"],
  [4.5,  "CALLER",     "I don't know what to do—",        null],
  [6.0,  "DISPATCHER", "Stay on the line with me.",       null],
  [6.9,  "DISPATCHER", "Is he conscious?",                null],
  [8.2,  "CALLER",     "No, he just collapsed—",          "medical",  "collapsed"],
  [9.6,  "CALLER",     "his lips are blue,",              "medical",  "lips are blue"],
  [10.6, "CALLER",     "please hurry,",                   null],
  [11.8, "DISPATCHER", "Help is being dispatched right now. Begin chest compressions—", null],
  [13.4, "CALLER",     "okay, okay—",                     null],
  [14.6, "CALLER",     "he's maybe 50,",                  null],
  [15.4, "CALLER",     "I think it's a heart attack,",    "medical",  "heart attack"],
  [16.6, "DISPATCHER", "Stay with me. Help is two minutes out.", null],
];

export const TRANSCRIPT: TranscriptEntry[] = RAW_TRANSCRIPT.map(
  ([t, speaker, text, kw]) => ({ t, speaker, text, kw: kw ?? null })
);

export const AGENTS: Agent[] = [
  { id: "stream",      name: "Stream Processor", short: "STREAM",       accent: "running",   icon: "mic"     },
  { id: "coordinator", name: "Coordinator",      short: "COORDINATOR",  accent: "indigo",    icon: "brain"   },
  { id: "navigation",  name: "Navigation",       short: "NAVIGATION",   accent: "cyan",      icon: "compass" },
  { id: "medical",     name: "Medical",          short: "MEDICAL",      accent: "critical",  icon: "heart"   },
  { id: "hazmat",      name: "Fire / Hazmat",    short: "FIRE/HAZMAT",  accent: "hazmat",    icon: "flame"   },
  { id: "report",      name: "Report",           short: "REPORT",       accent: "ok",        icon: "doc"     },
  { id: "haiku",       name: "Haiku Verifier",   short: "HAIKU VERIFY", accent: "yellow",    icon: "bolt"    },
];

export const EVENTS: DashboardEvent[] = [
  // Stream is always listening from t=0
  { t: 0.0,  type: "agent",    agent: "stream",     state: "listening" },
  { t: 0.1,  type: "timeline", icon: "●",           label: "Session started — INC-20260516-001" },

  // Location keyword fires
  { t: 2.5,  type: "timeline", icon: "◎",           label: "LocationWatcher fired → Navigation Agent triggered" },
  { t: 2.5,  type: "agent",    agent: "navigation", state: "triggered" },
  { t: 2.9,  type: "agent",    agent: "navigation", state: "running" },
  { t: 2.9,  type: "log",      agent: "navigation", line: { ts: "14:22:03.141", text: "Triggered by LocationWatcher" } },
  { t: 3.0,  type: "log",      agent: "navigation", line: { ts: "14:22:03.142", text: 'context_so_far: "...1420 East Pike Street..."' } },
  { t: 3.1,  type: "log",      agent: "navigation", line: { ts: "14:22:03.201", text: "Querying aria-units table (type: ambulance)" } },

  // Medical keyword fires
  { t: 3.7,  type: "timeline", icon: "◎",           label: "MedicalWatcher fired → Medical Agent triggered" },
  { t: 3.7,  type: "agent",    agent: "medical",    state: "triggered" },
  { t: 4.0,  type: "agent",    agent: "medical",    state: "running" },
  { t: 4.0,  type: "log",      agent: "medical",    line: { ts: "14:22:04.012", text: "Triggered by MedicalWatcher: 'not breathing'" } },
  { t: 4.1,  type: "log",      agent: "medical",    line: { ts: "14:22:04.103", text: "Knowledge Base query: AHA cardiac arrest protocol" } },
  { t: 4.2,  type: "log",      agent: "navigation", line: { ts: "14:22:03.340", text: "Found 3 available units" } },
  { t: 4.3,  type: "log",      agent: "navigation", line: { ts: "14:22:03.341", text: "Calculating ETAs via Google Maps API…" } },

  // Coordinator + Haiku come online
  { t: 4.6,  type: "agent",    agent: "coordinator", state: "running" },
  { t: 4.6,  type: "agent",    agent: "haiku",       state: "running" },
  { t: 4.8,  type: "log",      agent: "coordinator", line: { ts: "14:22:04.621", text: "Awaiting Navigation + Medical results" } },

  // Report agent starts logging
  { t: 5.0,  type: "agent",    agent: "report",     state: "running" },

  // Haiku verifier confirms
  { t: 5.8,  type: "agent",    agent: "haiku",      state: "complete" },
  { t: 5.8,  type: "timeline", icon: "✓",           label: "Haiku verify — incident_type: cardiac_arrest, severity: critical" },

  // Navigation returns at ~T+6s
  { t: 6.4,  type: "log",      agent: "navigation", line: { ts: "14:22:04.812", text: "MED-1 → 4 min ETA ✓" } },
  { t: 6.5,  type: "log",      agent: "navigation", line: { ts: "14:22:04.813", text: "MED-3 → 7 min ETA" } },
  { t: 6.6,  type: "log",      agent: "navigation", line: { ts: "14:22:04.814", text: "MED-2 → 9 min ETA" } },
  { t: 6.7,  type: "log",      agent: "navigation", line: { ts: "14:22:04.815", text: "Best unit: MED-1 (4 min, Station 10)" } },
  { t: 6.8,  type: "log",      agent: "navigation", line: { ts: "14:22:04.821", text: "COMPLETE — elapsed: 1680ms" } },
  { t: 6.8,  type: "agent",    agent: "navigation", state: "complete" },
  { t: 6.8,  type: "timeline", icon: "✓",           label: "Navigation complete — MED-1 dispatched (4 min ETA)" },
  { t: 6.8,  type: "partial_approval", value: true },
  { t: 6.8,  type: "map",      marker: "unit",      id: "MED-1" },
  { t: 6.8,  type: "map",      marker: "route" },
  { t: 6.9,  type: "rec_section", section: "navigation", payload: {
    unit: "MED-1",
    unit_type: "Ambulance",
    eta_min: 4,
    station: "Station 10",
    elapsed: "1.7s",
  }},

  // Hazmat decided not needed (skipped)
  { t: 7.5,  type: "agent",    agent: "hazmat",     state: "skipped" },

  // Medical returns at ~T+9s
  { t: 8.2,  type: "log",      agent: "medical",    line: { ts: "14:22:08.220", text: "Closest cardiac-capable: Harborview Medical Center" } },
  { t: 8.4,  type: "log",      agent: "medical",    line: { ts: "14:22:08.401", text: "Sending pre-alert to hospital API…" } },
  { t: 8.9,  type: "log",      agent: "medical",    line: { ts: "14:22:08.912", text: "Hospital reply: ACCEPTING (Trauma Bay 2)" } },
  { t: 9.0,  type: "log",      agent: "medical",    line: { ts: "14:22:09.014", text: "Protocol: BLS — assess ABCs, AED on standby" } },
  { t: 9.0,  type: "log",      agent: "medical",    line: { ts: "14:22:09.021", text: "COMPLETE — elapsed: 5009ms" } },
  { t: 9.0,  type: "agent",    agent: "medical",    state: "complete" },
  { t: 9.0,  type: "timeline", icon: "✓",           label: "Medical complete — Harborview accepting (Trauma Bay 2)" },
  { t: 9.0,  type: "map",      marker: "hospital" },
  { t: 9.1,  type: "rec_section", section: "medical", payload: {
    hospital: "Harborview Medical Center",
    eta_min: 8,
    status: "Accepting",
    bay: "Trauma Bay 2 ready",
    protocol: "BLS — assess ABCs, AED on standby",
    elapsed: "5.0s",
    citations: [
      { source_name: "AHA 2020 Cardiac Arrest Guidelines", doc_id: "aha-2020-cpr" },
      { source_name: "ARIA KB — cardiac_arrest_protocol",  doc_id: "kb-cardiac-001" },
    ],
  }},

  // Coordinator synthesizes
  { t: 11.4, type: "agent",    agent: "coordinator", state: "complete" },
  { t: 11.4, type: "timeline", icon: "✓",            label: "Coordinator card ready" },
  { t: 11.4, type: "rec_ready", confidence: 0.92, summary:
    "Cardiac arrest confirmed. Closest ALS unit dispatched. Harborview accepting with trauma team on standby." },

  // Dispatcher approves
  { t: 14.2, type: "timeline", icon: "⚡",           label: "Dispatcher approved — DISPATCH UNIT NOW" },
  { t: 14.2, type: "approved", value: "partial" },
  { t: 14.4, type: "timeline", icon: "✓",            label: "Dispatch event logged → DynamoDB" },
  { t: 14.4, type: "unit_state", unit: "MED-1",      state: "en_route" },
  { t: 14.4, type: "unit_state", unit: "MED-3",      state: "staging" },

  // Report agent finishes and session closes
  { t: 16.0, type: "agent",    agent: "report",     state: "complete" },
  { t: 16.0, type: "timeline", icon: "✓",            label: "Report Agent — after-action report generated" },
  { t: 16.5, type: "session_end",
    report_url: "https://aria-reports.s3.amazonaws.com/demo/INC-20260516-001-report.pdf",
  },
];

export const SCENARIO_DURATION = 18;
