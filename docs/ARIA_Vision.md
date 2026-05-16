# ARIA — Vision, Problem Statement & Mission
### Why we built it, what it solves, and where it goes next

---

> "911 dispatchers are the invisible first responders. They are never on the news. They never get the parade. But they are the voice that holds you together in the worst moment of your life — and they do it alone, under pressure, with tools that were never built to help them think."

---

## The Mission

ARIA exists for one reason: to give 911 dispatchers the backup they have never had.

Not a better data screen. Not a smarter CAD system. A real-time thinking partner — one that listens alongside the dispatcher, processes everything simultaneously, handles backend coordination in the background, and surfaces a single clear recommendation so the human can stay focused on the one thing that matters: the person on the other end of the line.

ARIA is a co-pilot. The dispatcher is always the pilot.

---

## The Four Problems

---

### 1. One Person. Every Task. Simultaneously.

A 911 dispatcher receives a call. In the next 90 seconds, that one person must:

- Keep the caller calm and extract coherent information from someone who is panicking
- Identify the incident type, severity, and exact location — often from fragmented, contradictory speech
- Search unit availability across the CAD system
- Calculate which unit is closest, accounting for current traffic and active assignments
- Cross-reference hospital availability and specialty capabilities
- Determine if hazmat, fire, or additional backup resources are needed
- Type all of this into the CAD system in real time
- Begin coordinating dispatch — while still on the call

There is no second person helping them think. There is no system doing any of this in the background. Every one of these tasks lands on a single human, simultaneously, every call.

ARIA's response: these tasks do not all need a human. The information gathering, the unit lookup, the hospital query, the protocol retrieval — these are parallelizable. ARIA runs all of it the moment the call starts, so by the time the dispatcher needs to make a decision, the information is already there. The dispatcher's job becomes what it should always have been: judgment and approval, not research and data entry.

---

### 2. Human Error Is Not a Character Flaw. It Is a System Design Failure.

Dispatchers make mistakes. Not because they are unqualified — they are among the most trained, highest-pressure professionals in public safety. They make mistakes because the conditions they work in make errors structurally inevitable.

- **Fatigue:** Centers are running 25–35% below minimum safe staffing (NENA, 2025). Mandatory overtime is standard. Dispatchers regularly work back-to-back 12-hour shifts.
- **Cognitive overload:** Simultaneously managing multiple active calls, radio traffic, and CAD input leaves no cognitive reserve for catching a missed detail.
- **Decision pressure:** In a cardiac arrest, the dispatcher has minutes. There is no time to second-guess, no time to re-check, no margin for a hesitation.
- **Information gaps:** A caller who is panicking gives incomplete information. The dispatcher fills in the gaps from experience — and sometimes fills them in wrong.

Under these conditions, a wrong unit dispatched, a hospital sent the wrong patient condition, a hazmat responder arriving without the right equipment — these are not failures of the individual. They are failures of a system that asks one person to do too much, too fast, with no backup.

ARIA's response: bring a layer of verification and grounding to every decision. Every recommendation ARIA surfaces is grounded in authoritative source documents — FEMA ERG, AHA protocols, MPDS triage guidelines. The Haiku verifier cross-checks pattern matches against the full call context. The Coordinator catches conflicts between agent outputs before they reach the dispatcher. ARIA does not eliminate human judgment — it catches the errors that happen when that judgment is operating under impossible conditions.

---

### 3. Emergencies Evolve Faster Than Any System Can Batch

An emergency is not a static event. It is a moving situation.

What starts as a medical call becomes a crime scene when the dispatcher hears a gunshot in the background. What sounds like a minor car accident becomes a multi-vehicle pile-up with fuel spillage as the caller reaches the scene. What appears to be a residential fire reveals a chemical smell as the first responder radios back.

Every second, the situation changes. Every second, new information arrives that may change the recommended course of action entirely.

Current systems are built for a world where information arrives in discrete packets — a call is assessed, data is entered, dispatch is made. They are not built for a world where the picture is actively changing while the call is in progress.

At the same time, pure automation is not the answer. These situations require **human judgment** — the experienced dispatcher who recognizes that "I think he had a heart attack" from a panicked spouse might actually be a stroke, or that the "small fire" in an industrial district needs a hazmat unit regardless of what the caller thinks. Pattern recognition built from years of experience cannot be replaced.

ARIA's response: combine human-speed instinct with machine-speed execution. The Stream Processor reacts to every word the moment it is spoken — domain watchers fire agents in real time, the recommendation card updates as the situation evolves. But every action still requires a human to approve. The dispatcher brings the judgment; ARIA brings the speed. Neither works as well without the other.

---

### 4. Backend Coordination Is Invisible Work That Costs Lives

When a dispatcher is managing an active call, there is a second layer of work happening in parallel that rarely gets acknowledged: coordinating with external entities.

- Calling a hospital to check if the trauma bay is available and staffed
- Radioing for backup units when a police call escalates
- Contacting the fire department's hazmat team to confirm they have the right equipment for the chemical involved
- Reaching out to a second hospital when the first is at capacity
- Flagging a mutual aid request when local resources are exhausted

All of this is manual. All of it requires the dispatcher to split their attention — and every split is a moment they are not listening to the caller, not updating the CAD, not catching the detail that changes the outcome.

The information that comes back from these contacts is equally important. A hospital saying "redirected, no trauma bay" or a fire team saying "we need a second engine" — these replies change the recommendation. But they arrive asynchronously, while the dispatcher is still managing everything else. Replies get missed. Status updates come back too late.

ARIA's response: move backend coordination entirely off the dispatcher's plate. The Medical Agent sends the hospital pre-alert during the call and receives the readiness reply, surfacing it to the dashboard without the dispatcher having to make a single call. The Navigation Agent queries unit availability and calculates backup options in real time. The Coordinator tracks all of this and updates the recommendation card the moment a reply changes the picture. The dispatcher sees the result — "Trauma Bay 2 accepting, ETA 8 min" — not the process that produced it.

---

## Where We Go Next — Multi-Source Incident Intelligence

The four problems above describe a single dispatcher on a single call. But many of the most serious incidents are not single-call events.

A major car accident on a highway generates 15 simultaneous 911 calls. Each caller sees a different part of the scene. One caller is at the front of the pile-up and sees two vehicles. Another is behind and sees five. One caller can see a person trapped. Another can see fuel leaking. One caller heard an explosion. Another is focused on a child crying.

Each call contains real, critical information. No single call contains the full picture.

Today, each of those calls is handled independently by different dispatchers. There is no mechanism to synthesize them. Information from one call does not inform the response recommended in another. The dispatcher on call #7 does not know that call #3 already reported a fuel leak.

**The vision:** ARIA maintains a live knowledge graph for every active incident — a unified, continuously updated record that aggregates information from every call linked to the same location and event. When call #7 comes in for the same accident, the responding agent already knows about the fuel leak from call #3, the trapped passenger from call #9, and the eyewitness count from call #11. Every dispatcher working the incident is working from the same complete picture.

This is not a simple data aggregation problem. It requires:
- **Incident deduplication** — recognizing that 15 calls from a 0.2-mile radius within 3 minutes are likely the same event
- **Information fusion** — reconciling conflicting reports (one caller says 2 vehicles, another says 6) and identifying which details are confirmed vs unverified
- **Conflict resolution** — when information from different callers contradicts, surfacing both versions to the dispatcher with a confidence weight, not silently choosing one
- **Live graph updates** — as new calls arrive and field units radio back, the knowledge graph updates in real time and all active agents are aware of the new state

When this exists, ARIA stops being a per-call tool and becomes an incident-level intelligence system. The dispatcher is not just better equipped for the call they are on — they have access to the full ground truth of the event, assembled from every human who called for help.

---

## The People This Is For

ARIA is not built for the best case — the 10-year veteran dispatcher who has seen everything and can synthesize inputs in their sleep. ARIA is built for:

- The dispatcher working their third consecutive shift because the center is understaffed
- The dispatcher six months in who has the protocols memorized but not yet the instincts
- The dispatcher managing two active calls when the third line rings
- Every dispatcher, on every call — because the system should never depend on anyone having a perfect day

The best human dispatcher in the world is still a human — subject to fatigue, distraction, and the limits of what one person can process at once. ARIA does not replace their judgment. It removes the conditions that degrade it.

---

*ARIA — Built for AWSHacks 2026 | Bedrock Track | Theme: Build with Gratitude*
