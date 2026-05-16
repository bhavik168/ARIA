# ARIA — Autonomous Response Intelligence Assistant
### Emergency Incident Intelligence System | Built on Amazon Bedrock

---

## Overview

ARIA is a multi-agent AI system built on Amazon Bedrock that acts as a real-time co-pilot for 911 dispatchers. When an emergency call comes in, ARIA listens, reasons, routes, and coordinates across six specialized agents — surfacing a single actionable recommendation to the dispatcher in seconds, so the human can focus entirely on the person on the other end of the line.

> "Every second costs a life. We gave dispatchers an AI co-pilot that thinks in milliseconds."

---

## System Architecture — Layer by Layer

---

### Layer 1 — Input: Pre-Recorded 911 Call Audio

**What it is:** The entry point of the system. For this open-source demo, ARIA ingests pre-recorded 911 call audio files (pulled from public datasets or recorded simulations). The audio is streamed to Amazon Transcribe for processing.

**Why it matters:** Using real 911 audio validates the core speech-to-intelligence pipeline end-to-end. It demonstrates ARIA's ability to handle genuine caller distress patterns, background noise, and fragmented speech — the exact conditions dispatchers face daily.

---

### Layer 2 — Amazon Transcribe (Speech to Text)

**AWS Service:** Amazon Transcribe (Streaming)

**What it does:** As the pre-recorded 911 audio streams in, Amazon Transcribe converts the caller's voice into a live text transcript — word by word. The transcript is fed directly to the Dispatcher Agent as it is generated.

**Why it matters:** This validates ARIA's core speech-to-intelligence capability using real emergency audio. Every word the caller says is captured, timestamped, and passed downstream automatically — nothing is lost, nothing is misheard.

**Key capability:** Supports 185+ languages and dialects, meaning non-English speaking callers are no longer a source of dangerous delay.

---

### Layer 3 — Stream Processor + Domain Watchers

**AWS Service:** AWS Lambda — `aria-stream-processor` (Provisioned Concurrency: 10)

**What it does:** The Stream Processor is the real-time spine of ARIA. It receives every word from Transcribe the moment it is stabilized and does four things in under 1ms — no batching, no buffering, no waiting:

1. **Broadcasts to dashboard WebSocket** — every word appears on the dispatcher's live transcript immediately, word by word
2. **Appends to in-memory context buffer** — the full growing transcript is always available to any agent that fires, checkpointed async to DynamoDB every 10 words
3. **Runs domain watchers in-process** — pure Python pattern matching, zero network hops, sub-millisecond:
   - `LocationWatcher` → triggers Navigation Agent the moment a street address, intersection, or zip code is detected
   - `MedicalWatcher` → triggers Medical Agent on keywords like "not breathing", "chest pain", "seizure", "overdose"
   - `FireWatcher` / `HazmatWatcher` → triggers Fire/Hazmat Agent on fire and chemical keywords
   - `CrimeWatcher` → triggers Navigation Agent for police dispatch on weapon/crime keywords
   - `SeverityWatcher` → sends severity upgrade to Coordinator on mass casualty keywords
4. **Fires agents asynchronously** — each agent invocation is `InvocationType: Event` (fire and forget). The stream processor returns to the next word immediately. Nothing blocks, nothing waits.

**De-duplication:** Each watcher fires once per incident. If new critical information arrives (a second location, a second victim count), the watcher fires again with the updated full context.

**Why it matters:** In a batched model, words are held until a chunk is assembled, sent to an LLM, and only then does downstream processing begin. By the time the LLM responds, the caller has said 15 more words the system never processed in time. With the Stream Processor, the moment the caller says a street address, the Navigation Agent fires — with the full transcript up to that word. No information is ever lost. No word is ever late.

---

#### Claude Haiku 3.5 — Parallel Verifier (not a gatekeeper)

**AWS Service:** Amazon Bedrock — Claude Haiku 3.5

**What it does:** Claude Haiku no longer sits on the critical blocking path. It runs in parallel with the already-launched agents as a verifier and enricher — invoked async every 15 seconds or when the first domain watcher fires:

- Resolves location ambiguities pattern matching can't handle: "near the McDonald's on Fifth" → geocoded address
- Verifies incident type: "I think he had a heart attack" vs confirmed cardiac arrest vs anxiety attack
- Estimates victim count from fragmented speech ("there's like... maybe five people hurt?")
- If Haiku disagrees with a watcher (e.g., caller said "fire" but means a dumpster, not a structure fire), it sends a severity downgrade event to the Coordinator

**Output:** `{ location_confirmed, incident_type_confirmed, severity, victim_count, corrections[] }` — sent to the Coordinator as a context enrichment event. Agents already running when Haiku finishes receive its enrichment mid-run. Haiku adds precision without adding latency to any critical path.

---

### Layer 4 — Coordinator Agent (The Brain)

**AWS Service:** Amazon Bedrock — Claude Sonnet (Bedrock multi-agent orchestration)

**What it does:** The Coordinator Agent is the synthesis intelligence of ARIA. Agents are triggered directly by the Stream Processor's domain watchers — the Coordinator's role is to receive their asynchronous results and produce a unified recommendation. It does three things:

1. **Streams partial results to the dashboard** — the moment any specialist agent completes, its output is pushed to the dispatcher's screen via WebSocket. No agent result waits for another. The dispatcher sees information as it arrives.
2. **Partial approval for critical incidents** — the moment the Navigation Agent returns (T+6–8s), a "Dispatch Unit Now" button appears for `severity: critical` incidents. The dispatcher dispatches the unit immediately — before the Medical and Hazmat agents finish, before the full card is ready. Two independent approvals, with the most time-critical one always first.
3. **Synthesizes the final card** — once all agents complete or hit their hard timeout, the Coordinator reconciles conflicts (two agents recommending different hospitals, competing unit assignments), prioritizes by severity, and activates the full recommendation card with the "Approve All" button.

**Why Claude Sonnet:** The Coordinator needs multi-step reasoning to balance competing priorities, synthesize four domain-specific inputs, and produce a single coherent recommendation. Sonnet handles nuanced conflict resolution that a pattern matcher cannot.

**Why it matters:** Without ARIA, a dispatcher manually reads inputs from CAD, radio, hospital systems, and mapping software — then makes a decision under pressure. The Coordinator collapses all of that into a single surface. The dispatcher reviews, not researches. And in critical incidents, they act before the full picture is even complete.

**Bedrock feature used:** Multi-agent result synthesis via Bedrock Agents, with sub-agent ARNs configured in the Coordinator's action group. The Coordinator also receives context enrichment from the Haiku verifier mid-synthesis.

---

### Layer 5 — Four Specialist Agents (Parallel Execution)

All four agents run simultaneously the moment the Coordinator spawns them. Each is a purpose-built Bedrock agent with its own system prompt, tool configuration, and Knowledge Base access.

---

#### Agent A — Navigation Agent

**AWS Services:** Amazon Bedrock Agent, AWS Lambda (Google Maps API), DynamoDB (unit availability)

**What it does:**
- Queries the real-time location of all available emergency units from DynamoDB
- Calculates ETAs to the incident location using the **real Google Maps API** with live traffic conditions
- Identifies the optimal unit or combination of units to dispatch
- Generates a **real turn-by-turn route** via Google Maps Directions API
- On dispatcher approval, the route and incident summary are **logged as a dispatch event** — no actual mobile push. The system simply records: `route_assigned`, `unit_id`, `destination`, `turn_by_turn_url`

**Real-world impact:** Dispatchers currently switch between a CAD system and a separate mapping tool, manually radio units, and wait for acknowledgment. The Navigation Agent completes route calculation in under three seconds using real navigation data. In production, this would push directly to a responder's mobile device via SNS.

---

#### Agent B — Medical Agent

**AWS Services:** Amazon Bedrock Agent, Bedrock Knowledge Base (medical protocols), Lambda (mock hospital API)

**What it does:**
- Queries the Bedrock Knowledge Base for the appropriate medical triage protocol based on the reported injury or condition
- Identifies the closest hospital with the right capability (trauma bay, burn unit, pediatric, cardiac catheterization)
- Sends a pre-alert to the **Mock Hospital API** — a simulated external hospital system that replies with readiness status, bed availability, and confirmation
- Surfaces the hospital's reply (accepted / redirected / preparing) to the Coordinator for the final recommendation card

**Knowledge Base contents:** Medical Priority Dispatch System (MPDS) protocols, AHA cardiac emergency guidelines, trauma triage criteria, pediatric emergency protocols.

**Real-world impact:** Ambulances currently arrive at the wrong hospital or the right hospital unprepared. The Medical Agent ensures the correct facility is identified in seconds and receives the pre-alert — saving critical preparation time at the ER.

---

#### Agent C — Fire / Hazmat Agent

**AWS Services:** Amazon Bedrock Agent, Bedrock Knowledge Base (FEMA hazmat database), Lambda

**What it does:**
- For fire incidents: queries building information, identifies structural risks, recommends suppression approach and protective gear
- For hazmat incidents: identifies chemicals involved, retrieves FEMA hazmat response guidelines, calculates safe evacuation radius based on substance and wind conditions
- Surfaces all hazard intelligence to the Coordinator before units arrive on scene

**Knowledge Base contents:** FEMA Emergency Response Guidebook, NIOSH hazmat protocols, chemical property database, building classification data.

**Real-world impact:** Responders currently arrive at scenes with no prior knowledge of chemical risks, structural instability, or required protective equipment. The Fire/Hazmat Agent surfaces that intelligence during the 4-minute window while units are en route — the only window available to prepare.

---

#### Agent D — Report Agent

**AWS Services:** Amazon Bedrock Agent, DynamoDB, S3

**What it does:**
- Logs every event in the incident timeline live — call received, agents spawned, recommendations generated, dispatcher decisions, units dispatched, hospital notified
- At incident close, automatically generates a complete structured after-action report:
  - Full incident timeline
  - Units dispatched and response times
  - AI recommendations made
  - Dispatcher decisions and overrides
  - Patient outcome data (if available)
- Stores the report in S3 and indexes metadata in DynamoDB for analytics

**Real-world impact:** Dispatchers currently write after-action reports manually after already exhausting shifts. Burnout is the top workforce challenge at 911 centers (NENA 2025 Pulse Report — 70% of telecommunicators report stress before every shift). The Report Agent gives dispatchers back the one thing they never have — time to recover.

---

### Layer 5.5 — Mock External Entities (Demo Simulation)

**What it is:** To demonstrate the full closed-loop dispatch flow without requiring access to real hospital ER systems, ARIA integrates with a **Mock Hospital API** that behaves exactly like a real hospital's ER intake system — receiving pre-alerts and replying back with readiness status. The Navigation Agent uses a **real Google Maps API** for routing and ETAs, but the responder-side dispatch is logged (not pushed to a real device) for this open-source demo.

| Mock Entity | What It Simulates | How It Behaves |
|---|---|---|
| **Mock Hospital System** | A receiving hospital's ER intake API | Receives pre-alert JSON (patient condition, ETA, resources needed). Replies after 1–3 seconds with: `accepting`, `redirecting`, or `preparing`. Simulates bed-capacity logic. |
| **Mock CAD Unit Database** | A Computer-Aided Dispatch system | Stores unit availability, current assignments, and location. Responds to Navigation Agent queries exactly like a real CAD API. |

**Why it matters:** The mock hospital lets judges and open-source users see the **closed-loop medical dispatch** — not just the AI recommending a hospital, but the hospital replying "we're ready." The Navigation Agent still uses real Google Maps data for routes and ETAs. The responder-side push is logged to prove the event was captured, without requiring a real mobile fleet management API. All mocks are lightweight and interchangeable with real vendor endpoints in production.

---

### Layer 6 — Bedrock Knowledge Base

**AWS Services:** Amazon Bedrock Knowledge Base, Amazon S3, Amazon Titan Embeddings

**What it does:** The Knowledge Base is the long-term memory of ARIA. It stores curated, authoritative documents that all specialist agents retrieve from using RAG (Retrieval-Augmented Generation):

| Document Category | Contents |
|---|---|
| Medical protocols | MPDS triage guidelines, AHA protocols, trauma criteria |
| FEMA hazmat database | Emergency Response Guidebook, chemical hazard data |
| Hospital data | ER capacity templates, specialty capability registry |
| Historical incidents | Past incident patterns, outcomes, lessons learned |
| Emergency SOPs | Standard operating procedures by incident type |

**How it works:** When a specialist agent needs to answer a question — "What is the safe evacuation radius for a chlorine leak?" — it sends that query to the Knowledge Base. Titan Embeddings converts the query into a vector, retrieves the most semantically relevant document chunks from S3, and returns them to the agent as grounded context. Claude then reasons over that context to produce an accurate, cited recommendation — not a hallucination.

**Why this matters for judges:** RAG grounding is what separates ARIA from a chatbot. Every recommendation is traceable to a real source document. No agent invents information.

---

### Layer 7 — Bedrock Guardrails (Safety Layer)

**AWS Service:** Amazon Bedrock Guardrails

**What it does:** Bedrock Guardrails is a hard architectural constraint — not a suggestion. It enforces the following rules across every agent in the system:

- **No auto-execution:** No unit is ever dispatched, no hospital is ever alerted, no route is ever pushed without explicit human approval from the dispatcher
- **Hallucination filtering:** Any agent output that contains medical dosages, chemical hazard data, or routing instructions is checked against a defined content policy before surfacing to the dispatcher
- **Sensitive information blocking:** Patient PII, caller location data, and medical history are never surfaced outside the secure dashboard
- **Override logging:** Every dispatcher override — when a human disagrees with ARIA's recommendation — is logged with a timestamp for post-incident review and system improvement

**Why it matters:** AI in emergency response must never remove the human from the loop. ARIA is a co-pilot, not an autopilot. Guardrails is the architectural guarantee of that principle — not a policy document, but a technical enforcement layer.

---

### Layer 8 — Dispatcher Dashboard

**Technology:** React + Tailwind, API Gateway WebSocket, Mapbox GL JS, Vercel hosting

---

#### WebSocket Architecture — The Real-Time Spine

The dashboard is entirely WebSocket-driven. Every event in the pipeline — each transcript word, each domain watcher trigger, each agent completion, each partial result — is pushed to the dispatcher's screen the instant it exists. There is no polling, no page refresh, no full-card loading spinner.

**WebSocket event types:**

| Event | When it fires | What appears on dashboard |
|---|---|---|
| `transcript_word` | Every word from Transcribe (300ms cadence) | Live transcript scrolls word by word |
| `agent_started` | Domain watcher triggers an agent | That agent's status card flips to "Running" with pulsing indicator |
| `agent_complete` | A specialist agent returns its output | That agent's section of the recommendation card fills in immediately |
| `partial_approval_available` | Navigation Agent returns, severity is critical | "Dispatch Unit Now" button appears — dispatcher dispatches before full card is ready |
| `recommendation_ready` | Coordinator synthesizes final card | Full recommendation card activates, "Approve All" button enabled |
| `hospital_response` | Mock Hospital API replies with readiness status | ER status badge updates (accepting / preparing / redirected) |
| `dispatch_logged` | Dispatcher clicks approve | Confirmation message, incident record updated in DynamoDB |
| `report_generated` | Report Agent completes after-action report | Link to report appears in incident timeline |

**Lambda–WebSocket bridge:** Every Lambda that emits an event calls a shared utility (`backend/shared/utils/websocket.py`) that looks up the dispatcher's `connectionId` in DynamoDB and posts the message via API Gateway Management API. Connection state (connectionId → incident_id) stored in DynamoDB with a 2-hour TTL.

---

#### Progressive Rendering — The Dispatcher Never Waits

The dashboard never shows a full-page loading state. Each section renders independently the moment its data arrives. The dispatcher sees information appear and can act on it before the full card is complete:

| Time | What appears |
|---|---|
| T + 0.3s | First transcript words scrolling on screen |
| T + 2–4s | Agent status panel appears — cards show "Pending" |
| T + 6–8s | Navigation Agent returns → unit, ETA, route fills in. Map draws route polyline. For critical severity: **"Dispatch Unit Now" button activates** |
| T + 8–10s | Medical Agent returns → hospital name, ETA, ER status fills in |
| T + 10–12s | Hazmat Agent returns (if applicable) → hazard warnings and evacuation radius appear |
| T + 12–15s | Coordinator synthesizes → AI confidence + reasoning summary appear. **"Approve All" button activates** |

---

#### What the Dispatcher Sees — The Recommendation Card

- **Severity badge** — color-coded border: red (critical) / amber (urgent) / green (non-urgent)
- **Incident summary** — one sentence, auto-generated by Coordinator
- **Recommended unit** — unit type, ETA in minutes, "View Route" link (real Google Maps turn-by-turn)
- **Recommended hospital** — name, ETA, ER readiness status (from Mock Hospital API reply)
- **Hazard warnings** — shown only when Fire/Hazmat Agent returns data
- **Triage protocol** — one-line excerpt from Knowledge Base (medical incidents only)
- **AI confidence** — high / medium / low, with two-sentence reasoning summary
- **"Dispatch Unit Now"** button — partial approval for critical severity, appears as soon as Navigation returns
- **"Approve All"** button — full approval, activates when Coordinator card is complete
- **Override button** — opens reason dropdown (Wrong unit type / Better route known / Hospital preference / Protocol disagreement / Other)

**Design principle:** The dispatcher's cognitive load is already at maximum during an active incident. The dashboard surfaces one decision, not ten inputs. Information fills in independently — the dispatcher acts on what they see as it arrives. They never watch a loading spinner. RapidSOS and Prepared.ai give dispatchers better information. ARIA gives them a decision — and puts it on screen in under 15 seconds.

---

### Layer 9 — Outputs (Real-Time Logging + Mock Hospital Response)

When the dispatcher clicks approve, two things happen simultaneously:

#### Output A — Route Assignment Logged + Mock Hospital Alert
- **Responder Dispatch:** The turn-by-turn route (from real Google Maps API) and incident summary are **logged to DynamoDB** as a dispatch event. No actual mobile device receives a push — the system simply records `route_assigned`, `unit_id`, `eta`, `turn_by_turn_url` for audit and reporting purposes.
- **Mock Hospital:** The Medical Agent's pre-alert is sent to the **Mock Hospital API**, which replies after a short delay with readiness status (`accepting` / `preparing` / `redirected`). This reply is streamed back to the dashboard via WebSocket.

#### Output B — Incident Log & After-Action Report
- Full session written to DynamoDB (structured metadata)
- Complete transcript and agent reasoning chain stored in S3
- After-action report auto-generated by Report Agent with:
  - Full incident timeline
  - AI recommendations and dispatcher decisions
  - Real Google Maps route, ETAs, and traffic conditions
  - Mock hospital response (readiness status, any redirect notes)
  - Logged dispatch events (route assigned to unit, unit availability at time of dispatch)
- Data available for analytics, training, and compliance reporting

**No SNS notifications:** For the open-source demo, all outputs are handled through real-time logging and WebSocket updates. In production, SNS would push the route directly to a responder's mobile device and the pre-alert to a hospital's ER system.

---

## AWS Services Summary

| Service | Layer | Role |
|---|---|---|
| Amazon Transcribe | Layer 2 | Real-time streaming voice to text, word by word |
| AWS Lambda (`aria-stream-processor`) | Layer 3 | Per-word pipeline — domain watchers, async agent triggers, WebSocket broadcast |
| Amazon Bedrock (Claude Haiku 3.5) | Layer 3 | Parallel verifier — resolves ambiguities, enriches agent context mid-run |
| Amazon Bedrock (Claude Sonnet 4) | Layer 4 | Coordinator synthesis — reconciles agent results, progressive card updates |
| Amazon Bedrock Agents | Layer 5 | Four specialist agents triggered asynchronously by domain watchers |
| Amazon Bedrock Knowledge Base | Layer 6 | RAG over emergency protocol docs |
| Amazon Titan Embeddings v2 | Layer 6 | Vector embeddings for Knowledge Base |
| Amazon S3 | Layer 6 + 9 | Document storage + incident logs + after-action reports |
| Amazon Bedrock Guardrails | Layer 7 | Safety enforcement, no auto-execution, override logging |
| Amazon API Gateway (REST + WebSocket) | Layer 8 | REST endpoints + WebSocket spine for live dashboard updates |
| Vercel | Layer 8 | Frontend hosting, CDN-distributed |
| AWS Lambda | Multiple | Tool execution for agents + mock entity APIs |
| Amazon DynamoDB | Multiple | Unit availability, incident metadata, WebSocket connection state |
| Mock External Entities | Layer 5.5 | Simulated hospital, responder, and CAD APIs |

---

## Judging Criteria Alignment

| Criteria | How ARIA addresses it |
|---|---|
| Thoughtful model usage | Claude Haiku for speed at Layer 3, Claude Sonnet for reasoning at Layer 4 — right model for right task |
| Prompt engineering | Each of six agents has a precision-crafted domain-specific system prompt |
| Guardrails and safety | Bedrock Guardrails enforces human-in-the-loop at every action point |
| Knowledge Bases and Agents | Multi-agent orchestration is the core architecture, backed by a structured Bedrock Knowledge Base |
| Strong AI integration | Bedrock is not a wrapper — it is the reasoning engine for every decision in the pipeline |

---

## Build with Gratitude

> "911 dispatchers are the invisible first responders. They are never on the news. They never get the parade. But they are the voice that holds you together in the worst moment of your life — and they do it while juggling six screens, aging systems that crash 88% of the time, and a staffing crisis that leaves them working double shifts. We built ARIA for them. Not to replace them — to finally give them the backup they deserve."

---

*ARIA — Built for AWSHacks 2026 | Bedrock Track | Theme: Build with Gratitude*
