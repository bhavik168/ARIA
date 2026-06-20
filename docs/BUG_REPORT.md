# ARIA — System Bug Report

**Date:** 2026-05-30
**Scope:** Full-stack review of the ARIA pipeline (frontend `frontend/src`, backend `backend/lambdas/*`, shared utils, and the `docs/INFRASTRUCTURE.md` deployment guide).
**Method:** Static read of every handler and React component, cross-checked against the documented event contract (`docs/ARIA_Architecture.md`) and the documented IAM/Lambda setup (`docs/INFRASTRUCTURE.md`). No code was changed.

This report catalogs defects only. Each entry lists **severity**, **location**, **symptom**, **root cause**, and **impact**. Severities:

- **P0 – Blocker:** breaks the primary demo path (a card never appears, or wrong data appears).
- **P1 – Major:** a documented feature silently doesn't work.
- **P2 – Moderate:** degraded behavior, wrong values, or fragile design.
- **P3 – Minor:** cosmetic, docs, or latent.

---

## Executive Summary

The single most user-visible class of bugs is a **field-name contract mismatch between every backend agent and the React `handleEvent` reducer in `frontend/src/App.tsx`.** The backend emits `eta_minutes`, `evacuation_radius_meters`, `protective_equipment`, `er_status`; the frontend reads `eta_min`, `evacuation_radius_m`, `gear`, `status`. The result is that the recommendation card renders **structural placeholders and internal fallback strings** (e.g. "Seattle, WA — location pending", "Fallback synthesis — Sonnet unavailable", "ETA 0 min") **directly to the dispatcher** — which is the "panel shows backend errors/notes directly on the front end" symptom.

The second major class is **deployment-contract drift**: `docs/INFRASTRUCTURE.md` does not deploy the `aria-verifier` Lambda at all, the IAM roles omit `bedrock:InvokeModel` for the three tool Lambdas that call Claude, and `aria-ingest`'s role can only invoke `aria-stream-processor` — so the coordinator trigger at `transcript_complete` (the end-of-call card in the main simulation demo) fails with AccessDenied.

The third is an **architectural correctness issue**: the stream processor keeps per-incident state (`_context_buffer`, `_word_count`, `_watcher_fired`) in module-level memory, but words are delivered via fan-out `InvocationType="Event"` across up to 10 provisioned containers — so that state is split and out of order.

---

## P0 — Blockers

### P0-1. Recommendation card fields never populate (backend↔frontend key mismatch)
**Location:** `frontend/src/App.tsx:224-262` (`agent_complete` handler) vs. backend agent return shapes.

The frontend reads field names the backend never sends:

| Section | Frontend reads (`App.tsx`) | Backend actually returns | File |
|---|---|---|---|
| Navigation | `u.eta_min`, `u.station` | `eta_minutes`, (no `station`) | `aria-navigation-tool/handler.py:189-195` |
| Medical | `h.eta_min`, `h.status` | `eta_minutes`, `er_status` | `aria-medical-tool/handler.py:237-243` |
| Hazmat | `res.evacuation_radius_m`, `res.gear`, `res.summary` | `evacuation_radius_meters`, `protective_equipment`, `suppression_approach`/`priority_action` (no `summary`) | `aria-hazmat-tool/handler.py:31-45,146-171` |

**Symptom:** Navigation shows "ETA 0 min", medical shows "ETA 0 min" with a blank ER status, and the entire Fire/Hazmat block renders empty (no summary, no evac radius, no PPE).
**Impact:** The core deliverable — the recommendation card — displays zeros and blanks even when every agent succeeded.

### P0-2. `aria-ingest` cannot invoke the coordinator → no final card in simulation mode
**Location:** `docs/INFRASTRUCTURE.md` Role 1 (`aria-ingest-role`, lines ~126-152) vs. `aria-ingest/handler.py:177-185, 267-277`.

The ingest role grants `lambda:InvokeFunction` on `arn:...:function:aria-stream-processor*` **only**. But `aria-ingest`:
- invokes `aria-coordinator` at `transcript_complete` (`handler.py:267`), and
- invokes coordinator/navigation/medical/hazmat/verifier during `_warmup` (`handler.py:94-100`).

**Symptom:** Every coordinator/warmup invoke from ingest fails with `AccessDeniedException`, caught and logged but otherwise silent. The end-of-call synthesis (the moment the full card is supposed to appear in the primary "Run backend simulation" demo) never runs.
**Impact:** In the main demo path the final recommendation card is never produced by the transcript-complete trigger.

### P0-3. `aria-verifier` is never deployed, and the stream processor cannot invoke it
**Location:** `docs/INFRASTRUCTURE.md` §5 "Lambda Functions — 10 Functions" (no `aria-verifier`); Role 2 `aria-stream-processor-role` (no verifier ARN). Code: `aria-stream-processor/handler.py:31,141-144,273-290`; `aria-ingest/handler.py:38,92-93`.

The verifier is the semantic classifier that the architecture relies on to upgrade severity, correct incident type, and trigger missed agents. The deployment guide documents only 10 functions and **does not create `aria-verifier`** (nor an `aria-verifier-role`). The stream-processor role also does not list the verifier ARN under `lambda:InvokeFunction`.
**Symptom:** `_fire_verifier` invokes a non-existent function (or one it lacks permission for); the call fails silently. `verifier_classification` is never written to DynamoDB, so `_apply_verifier_enrichment` (`aria-coordinator/handler.py:436-498`) always no-ops.
**Impact:** Severity upgrades, incident-type corrections, victim-count estimates, and "missed agent" triggers never happen. Severity stays at the default for the whole pipeline.

### P0-4. Tool Lambdas call `bedrock:InvokeModel` but their IAM roles don't grant it
**Location:** `docs/INFRASTRUCTURE.md` Roles 4/5/6 vs. code.

- **Navigation** (`aria-navigation-tool-role`) grants no Bedrock action at all, but `_nlp_extract_address` calls `bedrock_runtime.invoke_model` (`aria-navigation-tool/handler.py:118-150`).
- **Medical** (`aria-medical-tool-role`) grants `bedrock:Retrieve` only, but `_interpret_protocol` calls `invoke_model` (`aria-medical-tool/handler.py:197-213`).
- **Hazmat** (`aria-hazmat-tool-role`) grants `bedrock:Retrieve` only, but `_interpret_hazard_data` calls `invoke_model` (`aria-hazmat-tool/handler.py:173-191`).

**Symptom:** Each `invoke_model` throws `AccessDeniedException`, which is swallowed by the fallback paths. Navigation address always falls back to **"Seattle, WA — location pending"**; medical triage falls back to the raw KB chunk; hazmat interpretation returns `{}`.
**Impact:** All "AI enrichment" in the three specialist tools is dead; the dispatcher sees raw/placeholder text. This is a primary contributor to the "backend strings shown on the front end" complaint.

### P0-5. Model IDs in code don't match the model access the deploy guide tells you to enable
**Location:** `aria-coordinator/handler.py:45-48`, `aria-medical-tool/handler.py:31-34`, `aria-navigation-tool/handler.py:137` use `us.anthropic.claude-sonnet-4-5-20250929-v1:0`. `docs/INFRASTRUCTURE.md` §1 tells the operator to enable **Claude Sonnet 4** (and Haiku 3.5, Titan v2) — not Sonnet 4.5. `aria-report/handler.py:28-31` uses Sonnet 4 (`claude-sonnet-4-20250514`); `.env.example` lists yet another set (`anthropic.claude-sonnet-4-20250514` without the `us.` cross-region prefix).
**Symptom:** If the operator follows the guide, Sonnet 4.5 access is never granted → coordinator synthesis, medical, and navigation model calls fail with AccessDenied and fall back.
**Impact:** Coordinator card synthesis silently degrades to the Python fallback (`_synthesize_card_fallback`) which writes the literal string **"Fallback synthesis — Sonnet unavailable."** into `reasoning_summary`, shown verbatim on the dashboard.

---

## P1 — Major

### P1-1. The after-action report is never generated by the live pipeline
**Location:** `aria-coordinator/handler.py:179` and `:153-235`.

The coordinator only ever invokes the report Lambda with `{"action": "start_logging"}` (which returns immediately, `aria-report/handler.py:44-46`). Nothing ever invokes `aria-report` with the default `generate_report` action at incident close.
**Symptom:** No report JSON/markdown is written to S3 in the real pipeline; `report_generated` is never emitted.
**Impact:** The "Download Report" affordance in `RecCard` never appears in backend mode.

### P1-2. Even if the report ran, the frontend ignores its event
**Location:** `aria-report/handler.py:67-71` emits `{type: "report_generated", report_url}`. `frontend/src/App.tsx:154-323` has **no `report_generated` case** — it only sets `reportUrl` from a `session_end` event (`App.tsx:312-322`), which no backend Lambda ever emits.
**Impact:** Report URL never reaches the UI. (Also note `report_url` is an `s3://` URI — not browser-openable even if wired; see P2-9.)

### P1-3. Frontend drops most of the synthesized card
**Location:** `frontend/src/App.tsx:265-276` (`recommendation_ready`).

The handler reads only `summary`, `reasoning_summary`, and `ai_confidence`. It ignores `severity`, `incident_type`, `dispatcher_action`, `triage_protocol`, and `hazard_warnings` that the coordinator carefully produces (`aria-coordinator/handler.py:300-310`).
**Impact:** Severity/incident classification and the explicit dispatcher action never drive the UI (compounds P1-4).

### P1-4. Severity and confidence label are hardcoded in the UI
**Location:** `frontend/src/App.tsx:754` (`<TopBar severity="critical">`), `App.tsx:801` (`<RecCard severity="critical">`), and `frontend/src/components/RecCard.tsx:400` (`{(confidence * 100).toFixed(0)}% · HIGH`).
**Symptom:** Every incident renders a red **CRITICAL** badge and a **HIGH** confidence label regardless of the backend's computed severity (`critical|urgent|moderate|minor`) or confidence (`high|medium|low`).
**Impact:** Severity-coded triage — a headline feature — is fake; a "low confidence" recommendation still shows "HIGH".

### P1-5. Specialist agents never enter the "running" state in the UI
**Location:** `frontend/src/App.tsx:219-222` only flips `running` on `agent_started`, but only the coordinator emits `agent_started` (for itself, `aria-coordinator/handler.py:86`). Navigation/medical/hazmat emit only `agent_complete`.
**Symptom:** The nav/med/hazmat cards jump straight from `idle` ("◌ PENDING") to `complete`; the documented "pulsing Running" stage (Architecture §8) never occurs. For non-fire incidents the hazmat card sits at "PENDING" forever (nothing ever sets it to `skipped`, which is the only state `RecCard.tsx:122-129` treats as "NOT TRIGGERED").
**Impact:** Misleading status; hazmat looks perpetually stuck.

### P1-6. `transcript_complete` / WS keepalive ping has no route in the deploy guide
**Location:** `backend/lambdas/aria-ws-default/handler.py` exists, but `docs/INFRASTRUCTURE.md` §8 wires only `$connect` and `$disconnect` (no `$default`). The frontend sends `{action:"ping"}` every 20s (`App.tsx:357-360`).
**Symptom:** With no `$default` integration, API Gateway can't route the ping and may error/close the socket.
**Impact:** Keepalive may actively break the connection it's meant to preserve; falls back to dead polling (P2-6).

### P1-7. Per-word fan-out corrupts the stream processor's in-memory state
**Location:** `aria-stream-processor/handler.py:81-86` (module-level `_context_buffer`, `_word_count`, `_watcher_fired`, etc.) combined with `InvocationType="Event"` per word (`aria-ingest/handler.py:248-252, 362-366`) and Provisioned Concurrency 10 (`docs/INFRASTRUCTURE.md` §6).
**Root cause:** Each word is an independent async invocation. AWS distributes these across multiple warm containers with no ordering guarantee. The "growing transcript" buffer, the per-incident word counter, and the "fired once" watcher set are therefore **split across containers and processed out of order**.
**Symptom:** `transcript_so_far` pushed to the dashboard is partial; watchers fire multiple times (once per container that crosses the threshold); the coordinator's `COORDINATOR_FIRST_TRIGGER`/refire math is per-container, not per-incident.
**Impact:** Non-deterministic triggering and incomplete context. The DynamoDB checkpoint (`:138-139`) doesn't reconcile this — it overwrites with whichever container last hit a 10-word multiple.

### P1-8. Override reason is silently lost (field-name mismatch)
**Location:** `frontend/src/App.tsx:699-707` posts `{reason, notes}`; `aria-coordinator/handler.py:420-433` reads `override_reason`, `dispatcher_choice`, `aria_recommendation`.
**Symptom:** `override_reason` always falls back to its default `"Other"`; the dispatcher's actual reason and the ARIA recommendation are never recorded.
**Impact:** The override audit trail (a stated safety/compliance feature, Architecture §7) records "Other" for everything.

### P1-9. Coordinator re-runs everything on every trigger (no dedup/idempotency)
**Location:** `aria-stream-processor/handler.py:236-241` fires the coordinator at word 25 and every 60 words; `aria-ingest/handler.py:267` fires again at `transcript_complete`. `aria-coordinator` has no per-incident lock.
**Symptom:** A single ~150-word call triggers 3-4 full coordinator passes, each re-invoking all specialist agents + a Sonnet synthesis. Multiple `recommendation_ready` cards race and overwrite each other on the dashboard.
**Impact:** Duplicate Bedrock spend, throttling risk, and a flickering/last-writer-wins card.

---

## P2 — Moderate

### P2-1. `concurrent.futures` timeout can crash the whole coordinator pass
**Location:** `aria-coordinator/handler.py:225` — `as_completed(futures, timeout=max(AGENT_TIMEOUTS.values()))` (10s). If any agent (notably `report`, or a slow Bedrock agent) exceeds 10s, `as_completed` raises `TimeoutError` that is **not caught** inside `_run_specialist_agents`, propagating out and aborting synthesis. The per-agent `AGENT_TIMEOUTS` dict (`:51-56`) is otherwise unused — individual invokes are never actually bounded.
**Impact:** One slow agent fails the entire card instead of degrading gracefully.

### P2-2. Float values crash DynamoDB writes in hazmat/coordinator
**Location:** Only `aria-medical-tool/handler.py:267-275` converts `float → Decimal`. `aria-hazmat-tool/handler.py:202-208` and `aria-coordinator/handler.py:512-518` write model-parsed JSON directly. If a model emits `evacuation_radius_meters: 300.0` (or Sonnet emits any decimal), boto3 raises `TypeError: Float types are not supported`.
**Impact:** Intermittent hazmat/coordinator persistence failures depending on model output formatting.

### P2-3. Transcribe speaker labels are read from the wrong place
**Location:** `aria-ingest/handler.py:347-359`. The code reads `word_item.get("speaker_label")` off each item in `results.items`, but Amazon Transcribe places speaker labels in the separate `results.speaker_labels.segments` structure, not on the word items.
**Symptom:** `speaker` is always the default `spk_0` → everything is labeled **CALLER**; the dispatcher's turns never appear.

### P2-4. `MediaFormat="wav"` is hardcoded but uploads accept any type
**Location:** `aria-ingest/handler.py:293` vs. presign accepting arbitrary `content_type` (`:109-120`).
**Symptom:** Uploading an mp3/m4a starts a Transcribe job that fails (`FAILED`); the UI just spins with no words and no error surfaced.

### P2-5. Per-word async invokes in transcribe mode flood and reorder
**Location:** `aria-ingest/handler.py:346-366` fires every transcript word as a separate `Event` invoke with **no inter-word delay** (unlike simulation mode, which sleeps `delay_ms`). Hundreds of near-simultaneous invokes hit the stream processor.
**Impact:** Compounds P1-7 (ordering), produces a burst instead of a live word-by-word feed, and multiplies Lambda invocations.

### P2-6. Polling fallback never stops and produces no UI updates
**Location:** `frontend/src/App.tsx:329-344`. Polls `/session/{id}/status` and stops only when `data.status === "complete" || "failed"`, but the backend only ever sets `"ingesting"` / `"transcript_complete"` (`aria-ingest/handler.py:262,373`). It also never dispatches any event from the polled payload.
**Impact:** If the WebSocket drops, the poller spins forever every 3s and the UI receives nothing.

### P2-7. `transcript_word` timestamps mix client and server clocks
**Location:** `frontend/src/App.tsx:173-183`. `relSec = (ev.timestamp_ms − sessionStartEpochRef)/1000`, where `sessionStartEpochRef` is the browser's `Date.now()` (`:430,493`) but `ev.timestamp_ms` is the Lambda's `time.time()*1000`.
**Symptom:** Clock skew makes `relSec` negative (clamped to 0 by `Math.max`) or large. With everything clamped to 0, `TranscriptFeed`'s grouping (`e.t − last.endT < 2.5`, `TranscriptFeed.tsx:30`) collapses the whole call into one block with a 00:00 timestamp.

### P2-8. Internal fallback strings are surfaced to the dispatcher
**Location / strings:**
- `"Seattle, WA — location pending"` → card address (`aria-navigation-tool/handler.py:149-150` → `App.tsx:231-232`).
- `"Fallback synthesis — Sonnet unavailable."` → reasoning (`aria-coordinator/handler.py:356`).
- `"Verifier fallback — no classification available"` (`aria-verifier/handler.py:167`).
- `"Pre-alert delivery pending"` (`aria-medical-tool/handler.py:264`).
- Raw KB chunk text as the triage protocol when the model call fails (`aria-medical-tool/handler.py:212-213` → `RecCard.tsx:316`).

**Impact:** These are internal degradation markers, not dispatcher-facing copy, but they render verbatim in the card. This is the literal "backend errors/notes shown directly on the front end" symptom.

### P2-9. Report URL is an `s3://` URI, not downloadable
**Location:** `aria-report/handler.py:66,91` build `report_url = f"s3://{ARIA_BUCKET}/{key}"`. `RecCard.tsx:453-459` renders it as an `<a href>` "Download Report".
**Impact:** Even if wired (it isn't — P1-2), the link is not browser-resolvable; it needs a presigned GET URL.

### P2-10. Events the frontend silently ignores
**Location:** `frontend/src/App.tsx` switch (`:154-323`). Backend emits these with no handler:
- `context_enrichment` (verifier + coordinator) — `aria-verifier/handler.py:239`, `aria-coordinator/handler.py:490`.
- `partial_approval_available` — `aria-coordinator/handler.py:230` (frontend only handles `partial_approval`/`approved`).
- `guardrail_blocked` — `aria-coordinator/handler.py:102`. If a card is blocked, the dispatcher sees **nothing at all** (no card, no message).

**Impact:** Enrichment never reflected; guardrail blocks are invisible (a safety concern).

### P2-11. Stale WebSocket connections accumulate
**Location:** `_push_to_dashboard` in `aria-coordinator`, `aria-medical-tool`, `aria-navigation-tool`, `aria-hazmat-tool`, `aria-report` use `except Exception: pass` and never delete `GoneException` connections (only `aria-stream-processor/handler.py:333-334` and the unused shared util do). The shared `backend/shared/utils/websocket.py` (which does clean up) is **never imported anywhere**.
**Impact:** Dead connection rows pile up in `aria-ws-connections`; every push iterates them, repeatedly hitting `GoneException`.

### P2-12. No authentication or authorization on any route
**Location:** `docs/INFRASTRUCTURE.md` §7 (REST) and all handlers respond with `Access-Control-Allow-Origin: *` and no authorizer. Anyone who can reach the API can start sessions, approve dispatch, and submit overrides.
**Impact:** For a dispatch-control surface this is a significant gap (acceptable only for a closed demo; should be called out).

---

## P3 — Minor / Docs / Latent

### P3-1. Frontend env var name mismatch between code and the setup guide
`docs/INFRASTRUCTURE.md` §10 instructs setting `VITE_API_URL`, but the code reads `VITE_API_BASE_URL` (`frontend/src/App.tsx:36`; `frontend/.env.example` correctly uses `VITE_API_BASE_URL`). Following the guide leaves `API_BASE` empty and all REST calls hit a relative URL.

### P3-2. `dead `rec_section` path
`App.tsx:187-217` normalizes a `rec_section` event that no backend Lambda emits (only the local simulation uses it). Harmless but signals contract drift.

### P3-3. Deploy-guide checklist contradictions
`docs/INFRASTRUCTURE.md` "Completion Checklist" says "4 S3 buckets" while §3 creates **1** bucket; says "10 IAM roles" / "10 Lambda functions" while the system actually needs an 11th (`aria-verifier`) plus an `aria-ws-default` route. The §1 model-access list omits Sonnet 4.5 (see P0-5).

### P3-4. Audio duration hardcoded
`frontend/src/App.tsx:770-771` pins total/elapsed audio length to `163000` ms for any uploaded file. The progress bar is wrong for any clip that isn't 2:43.

### P3-5. `_wait_for_ws_connection` bails on first exception
`aria-ingest/handler.py:217-219` `return False` lives inside the `except` within the retry loop, so a single transient query error aborts the wait instead of retrying. Also the comment in `_start_session` (`:148-149`) references a "3s sleep in the handler" that doesn't exist; the real wait is ≤2s (`:203`), so the first words can fire before the browser registers its WebSocket → lost opening words.

### P3-6. `.env.example` placeholder noise
`AWS_PROFILE=your_account_name here` (embedded space) and `ARIA_BUCKET=you-bucket_name_here` are invalid literal values that will be copied verbatim by an operator who misses them.

### P3-7. Guardrail "reason" leaks masked output
`aria-coordinator/handler.py:386-389` uses `outputs[0]["text"]` (the guardrail's masked/blocked text) as the human-readable `reason` pushed to the dashboard, rather than the policy/topic name.

### P3-8. `_synthesize_card_fallback` confidence logic
`aria-coordinator/handler.py:345-357` computes `agents_ok` over `(nav, med)` only — hazmat-only (fire) incidents are judged on agents that may not have run, and `severity` is hardcoded to `"urgent"` in the fallback regardless of input.

---

## Suggested Fix Ordering

1. **Unblock the demo:** P0-2, P0-3, P0-4, P0-5 (IAM + model-access + verifier deployment), then P0-1 (field-name contract).
2. **Make the card truthful:** P1-3, P1-4, P1-5 (severity/confidence/running state) and P2-8 (stop surfacing fallback strings).
3. **Close the loop:** P1-1, P1-2, P2-9 (report generation + downloadable URL), P1-8 (override fields).
4. **Harden the pipeline:** P1-7/P2-5 (stateful fan-out), P1-9/P2-1 (coordinator idempotency + timeout handling), P2-2 (Decimal), P2-3/P2-4 (Transcribe).
5. **Polish:** P2-6, P2-7, P2-10, P2-11, P2-12, and the P3 docs items.

---

*Generated as a read-only audit. No source files were modified. Line references reflect the repository state at the time of review.*
