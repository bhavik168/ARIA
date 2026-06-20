"""
ARIA — grouped architecture diagram (croppable into 3 blocks).

Same nodes / icons / edges / styling as aria_architecture.py, but the 9 layers
are reorganized into THREE stacked macro-blocks with clear white gaps between
them so the single PNG can be cropped into 3 readable images:

  Block 1 — Transcribe : Layer 1 (Input, clearly marked) + Layer 2 (Transcribe)
  Block 2 — Amazon Bedrock : Layers 3-7 (Dispatcher, Coordinator, Specialist
            Agents, Knowledge Base, Guardrails) — the large Bedrock component
  Block 3 — Output : Layer 8 (Dashboard) + Layer 9 (Outputs A/B/C)

Nothing is added, updated, or removed from the content — only organized.
Does NOT touch aria_architecture.py.

Run:  python aria_architecture_grouped.py   ->   aria_architecture_grouped.png

Icon notes / substitutions (identical to the main script):
  * APIGateway lives in diagrams.aws.network (not integration) in this version.
  * MobileClient (capital C) in diagrams.aws.general.
  * No dedicated Bedrock KB / Titan / Guardrails icon exists — the generic
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


# ---- identical base styling to aria_architecture.py ----
graph_attr = {
    "dpi": "200",
    "fontsize": "26",
    "fontname": "Helvetica-Bold",
    "labelloc": "t",
    "pad": "0.6",
    "nodesep": "0.55",
    "ranksep": "1.4",          # a bit roomier so the blocks separate cleanly
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

# Macro-block wrappers — thick borders + tinted backgrounds so each crop is
# visually self-contained. (Organization only; no content change.)
macro_transcribe = {
    "fontsize": "22", "fontname": "Helvetica-Bold", "style": "rounded",
    "pencolor": "#1f6f78", "penwidth": "3.0", "margin": "26", "bgcolor": "#eef7f8",
}
macro_bedrock = {
    "fontsize": "22", "fontname": "Helvetica-Bold", "style": "rounded",
    "pencolor": "#6c3fa3", "penwidth": "3.0", "margin": "26", "bgcolor": "#f4eefb",
}
macro_output = {
    "fontsize": "22", "fontname": "Helvetica-Bold", "style": "rounded",
    "pencolor": "#c0641a", "penwidth": "3.0", "margin": "26", "bgcolor": "#fdf2e8",
}
input_cluster = {
    **cluster_attr, "pencolor": "#1f8a4c", "penwidth": "2.6",
    "bgcolor": "#eafaf0", "fontsize": "18", "fontcolor": "#1f8a4c",
}

# ---- identical edge styles to aria_architecture.py ----
FLOW = {"color": "#2d3e50", "penwidth": "1.8", "fontsize": "11", "fontname": "Helvetica"}
FINDINGS = {"color": "#1f8a4c", "penwidth": "1.4", "style": "dashed", "fontsize": "11", "fontname": "Helvetica"}
PARALLEL = {"color": "#1f8a4c", "penwidth": "1.6", "style": "bold", "fontsize": "11", "fontname": "Helvetica"}
RAG = {"color": "#8e44ad", "penwidth": "1.4", "style": "dashed", "fontsize": "10", "fontname": "Helvetica"}
SAFETY = {"color": "#c0392b", "penwidth": "2.0", "fontsize": "11", "fontname": "Helvetica-Bold"}
OUTPUT = {"color": "#d35400", "penwidth": "1.8", "fontsize": "11", "fontname": "Helvetica"}


with Diagram(
    "ARIA — Autonomous Response Intelligence Assistant",
    filename="aria_architecture_grouped",
    show=False,
    direction="TB",
    graph_attr=graph_attr,
    node_attr=node_attr,
):

    # ======================= BLOCK 1 — TRANSCRIBE =======================
    with Cluster("BLOCK 1 — Speech-to-Text", graph_attr=macro_transcribe):

        # Layer 1 — Input (clearly marked)
        with Cluster("▶ INPUT · Layer 1 — 911 Caller", graph_attr=input_cluster):
            caller = User("911 Caller\n(live audio stream)")

        # Layer 2 — Amazon Transcribe
        with Cluster("Layer 2 — Speech-to-Text", graph_attr=cluster_attr):
            transcribe = Transcribe("Amazon Transcribe\n(Streaming, word-level)")

        caller >> Edge(**FLOW, label="voice / text / video") >> transcribe

    # ======================= BLOCK 2 — AMAZON BEDROCK ===================
    with Cluster("BLOCK 2 — Amazon Bedrock", graph_attr=macro_bedrock):

        # Layer 3 — Dispatcher Agent
        with Cluster("Layer 3 — Dispatcher Agent (fast entity extraction)", graph_attr=cluster_attr):
            stream_proc = Lambda("aria-stream-processor\n(domain watchers)")
            dispatcher = Bedrock("Amazon Bedrock\nClaude Haiku 3.5\n(verify + extract)")

        # Layer 4 — Coordinator
        with Cluster("Layer 4 — Coordinator Agent · The Brain (Claude Sonnet 4)", graph_attr=cluster_attr):
            coordinator = Bedrock("Amazon Bedrock\nClaude Sonnet 4\n(multi-agent orchestration)")

        # Layer 6 — Knowledge Base (declared before L5 so specialists can query it)
        with Cluster("Layer 6 — Bedrock Knowledge Base (RAG)", graph_attr=cluster_attr):
            kb = Bedrock("Bedrock Knowledge Base\n(RAG retrieval)")
            kb_s3 = S3("S3 aria-knowledge-base\n(protocols / FEMA / SOPs)")
            titan = Bedrock("Amazon Titan\nEmbeddings v2")
            kb >> Edge(**RAG, label="embed") >> titan
            kb >> Edge(**RAG, label="vector search") >> kb_s3

        # Layer 5 — Four Specialist Agents in parallel
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

        # Layer 7 — Guardrails
        with Cluster("Layer 7 — Bedrock Guardrails (human-in-the-loop safety)", graph_attr=cluster_attr):
            guardrails = Bedrock("Bedrock Guardrails\n(no auto-execution)")

        # --- intra-Bedrock wiring ---
        stream_proc >> Edge(**FLOW, label="enrich") >> dispatcher
        dispatcher >> Edge(**FLOW, label="entities + severity") >> coordinator
        for sa in (nav_agent, med_agent, fire_agent, report_agent):
            coordinator >> Edge(**PARALLEL, label="spawn in parallel") >> sa
            sa >> Edge(**FINDINGS, label="findings") >> coordinator
        med_agent >> Edge(**RAG, label="query KB") >> kb
        fire_agent >> Edge(**RAG, label="query KB") >> kb
        coordinator >> Edge(**SAFETY, label="recommendation") >> guardrails

    # ======================= BLOCK 3 — OUTPUT ===========================
    with Cluster("BLOCK 3 — Output", graph_attr=macro_output):

        # Layer 8 — Dispatcher Dashboard
        with Cluster("Layer 8 — Dispatcher Dashboard", graph_attr=cluster_attr):
            cognito = Cognito("Cognito\n(auth)")
            apigw = APIGateway("API Gateway\n(REST + WebSocket)")
            dashboard = MobileClient("React Dashboard\n(dispatcher UI)")
            apigw >> Edge(**FLOW) >> dashboard
            cognito >> Edge(**FLOW, style="dashed", label="authn") >> apigw

        # Layer 9 — Outputs
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

        dashboard >> Edge(**OUTPUT, label="approve") >> out_sns_resp
        dashboard >> Edge(**OUTPUT, label="approve") >> out_sns_hosp
        dashboard >> Edge(**OUTPUT, label="approve") >> out_db
        out_db >> Edge(**OUTPUT, style="dashed") >> out_s3

    # ============ inter-block connectors (span the crop gaps) ============
    # minlen pushes the blocks apart so there is clear white space to crop on.
    # taillabel keeps the label hugging the upper block where the line exits,
    # so the connector stays labelled after the PNG is cropped at the gap.
    transcribe >> Edge(**FLOW, taillabel="live transcript", labeldistance="2.5",
                       labelangle="0", minlen="2") >> stream_proc
    guardrails >> Edge(**SAFETY, taillabel="human approval required", labeldistance="2.5",
                       labelangle="0", minlen="2") >> apigw

    print("Blocks: 1) Transcribe (Input+Transcribe)  2) Amazon Bedrock (Layers 3-7)  "
          "3) Output (Dashboard+Outputs). Same icons/edges as main script, regrouped for cropping.")
