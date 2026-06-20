"""
ARIA — Autonomous Response Intelligence Assistant
Full AWS architecture diagram (9-layer pipeline) rendered with the
`diagrams` library (https://diagrams.mingrammer.com), using official AWS icons.

Run:  python aria_architecture.py   ->   produces aria_architecture.png

Icon notes / substitutions (verified against the installed diagrams version):
  * APIGateway lives in diagrams.aws.network (NOT diagrams.aws.integration in
    this version). Imported from network.
  * Mobileclient is spelled `MobileClient` (capital C) in diagrams.aws.general.
  * There is no dedicated Bedrock Knowledge Base, Titan Embeddings, or Bedrock
    Guardrails icon in this version of `diagrams`. The generic `Bedrock` icon is
    reused for all Bedrock-family services (Coordinator, specialists, KB,
    Guardrails) and the specific service is named in the node label.
  * Titan Embeddings v2 is represented with the `Bedrock` icon, labeled.
"""

from diagrams import Diagram, Cluster, Edge

# --- ML / AI ---
# Bedrock + Transcribe both exist in diagrams.aws.ml in this version.
from diagrams.aws.ml import Transcribe, Bedrock
# --- Compute ---
from diagrams.aws.compute import Lambda
# --- Database ---
from diagrams.aws.database import Dynamodb
# --- Storage ---
from diagrams.aws.storage import S3
# --- Integration ---
from diagrams.aws.integration import SNS
# --- Network (APIGateway is here, not in integration) ---
from diagrams.aws.network import APIGateway
# --- Security ---
from diagrams.aws.security import Cognito
# --- General (User + MobileClient) ---
from diagrams.aws.general import User, MobileClient


graph_attr = {
    "dpi": "200",
    "fontsize": "26",
    "fontname": "Helvetica-Bold",
    "labelloc": "t",
    "pad": "0.6",
    "nodesep": "0.55",
    "ranksep": "0.85",
    "splines": "spline",
    "bgcolor": "white",
}

cluster_attr = {
    "fontsize": "16",
    "fontname": "Helvetica-Bold",
    "style": "rounded",
    "pencolor": "#3b6ea5",
    "penwidth": "1.6",
    "margin": "16",
}

node_attr = {
    "fontsize": "12",
    "fontname": "Helvetica",
}

# Edge styles
FLOW = {"color": "#2d3e50", "penwidth": "1.8", "fontsize": "11", "fontname": "Helvetica"}
PARALLEL = {"color": "#1f8a4c", "penwidth": "1.6", "style": "bold", "fontsize": "11", "fontname": "Helvetica"}
FINDINGS = {"color": "#1f8a4c", "penwidth": "1.4", "style": "dashed", "fontsize": "11", "fontname": "Helvetica"}
RAG = {"color": "#8e44ad", "penwidth": "1.4", "style": "dashed", "fontsize": "10", "fontname": "Helvetica"}
SAFETY = {"color": "#c0392b", "penwidth": "2.0", "fontsize": "11", "fontname": "Helvetica-Bold"}
OUTPUT = {"color": "#d35400", "penwidth": "1.8", "fontsize": "11", "fontname": "Helvetica"}


with Diagram(
    "ARIA — Autonomous Response Intelligence Assistant",
    filename="aria_architecture",
    show=False,
    direction="TB",
    graph_attr=graph_attr,
    node_attr=node_attr,
):

    # ----- Layer 1 — Input -----
    with Cluster("Layer 1 — Input: 911 Caller (voice / text / video)", graph_attr=cluster_attr):
        caller = User("911 Caller\n(live audio stream)")

    # ----- Layer 2 — Transcribe -----
    with Cluster("Layer 2 — Speech-to-Text", graph_attr=cluster_attr):
        transcribe = Transcribe("Amazon Transcribe\n(Streaming, word-level)")

    # ----- Layer 3 — Dispatcher / Stream Processor -----
    with Cluster("Layer 3 — Dispatcher Agent (fast entity extraction)", graph_attr=cluster_attr):
        stream_proc = Lambda("aria-stream-processor\n(domain watchers)")
        dispatcher = Bedrock("Amazon Bedrock\nClaude Haiku 3.5\n(verify + extract)")

    # ----- Layer 4 — Coordinator (The Brain) -----
    with Cluster("Layer 4 — Coordinator Agent · The Brain (Claude Sonnet 4)", graph_attr=cluster_attr):
        coordinator = Bedrock("Amazon Bedrock\nClaude Sonnet 4\n(multi-agent orchestration)")

    # ----- Layer 6 — Knowledge Base (declared before L5 so specialists can query it) -----
    with Cluster("Layer 6 — Bedrock Knowledge Base (RAG)", graph_attr=cluster_attr):
        kb = Bedrock("Bedrock Knowledge Base\n(RAG retrieval)")
        kb_s3 = S3("S3 aria-knowledge-base\n(protocols / FEMA / SOPs)")
        titan = Bedrock("Amazon Titan\nEmbeddings v2")
        kb >> Edge(**RAG, label="embed") >> titan
        kb >> Edge(**RAG, label="vector search") >> kb_s3

    # ----- Layer 5 — Four Specialist Agents in parallel -----
    with Cluster("Layer 5 — Specialist Agents (parallel)", graph_attr=cluster_attr):

        with Cluster("Navigation Agent", graph_attr=cluster_attr):
            nav_agent = Bedrock("Bedrock Agent\nNavigation")
            nav_lambda = Lambda("aria-navigation-tool\n(Maps / ETA)")
            nav_db = Dynamodb("aria-units\n(unit availability)")
            nav_sns = SNS("SNS\n(responder push)")
            nav_agent >> Edge(**FLOW) >> nav_lambda
            nav_agent >> Edge(**FLOW) >> nav_db
            nav_agent >> Edge(**FLOW) >> nav_sns

        with Cluster("Medical Agent", graph_attr=cluster_attr):
            med_agent = Bedrock("Bedrock Agent\nMedical")
            med_lambda = Lambda("aria-medical-tool\n(hospital capacity API)")
            med_agent >> Edge(**FLOW) >> med_lambda

        with Cluster("Fire / Hazmat Agent", graph_attr=cluster_attr):
            fire_agent = Bedrock("Bedrock Agent\nFire / Hazmat")
            fire_lambda = Lambda("aria-hazmat-tool\n(FEMA / evac radius)")
            fire_agent >> Edge(**FLOW) >> fire_lambda

        with Cluster("Report Agent", graph_attr=cluster_attr):
            report_agent = Bedrock("Bedrock Agent\nReport")
            report_db = Dynamodb("aria-incidents\n(metadata)")
            report_s3 = S3("S3 aria-reports\n(after-action)")
            report_agent >> Edge(**FLOW) >> report_db
            report_agent >> Edge(**FLOW) >> report_s3

    # ----- Layer 7 — Guardrails (between Coordinator recommendation and dashboard) -----
    with Cluster("Layer 7 — Bedrock Guardrails (human-in-the-loop safety)", graph_attr=cluster_attr):
        guardrails = Bedrock("Bedrock Guardrails\n(no auto-execution)")

    # ----- Layer 8 — Dispatcher Dashboard -----
    with Cluster("Layer 8 — Dispatcher Dashboard", graph_attr=cluster_attr):
        cognito = Cognito("Cognito\n(auth)")
        apigw = APIGateway("API Gateway\n(REST + WebSocket)")
        dashboard = MobileClient("React Dashboard\n(dispatcher UI)")
        apigw >> Edge(**FLOW) >> dashboard
        cognito >> Edge(**FLOW, style="dashed", label="authn") >> apigw

    # ----- Layer 9 — Outputs (fire simultaneously on approval) -----
    with Cluster("Layer 9 — Outputs (on dispatcher approval)", graph_attr=cluster_attr):
        with Cluster("Output A — Responder push", graph_attr=cluster_attr):
            out_sns_resp = SNS("SNS")
            out_mobile = MobileClient("Responder\nmobile device")
            out_sns_resp >> Edge(**OUTPUT) >> out_mobile
        with Cluster("Output B — Hospital pre-alert", graph_attr=cluster_attr):
            out_sns_hosp = SNS("SNS")
            out_hosp = APIGateway("ER webhook\n(hospital)")
            out_sns_hosp >> Edge(**OUTPUT) >> out_hosp
        with Cluster("Output C — Incident log", graph_attr=cluster_attr):
            out_db = Dynamodb("DynamoDB\n(incident metadata)")
            out_s3 = S3("S3\n(transcript / report)")

    # ============ Wiring the pipeline top-to-bottom ============

    # L1 -> L2 -> L3
    caller >> Edge(**FLOW, label="voice / text / video") >> transcribe
    transcribe >> Edge(**FLOW, label="live transcript") >> stream_proc
    stream_proc >> Edge(**FLOW, label="enrich") >> dispatcher

    # L3 -> L4
    dispatcher >> Edge(**FLOW, label="entities + severity") >> coordinator

    # L4 -> specialists (spawn in parallel)
    for sa in (nav_agent, med_agent, fire_agent, report_agent):
        coordinator >> Edge(**PARALLEL, label="spawn in parallel") >> sa

    # specialists -> coordinator (findings rejoin)
    for sa in (nav_agent, med_agent, fire_agent, report_agent):
        sa >> Edge(**FINDINGS, label="findings") >> coordinator

    # specialists query the Knowledge Base (RAG)
    med_agent >> Edge(**RAG, label="query KB") >> kb
    fire_agent >> Edge(**RAG, label="query KB") >> kb

    # L4 recommendation -> L7 Guardrails -> L8 Dashboard
    coordinator >> Edge(**SAFETY, label="recommendation") >> guardrails
    guardrails >> Edge(**SAFETY, label="human approval required") >> apigw

    # L8 approval -> L9 outputs (fire simultaneously)
    dashboard >> Edge(**OUTPUT, label="approve") >> out_sns_resp
    dashboard >> Edge(**OUTPUT, label="approve") >> out_sns_hosp
    dashboard >> Edge(**OUTPUT, label="approve") >> out_db
    out_db >> Edge(**OUTPUT, style="dashed") >> out_s3

    print("Icons used: Transcribe, Bedrock (ml); Lambda (compute); Dynamodb (database); "
          "S3 (storage); SNS (integration); APIGateway (network); Cognito (security); "
          "User, MobileClient (general). Bedrock icon reused for KB / Titan / Guardrails / agents.")
