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

### Layer 3 — Dispatcher Agent

**AWS Service:** Amazon Bedrock — Claude Haiku (fast, low-latency model)

**What it does:** The Dispatcher Agent reads the live transcript from Transcribe and extracts structured, actionable data:

- Caller location (address, GPS coordinates, landmark)
- Incident type (medical, fire, crime, accident, hazmat)
- Severity level (critical, urgent, non-urgent)
- Number of victims
- Any hazards mentioned (smoke, weapons, chemicals, flooding)

This structured data packet is then passed to the Coordinator Agent for orchestration.

**Why Claude Haiku:** Speed is the priority at this layer. Haiku is Anthropic's fastest, most cost-efficient model — ideal for high-frequency, real-time extraction tasks where latency directly impacts lives. Deep reasoning is not needed here; fast, accurate entity extraction is.

**Why it matters:** Dispatchers currently piece together incident details from a panicked caller while manually filling CAD system fields. The Dispatcher Agent does this automatically in under two seconds, with no dispatcher action required.

---

### Layer 4 — Coordinator Agent (The Brain)

**AWS Service:** Amazon Bedrock — Claude Sonnet (Bedrock multi-agent orchestration)

**What it does:** The Coordinator Agent is the central intelligence of ARIA. It receives the structured incident data from the Dispatcher Agent and does three things:

1. **Plans the investigation** — decides which specialist agents are needed based on incident type
2. **Spawns agents in parallel** — launches Navigation, Medical, Fire/Hazmat, and Report agents simultaneously, not sequentially
3. **Synthesizes results** — when all agents return their findings, the Coordinator reconciles conflicts, prioritizes by severity, and produces one clean recommendation card for the dispatcher

**Why Claude Sonnet:** The Coordinator needs deep multi-step reasoning — balancing competing priorities (two incidents needing the same unit), synthesizing inputs from four different domains, and generating a coherent, human-readable recommendation. Sonnet is used here for its superior reasoning capability.

**Why it matters:** Without ARIA, a dispatcher manually reads inputs from CAD, radio, hospital systems, and mapping software — then makes a decision under pressure. The Coordinator collapses all of that into a single surface. The dispatcher reviews, not researches.

**Bedrock feature used:** Multi-agent orchestration — this is the core Bedrock capability that enables one agent to spawn, manage, and synthesize outputs from multiple sub-agents autonomously.

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

**Technology:** React frontend, API Gateway, WebSocket for live updates, Vercel for hosting

**What it does:** The dispatcher sees a single, clean recommendation card — not four separate agent outputs, not a wall of data. The card contains:

- Incident type and severity (color coded: red / amber / green)
- Recommended units with ETAs and routes
- Recommended hospital with ER status
- Hazard warnings if applicable
- AI confidence level and reasoning summary
- One-click approve button
- One-click override with reason selection

**Design principle:** The dispatcher's cognitive load is already at maximum during an active incident. The dashboard surfaces one decision, not ten inputs. Everything ARIA gathered, reasoned over, and synthesized appears as a single actionable surface.

**Why it matters:** RapidSOS and Prepared.ai give dispatchers better information. ARIA gives them a decision. That is the fundamental difference.

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
| Amazon Transcribe | Layer 2 | Real-time voice to text |
| Amazon Bedrock (Claude Haiku) | Layer 3 | Fast entity extraction |
| Amazon Bedrock (Claude Sonnet) | Layer 4 | Multi-agent orchestration + reasoning |
| Amazon Bedrock Agents | Layer 5 | Four specialist agents |
| Amazon Bedrock Knowledge Base | Layer 6 | RAG over emergency protocol docs |
| Amazon Titan Embeddings | Layer 6 | Vector embeddings for Knowledge Base |
| Amazon S3 | Layer 6 + 9 | Document storage + incident logs |
| Amazon Bedrock Guardrails | Layer 7 | Safety enforcement, no auto-execution |
| Amazon API Gateway | Layer 8 | REST + WebSocket for dashboard |
| Vercel | Layer 8 | Frontend hosting + edge deployment |
| AWS Lambda | Multiple | Tool execution for agents + mock entity APIs |
| Amazon DynamoDB | Multiple | Unit availability + incident metadata |
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
