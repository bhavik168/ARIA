"""
ARIA — per-layer architecture diagrams (LinkedIn-carousel friendly).

Generates one readable PNG per pipeline layer into ./aria_layers/.
Each image is focused on a single layer, with large fonts and light
"context" nodes (faded) showing what feeds in and what comes next, so
every slide stands alone.

The full single-image diagram (aria_architecture.png) is left untouched.

Run:  python aria_layers.py

Icon notes (same substitutions as aria_architecture.py):
  * APIGateway is in diagrams.aws.network (not integration) in this version.
  * MobileClient (capital C) in diagrams.aws.general.
  * No dedicated Bedrock KB / Titan / Guardrails icons exist — the generic
    Bedrock icon is reused and the service is named in the node label.
"""

from diagrams import Diagram, Cluster, Edge
from diagrams.aws.ml import Transcribe, Bedrock
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.storage import S3
from diagrams.aws.integration import SNS
from diagrams.aws.network import APIGateway
from diagrams.aws.security import Cognito
from diagrams.aws.general import User, MobileClient

OUTDIR = "aria_layers"

# Large fonts so text is legible when shrunk into a LinkedIn feed.
BASE_GRAPH = {
    "dpi": "200",
    "fontsize": "30",
    "fontname": "Helvetica-Bold",
    "labelloc": "t",
    "pad": "0.7",
    "nodesep": "0.7",
    "ranksep": "1.0",
    "splines": "spline",
    "bgcolor": "white",
}

CLUSTER = {
    "fontsize": "22",
    "fontname": "Helvetica-Bold",
    "style": "rounded",
    "pencolor": "#3b6ea5",
    "penwidth": "2.2",
    "margin": "20",
}

NODE = {"fontsize": "16", "fontname": "Helvetica"}

# Faded styling for "context" nodes (the layer before / after, for orientation).
CTX_NODE = {"fontsize": "14", "fontname": "Helvetica", "fontcolor": "#9aa4ad"}
CTX_CLUSTER = {**CLUSTER, "pencolor": "#c4ccd3", "fontcolor": "#9aa4ad", "penwidth": "1.4"}

FLOW = {"color": "#2d3e50", "penwidth": "2.2", "fontsize": "15", "fontname": "Helvetica"}
CTX_FLOW = {"color": "#b3bcc4", "penwidth": "1.6", "fontsize": "13", "fontname": "Helvetica", "fontcolor": "#9aa4ad"}
PARALLEL = {"color": "#1f8a4c", "penwidth": "2.0", "style": "bold", "fontsize": "14", "fontname": "Helvetica"}
FINDINGS = {"color": "#1f8a4c", "penwidth": "1.6", "style": "dashed", "fontsize": "14", "fontname": "Helvetica"}
RAG = {"color": "#8e44ad", "penwidth": "1.8", "style": "dashed", "fontsize": "14", "fontname": "Helvetica"}
SAFETY = {"color": "#c0392b", "penwidth": "2.4", "fontsize": "15", "fontname": "Helvetica-Bold"}
OUTPUT = {"color": "#d35400", "penwidth": "2.2", "fontsize": "15", "fontname": "Helvetica"}


def diagram(title, fname, direction="LR"):
    return Diagram(
        title,
        filename=f"{OUTDIR}/{fname}",
        show=False,
        direction=direction,
        graph_attr=BASE_GRAPH,
        node_attr=NODE,
    )


# ───────────────────────── Layer 1 — Input ─────────────────────────
with diagram("Layer 1 — Input: 911 Caller", "layer_1_input", direction="LR"):
    with Cluster("Layer 1 — Input", graph_attr=CLUSTER):
        caller = User("911 Caller\nvoice / text / video")
    with Cluster("Layer 2 (next)", graph_attr=CTX_CLUSTER):
        nxt = Transcribe("Amazon Transcribe")
    caller >> Edge(**FLOW, label="live audio stream") >> nxt


# ──────────────────── Layer 2 — Transcribe ─────────────────────────
with diagram("Layer 2 — Amazon Transcribe (Speech-to-Text)", "layer_2_transcribe", direction="LR"):
    with Cluster("Layer 1", graph_attr=CTX_CLUSTER):
        prev = User("911 Caller")
    with Cluster("Layer 2 — Speech-to-Text", graph_attr=CLUSTER):
        tr = Transcribe("Amazon Transcribe\n(Streaming)\nword-level, 185+ languages")
    with Cluster("Layer 3 (next)", graph_attr=CTX_CLUSTER):
        nxt = Lambda("aria-stream-processor")
    prev >> Edge(**CTX_FLOW, label="audio") >> tr
    tr >> Edge(**FLOW, label="live transcript (300ms)") >> nxt


# ──────────────────── Layer 3 — Dispatcher ─────────────────────────
with diagram("Layer 3 — Dispatcher Agent (fast entity extraction)", "layer_3_dispatcher", direction="LR"):
    with Cluster("Layer 2", graph_attr=CTX_CLUSTER):
        prev = Transcribe("Amazon Transcribe")
    with Cluster("Layer 3 — Dispatcher Agent", graph_attr=CLUSTER):
        sp = Lambda("aria-stream-processor\ndomain watchers")
        haiku = Bedrock("Amazon Bedrock\nClaude Haiku 3.5\nfast entity extraction")
        sp >> Edge(**FLOW, label="enrich") >> haiku
    with Cluster("Layer 4 (next)", graph_attr=CTX_CLUSTER):
        nxt = Bedrock("Coordinator\nClaude Sonnet 4")
    prev >> Edge(**CTX_FLOW, label="live transcript") >> sp
    haiku >> Edge(**FLOW, label="entities + severity") >> nxt


# ──────────────────── Layer 4 — Coordinator ────────────────────────
with diagram("Layer 4 — Coordinator Agent · The Brain (Claude Sonnet 4)", "layer_4_coordinator", direction="LR"):
    with Cluster("Layer 3", graph_attr=CTX_CLUSTER):
        prev = Bedrock("Dispatcher\nClaude Haiku 3.5")
    with Cluster("Layer 4 — Coordinator · The Brain", graph_attr=CLUSTER):
        coord = Bedrock("Amazon Bedrock\nClaude Sonnet 4\nmulti-agent orchestration")
    with Cluster("Layer 5 (next)", graph_attr=CTX_CLUSTER):
        nxt = Bedrock("4 Specialist Agents\n(parallel)")
    prev >> Edge(**CTX_FLOW, label="entities") >> coord
    coord >> Edge(**PARALLEL, label="spawn in parallel") >> nxt
    nxt >> Edge(**FINDINGS, label="findings") >> coord


# ─────────────── Layer 5 — Specialist Agents (parallel) ────────────
with diagram("Layer 5 — Specialist Agents (parallel)", "layer_5_specialists", direction="TB"):
    coord = Bedrock("Layer 4 — Coordinator\nClaude Sonnet 4")
    with Cluster("Layer 5 — Specialist Agents (run in parallel)", graph_attr=CLUSTER):

        with Cluster("Navigation Agent", graph_attr=CLUSTER):
            nav = Bedrock("Bedrock Agent")
            nav_l = Lambda("aria-navigation-tool\nMaps / ETA")
            nav_db = Dynamodb("aria-units")
            nav_sns = SNS("SNS push")
            nav >> Edge(**FLOW) >> nav_l
            nav >> Edge(**FLOW) >> nav_db
            nav >> Edge(**FLOW) >> nav_sns

        with Cluster("Medical Agent", graph_attr=CLUSTER):
            med = Bedrock("Bedrock Agent")
            med_kb = Bedrock("Knowledge Base\nmedical protocols")
            med_l = Lambda("aria-medical-tool\nhospital capacity")
            med >> Edge(**RAG) >> med_kb
            med >> Edge(**FLOW) >> med_l

        with Cluster("Fire / Hazmat Agent", graph_attr=CLUSTER):
            fire = Bedrock("Bedrock Agent")
            fire_kb = Bedrock("Knowledge Base\nFEMA hazmat")
            fire_l = Lambda("aria-hazmat-tool\nevac radius")
            fire >> Edge(**RAG) >> fire_kb
            fire >> Edge(**FLOW) >> fire_l

        with Cluster("Report Agent", graph_attr=CLUSTER):
            rep = Bedrock("Bedrock Agent")
            rep_db = Dynamodb("aria-incidents")
            rep_s3 = S3("aria-reports")
            rep >> Edge(**FLOW) >> rep_db
            rep >> Edge(**FLOW) >> rep_s3

    for a in (nav, med, fire, rep):
        coord >> Edge(**PARALLEL, label="spawn") >> a
        a >> Edge(**FINDINGS, label="findings") >> coord


# ──────────────────── Layer 6 — Knowledge Base ─────────────────────
with diagram("Layer 6 — Bedrock Knowledge Base (RAG)", "layer_6_knowledge_base", direction="LR"):
    with Cluster("Specialist Agents", graph_attr=CTX_CLUSTER):
        med = Bedrock("Medical Agent")
        fire = Bedrock("Fire / Hazmat Agent")
    with Cluster("Layer 6 — Bedrock Knowledge Base (RAG)", graph_attr=CLUSTER):
        kb = Bedrock("Bedrock Knowledge Base\nsemantic retrieval")
        titan = Bedrock("Amazon Titan\nEmbeddings v2")
        s3 = S3("S3 aria-knowledge-base\nprotocols / FEMA / SOPs")
        kb >> Edge(**RAG, label="embed query") >> titan
        kb >> Edge(**RAG, label="vector search") >> s3
    med >> Edge(**RAG, label="query KB") >> kb
    fire >> Edge(**RAG, label="query KB") >> kb
    kb >> Edge(**FLOW, label="grounded context") >> med


# ──────────────────── Layer 7 — Guardrails ─────────────────────────
with diagram("Layer 7 — Bedrock Guardrails (human-in-the-loop)", "layer_7_guardrails", direction="LR"):
    with Cluster("Layer 4", graph_attr=CTX_CLUSTER):
        coord = Bedrock("Coordinator\nClaude Sonnet 4")
    with Cluster("Layer 7 — Bedrock Guardrails (safety)", graph_attr=CLUSTER):
        gr = Bedrock("Bedrock Guardrails\nno auto-execution\noverride logging")
    with Cluster("Layer 8 (next)", graph_attr=CTX_CLUSTER):
        nxt = APIGateway("Dispatcher Dashboard")
    coord >> Edge(**SAFETY, label="recommendation") >> gr
    gr >> Edge(**SAFETY, label="human approval required") >> nxt


# ──────────────────── Layer 8 — Dashboard ──────────────────────────
with diagram("Layer 8 — Dispatcher Dashboard", "layer_8_dashboard", direction="LR"):
    with Cluster("Layer 7", graph_attr=CTX_CLUSTER):
        prev = Bedrock("Bedrock Guardrails")
    with Cluster("Layer 8 — Dispatcher Dashboard", graph_attr=CLUSTER):
        cog = Cognito("Cognito\nauth")
        api = APIGateway("API Gateway\nREST + WebSocket")
        ui = MobileClient("React Dashboard\ndispatcher UI")
        cog >> Edge(**FLOW, style="dashed", label="authn") >> api
        api >> Edge(**FLOW, label="live updates") >> ui
    with Cluster("Layer 9 (next)", graph_attr=CTX_CLUSTER):
        nxt = SNS("Outputs")
    prev >> Edge(**CTX_FLOW, label="approval required") >> api
    ui >> Edge(**OUTPUT, label="approve") >> nxt


# ──────────────────── Layer 9 — Outputs ────────────────────────────
with diagram("Layer 9 — Outputs (on dispatcher approval)", "layer_9_outputs", direction="TB"):
    ui = MobileClient("Layer 8 — Dispatcher\nclicks Approve")
    with Cluster("Layer 9 — Outputs (fire simultaneously)", graph_attr=CLUSTER):
        with Cluster("Output A — Responder push", graph_attr=CLUSTER):
            a_sns = SNS("SNS")
            a_dev = MobileClient("Responder\nmobile device")
            a_sns >> Edge(**OUTPUT) >> a_dev
        with Cluster("Output B — Hospital pre-alert", graph_attr=CLUSTER):
            b_sns = SNS("SNS")
            b_hosp = APIGateway("ER webhook")
            b_sns >> Edge(**OUTPUT) >> b_hosp
        with Cluster("Output C — Incident log", graph_attr=CLUSTER):
            c_db = Dynamodb("DynamoDB\nincident metadata")
            c_s3 = S3("S3\ntranscript / report")
            c_db >> Edge(**OUTPUT, style="dashed") >> c_s3
    ui >> Edge(**OUTPUT, label="approve") >> a_sns
    ui >> Edge(**OUTPUT, label="approve") >> b_sns
    ui >> Edge(**OUTPUT, label="approve") >> c_db


print("Generated per-layer images in ./aria_layers/")
