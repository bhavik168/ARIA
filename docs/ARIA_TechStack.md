# ARIA — Tech Stack Documentation
### Full Technology Breakdown by Layer

---

## Overview

ARIA is built entirely on AWS-native services, with Amazon Bedrock as the core reasoning engine. Every layer of the stack is chosen for a specific reason — speed, accuracy, safety, or scalability. This document breaks down every technology used, why it was chosen, and how it connects to the rest of the system.

---

## Core AI Layer — Amazon Bedrock

Bedrock is not a wrapper around an LLM. It is the reasoning engine for every decision ARIA makes. All agent logic, knowledge retrieval, guardrails enforcement, and response generation runs through Bedrock.

### Models Used

| Model | Layer | Why This Model |
|---|---|---|
| Claude Haiku 3.5 | Dispatcher Agent (Layer 3) | Fastest Anthropic model — sub-second latency for real-time transcript parsing and entity extraction. Cost-efficient for high-frequency calls. |
| Claude Sonnet 4 | Coordinator Agent (Layer 4) | Superior multi-step reasoning. Handles conflict resolution, priority balancing, and synthesizing four agent outputs into one recommendation. |
| Claude Sonnet 4 | Specialist Agents (Layer 5) | Medical, Fire/Hazmat, and Navigation agents need domain-specific reasoning grounded in Knowledge Base retrieval. Sonnet handles nuanced protocol interpretation. |
| Amazon Titan Embeddings v2 | Knowledge Base (Layer 6) | Converts documents and queries into vectors for semantic similarity search. Native Bedrock integration with no external embedding service required. |

### Bedrock Features Used

| Feature | Purpose |
|---|---|
| Bedrock Agents | Each of the six ARIA agents is a standalone Bedrock Agent with its own system prompt, tool bindings, and KB access |
| Multi-Agent Orchestration | The Coordinator Agent spawns and manages the four specialist agents in parallel using Bedrock's native orchestration layer |
| Bedrock Knowledge Base | RAG pipeline over emergency protocol documents — medical, hazmat, hospital, and SOP data |
| Bedrock Guardrails | Hard safety enforcement — blocks hallucinated medical/chemical data, enforces human-in-the-loop, logs all overrides |
| Prompt Caching | Frequently used system prompts (medical protocols, hazmat guidelines) cached to reduce latency and token cost on repeat calls |

---

## Speech Processing Layer

### Amazon Transcribe Streaming

| Property | Detail |
|---|---|
| Mode | Streaming (from pre-recorded audio file) |
| Latency | Word-level output within 300ms of speech |
| Language support | 185+ languages and dialects |
| Integration | Audio file streamed to Transcribe, transcript fed live to Dispatcher Agent via Lambda |
| Demo note | Pre-recorded 911 call audio is streamed to simulate a live call — validating real-world speech-to-intelligence performance |

---

## Compute Layer — AWS Lambda

All agent tool execution, API calls, and data transformations run through Lambda functions. No servers to manage, no idle compute cost.

### Lambda Functions Breakdown

| Function Name | Trigger | What It Does |
|---|---|---|
| `aria-ingest` | API Gateway (REST) | Receives incoming 911 audio session, initializes DynamoDB incident record, starts Transcribe stream |
| `aria-dispatcher` | Transcribe stream event | Passes live transcript to Dispatcher Agent, returns structured incident data |
| `aria-coordinator` | Dispatcher output | Invokes Coordinator Agent, manages parallel specialist agent spawning |
| `aria-navigation-tool` | Navigation Agent tool call | Calls **Google Maps API** for live traffic ETAs and turn-by-turn routes. Queries unit locations from DynamoDB. Logs dispatch event on approval (no real device push in demo). |
| `aria-medical-tool` | Medical Agent tool call | Queries Knowledge Base for triage, sends pre-alert to Mock Hospital API |
| `aria-hazmat-tool` | Fire/Hazmat Agent tool call | Queries Knowledge Base for chemical data, returns evacuation radius and gear recommendations |
| `aria-mock-hospital` | Medical Agent pre-alert | Simulated hospital endpoint — receives pre-alert JSON, replies with readiness status after 1–3s delay |
| `aria-report` | Incident close event | Triggers Report Agent to generate full after-action report, writes to S3 |

**Runtime:** Python 3.12
**Memory:** 512MB standard, 1024MB for coordinator and report functions
**Timeout:** 30 seconds standard, 5 minutes for report generation

---

## Storage Layer

### Amazon DynamoDB

| Table | Partition Key | Sort Key | Contents |
|---|---|---|---|
| `aria-incidents` | `incident_id` | `timestamp` | Live incident record — status, agent outputs, dispatcher decisions, timeline |
| `aria-units` | `unit_id` | `status` | Real-time emergency unit availability, location, current assignment |
| `aria-hospitals` | `hospital_id` | `region` | Hospital ER capacity, specialty capabilities, pre-alert status |
| `aria-overrides` | `incident_id` | `timestamp` | Dispatcher override log — what ARIA recommended vs what dispatcher chose |

**Why DynamoDB:** Single-digit millisecond reads under any load. During a mass casualty event with 100+ simultaneous incidents, DynamoDB scales automatically with zero configuration. No connection pooling, no query planning — just fast key-value access at emergency scale.

### Amazon S3

| Bucket | Contents | Lifecycle |
|---|---|---|
| `aria-knowledge-base` | Medical protocols, FEMA hazmat docs, hospital registry, emergency SOPs | Versioned, replicated — source of truth for all RAG retrieval |
| `aria-transcripts` | Full call transcripts, timestamped word by word | 7-year retention (legal compliance) |
| `aria-reports` | Auto-generated after-action reports (PDF + JSON) | 7-year retention, indexed in DynamoDB |
| `aria-agent-logs` | Full agent reasoning chains for every incident | 2-year retention, used for model evaluation and audit |

---

## Mock External Entity Layer

### Simulated Hospital and CAD APIs

For the open-source demo, ARIA interfaces with a lightweight mock hospital service that behaves exactly like a real hospital's ER intake system — receiving pre-alerts and replying back with readiness status. The responder-side dispatch is logged, not pushed to a real device.

| Mock Service | Technology | Receives | Replies With |
|---|---|---|---|
| **Mock Hospital API** | AWS Lambda + API Gateway | Pre-alert JSON (patient condition, ETA, required resources) | `{hospital_id, status: "accepting" \| "preparing" \| "redirect", eta_accepted: true, notes: "Trauma bay ready"}` after 1–3s delay |
| **Mock CAD Database** | DynamoDB + Lambda | Unit availability query | Real-time unit status, location, and current assignment |

**Responder dispatch (logged only):** The Navigation Agent generates a real turn-by-turn route via Google Maps API. On dispatcher approval, the system logs the dispatch event to DynamoDB (`route_assigned`, `unit_id`, `eta`, `turn_by_turn_url`). No actual mobile device receives a push — this proves the event was captured for audit and reporting without requiring a real responder fleet API.

**Why mocks:** Real hospital ER systems are not publicly accessible. The mock hospital proves the closed-loop medical dispatch architecture while remaining lightweight and interchangeable with a real HL7/FHIR endpoint in production.

---

## API and Frontend Layer

### Amazon API Gateway

| Endpoint | Method | Purpose |
|---|---|---|
| `/session/start` | POST | Initialize new 911 incident session |
| `/session/{id}/approve` | POST | Dispatcher approves ARIA recommendation |
| `/session/{id}/override` | POST | Dispatcher overrides with custom decision |
| `/session/{id}/status` | GET | Poll current agent status and outputs |
| `/ws/dashboard` | WebSocket | Live dashboard updates via persistent connection |

### React Frontend (Dispatcher Dashboard)

| Component | Technology | Purpose |
|---|---|---|
| Recommendation card | React + Tailwind | Surfaces single synthesized recommendation with severity color coding |
| Live transcript feed | WebSocket + React state | Shows caller transcript updating in real time |
| Map component | Mapbox GL JS | Displays unit locations, incident location, recommended route |
| Agent status panel | React | Shows which agents are running, complete, or pending |
| Approve / Override buttons | React + API Gateway | One-click dispatcher action with override reason dropdown |
| Incident timeline | React | Chronological log of all events in the current incident |

**Hosting:** Vercel (static React build, CDN-distributed, edge-deployed)
**Auth:** None — open-source demo, no login required

---

## Knowledge Base — Documents and Data Sources

### Source Documents (loaded into S3, indexed by Bedrock)

| Document | Source | Used By |
|---|---|---|
| Medical Priority Dispatch System (MPDS) protocols | IAED (public) | Medical Agent |
| AHA cardiac emergency guidelines | American Heart Association (public) | Medical Agent |
| Trauma triage criteria | ATLS guidelines (public) | Medical Agent |
| FEMA Emergency Response Guidebook | FEMA (public, free download) | Fire/Hazmat Agent |
| NIOSH hazmat pocket guide | CDC/NIOSH (public) | Fire/Hazmat Agent |
| Chemical property database | PubChem API (public) | Fire/Hazmat Agent |
| Standard operating procedures | Custom — seeded for demo | Coordinator Agent |
| Historical incident patterns | Synthetic demo data | All agents |

### Embedding and Retrieval

| Step | Service | Detail |
|---|---|---|
| Chunking | Bedrock Knowledge Base (auto) | Documents split into 512-token chunks with 10% overlap |
| Embedding | Amazon Titan Embeddings v2 | 1536-dimension vectors per chunk |
| Vector store | Bedrock-managed (OpenSearch Serverless) | Fully managed, no infrastructure to run |
| Retrieval | Semantic similarity search | Top-5 most relevant chunks returned per agent query |
| Grounding | Claude reasoning over retrieved context | All recommendations cite source document and chunk |

---

## Safety and Compliance Layer

### Amazon Bedrock Guardrails Configuration

| Guardrail Rule | What It Blocks | Why |
|---|---|---|
| No auto-execution policy | Any agent action that would dispatch a unit or alert a hospital without human approval | AI must never autonomously act in a life-or-death context |
| Medical dosage filter | Any output containing specific drug dosages or treatment prescriptions | ARIA is not a medical provider — all clinical decisions stay with trained personnel |
| PII blocking | Caller phone numbers, names, addresses surfaced outside the secure dashboard | HIPAA and 911 data privacy compliance |
| Hallucination filter | Chemical hazard data, evacuation radii, hospital capacity figures not grounded in KB | Ungrounded outputs in emergency contexts are dangerous |
| Profanity and distress filter | Caller distress signals escalated to human review immediately | Ensures no automated response to a suicidal or hostage call |

---

## Infrastructure as Code

| Tool | Purpose |
|---|---|
| AWS CDK (Python) | Defines all Lambda functions, DynamoDB tables, S3 buckets, API Gateway routes, and mock entity endpoints as code |
| AWS SAM | Local testing of Lambda functions before deployment |
| GitHub Actions | CI/CD pipeline — push to main triggers CDK deploy to AWS |
| Vercel | Auto-deploys React frontend on every push to main |

---

## Cost Profile (Estimated per 1,000 incidents)

| Service | Estimated Cost |
|---|---|
| Amazon Transcribe Streaming | ~$2.40 (avg 2 min per call at $0.024/min) |
| Bedrock Claude Haiku (Dispatcher Agent) | ~$0.80 (avg 2K tokens per call) |
| Bedrock Claude Sonnet (Coordinator + Specialists) | ~$6.00 (avg 8K tokens across 5 Sonnet calls) |
| Bedrock Knowledge Base retrieval | ~$0.50 (5 retrievals per incident) |
| Lambda invocations | ~$0.03 (10 functions per incident, including mocks) |
| DynamoDB reads/writes | ~$0.10 |
| S3 storage | ~$0.05 |
| **Total per 1,000 incidents** | **~$9.88** |

> Cost per incident: approximately $0.01. One life saved is worth infinitely more.

---

## Security Architecture

| Concern | Solution |
|---|---|
| Encryption at rest | S3 SSE-KMS, DynamoDB encryption enabled |
| Encryption in transit | TLS 1.3 on all API Gateway and WebSocket connections |
| IAM least privilege | Each Lambda function has its own IAM role with only the permissions it needs |
| VPC isolation | All Lambda functions run inside a private VPC — no public internet access to backend |
| Audit trail | CloudTrail logs every API call, every agent action, every dispatcher decision |

---

*ARIA — Built for AWSHacks 2026 | Bedrock Track | Theme: Build with Gratitude*
