"""
aria-medical-tool — retrieves triage protocol from KB, identifies closest hospital, sends pre-alert.

Triggered by aria-stream-processor (MedicalWatcher) or aria-coordinator.
Uses Bedrock Knowledge Base for protocol retrieval.
Calls aria-mock-hospital for pre-alert.
"""
import json
import os
import re
import time
import boto3
from decimal import Decimal
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
metrics = Metrics()

dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_DEPLOY_REGION"])
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=os.environ["AWS_DEPLOY_REGION"])
bedrock_runtime = boto3.client("bedrock-runtime", region_name=os.environ["AWS_DEPLOY_REGION"])
lambda_client = boto3.client("lambda", region_name=os.environ["AWS_DEPLOY_REGION"])
apigw_mgmt = None

HOSPITALS_TABLE = os.environ["HOSPITALS_TABLE"]
INCIDENTS_TABLE = os.environ["INCIDENTS_TABLE"]
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
BEDROCK_KB_ID = os.environ.get("BEDROCK_KB_ID", "")
MOCK_HOSPITAL_FUNCTION = os.environ.get("MOCK_HOSPITAL_FUNCTION", "aria-mock-hospital")
MEDICAL_MODEL_ID = os.environ.get(
    "MEDICAL_MODEL_ID",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
)
WS_ENDPOINT = os.environ.get("WS_ENDPOINT", "")

# ─── Hospital name detection from transcript ────────────────────────────────

KNOWN_HOSPITALS = {
    # canonical_name: [list of phrases to detect in transcript]
    "Harborview Medical Center": ["harborview medical center", "harborview"],
    "UW Medical Center": ["uw medical center", "university of washington medical center", "uw hospital"],
    "Swedish Medical Center": ["swedish medical center", "swedish first hill", "swedish"],
    "Seattle Children's Hospital": ["seattle children's hospital", "children's hospital", "seattle childrens"],
    "Overlake Medical Center": ["overlake medical center", "overlake"],
}


def _detect_hospital_name(context: str) -> str | None:
    """Scan transcript context for known hospital names."""
    lower = context.lower()
    for canonical, phrases in KNOWN_HOSPITALS.items():
        for phrase in phrases:
            if phrase in lower:
                return canonical
    return None


@logger.inject_lambda_context
def lambda_handler(event, context):
    if event.get("messageVersion") == "1.0" and "actionGroup" in event:
        return _handle_agent_action(event)
    return _handle_direct(event)


def _handle_agent_action(event: dict) -> dict:
    """Handle Bedrock Agent action group invocation."""
    action_group = event.get("actionGroup", "MedicalActions")
    function = event.get("function", "assess_medical_emergency")
    params = {p["name"]: p["value"] for p in event.get("parameters", [])}

    incident_id = params.get("incident_id", "")
    context_so_far = params.get("context_so_far", "")
    verifier_json = params.get("verifier_classification_json", "{}")
    try:
        verifier = json.loads(verifier_json)
    except (json.JSONDecodeError, TypeError):
        verifier = {}

    logger.info("Medical agent action invoked", extra={"incident_id": incident_id, "function": function})
    result = _run_medical(incident_id, context_so_far, {}, verifier, int(time.time() * 1000))

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "function": function,
            "functionResponse": {
                "responseBody": {
                    "TEXT": {"body": json.dumps(result, default=str)}
                }
            },
        },
    }


def _handle_direct(event: dict) -> dict:
    """Handle direct Lambda invocation from coordinator fallback or stream processor."""
    t0 = int(time.time() * 1000)
    incident_id = event.get("incident_id", "")
    context_so_far = event.get("context_so_far", "")
    incident_data = event.get("incident_data", {})
    verifier = event.get("verifier_classification", {})

    logger.info("Medical tool invoked (direct)", extra={"incident_id": incident_id})
    result = _run_medical(incident_id, context_so_far, incident_data, verifier, t0)
    _push_to_dashboard(incident_id, {"type": "agent_complete", "agent": "medical", "result": result})
    return result


def _run_medical(incident_id: str, context_so_far: str, incident_data: dict, verifier: dict, t0: int) -> dict:
    kb_text, source_doc = _retrieve_triage_protocol(context_so_far)
    triage_protocol = _interpret_protocol(kb_text, context_so_far, verifier)

    detected_name = _detect_hospital_name(context_so_far)
    if detected_name:
        logger.info("Hospital detected from transcript", extra={"incident_id": incident_id, "hospital": detected_name})
        _push_to_dashboard(incident_id, {
            "type": "log",
            "agent": "medical",
            "line": {"ts": _iso_ts(), "text": f"Contacting {detected_name}..."},
        })

    hospital = _find_closest_hospital(incident_data, detected_name)
    pre_alert_status = _send_pre_alert(hospital, incident_data)

    elapsed_ms = int(time.time() * 1000) - t0
    metrics.add_metric("medical_agent_complete_ms", unit=MetricUnit.Milliseconds, value=elapsed_ms)

    result = {
        "status": "ok",
        "incident_id": incident_id,
        "triage_protocol": triage_protocol,
        "source_document": source_doc,
        "recommended_hospital": hospital,
        "pre_alert_status": pre_alert_status,
        "elapsed_ms": elapsed_ms,
    }
    _update_incident(incident_id, result, t0)
    return result


def _retrieve_triage_protocol(context: str) -> tuple[str, str]:
    """Retrieve raw triage protocol text from KB. Returns (kb_text, source_doc)."""
    if not BEDROCK_KB_ID:
        return "Standard BLS protocol — airway, breathing, circulation. Activate AED if available.", "default-sop"

    try:
        resp = bedrock_agent_runtime.retrieve(
            knowledgeBaseId=BEDROCK_KB_ID,
            retrievalQuery={"text": f"Medical emergency triage protocol: {context[:300]}"},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": 5}
            },
        )
        chunks = resp.get("retrievalResults", [])
        if chunks:
            best = chunks[0]
            return (
                best["content"]["text"][:600],
                best.get("location", {}).get("s3Location", {}).get("uri", "knowledge-base"),
            )
    except Exception as e:
        logger.warning("KB retrieval failed", exc_info=e)

    return "BLS protocol: assess ABCs, call for ALS backup, prepare defibrillator.", "fallback"


def _interpret_protocol(kb_text: str, context: str, verifier: dict) -> str:
    """Call Claude Haiku to produce incident-specific triage instructions from raw KB text."""
    conditions = verifier.get("detected_conditions", [])
    severity = verifier.get("severity", "urgent")
    victim_count = verifier.get("victim_count_estimate")

    victim_line = f"Estimated victims: {victim_count}." if victim_count else ""
    conditions_line = f"AI-detected conditions: {', '.join(conditions)}." if conditions else ""

    prompt = (
        "You are a 911 medical coordinator. Given the caller transcript, AI-detected conditions, "
        "and the relevant protocol excerpt from the medical knowledge base, write specific numbered "
        "triage instructions for the responding EMS crew. Be concrete and incident-specific.\n\n"
        f"CALLER TRANSCRIPT:\n{context[:300]}\n\n"
        f"SEVERITY: {severity}. {victim_line} {conditions_line}\n\n"
        f"PROTOCOL FROM KNOWLEDGE BASE:\n{kb_text}\n\n"
        "Write 3 numbered, actionable EMS instructions tailored to THIS incident. "
        "No headers, no markdown."
    )

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 300,
        "temperature": 0.1,
        "messages": [{"role": "user", "content": prompt}],
    })
    for attempt in range(3):
        try:
            resp = bedrock_runtime.invoke_model(
                modelId=MEDICAL_MODEL_ID,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            raw = json.loads(resp["body"].read())
            return raw["content"][0]["text"].strip()
        except Exception as e:
            if "ThrottlingException" in type(e).__name__ and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            logger.warning("Protocol interpretation failed — using raw KB text", exc_info=e)
            return kb_text[:500]
    return kb_text[:500]


def _find_closest_hospital(incident_data: dict, detected_name: str | None) -> dict:
    table = dynamodb.Table(HOSPITALS_TABLE)
    resp = table.scan(Limit=10)
    hospitals = resp.get("Items", [])

    # If a hospital was named in the transcript, use it directly
    if detected_name:
        return {
            "hospital_id": "DETECTED",
            "name": detected_name,
            "eta_minutes": incident_data.get("location", {}).get("eta_minutes", 7),
            "er_status": "accepting",
            "capabilities": [],
        }

    if not hospitals:
        return {"hospital_id": "H001", "name": "City General Hospital", "eta_minutes": 6, "er_status": "accepting"}

    # Simple heuristic: return first accepting hospital (real implementation uses geo distance)
    for h in hospitals:
        if h.get("er_status", "accepting") in ("accepting", "preparing"):
            return {
                "hospital_id": h["hospital_id"],
                "name": h.get("name", "Unknown Hospital"),
                "eta_minutes": h.get("distance_minutes", 7),
                "er_status": h.get("er_status", "accepting"),
                "capabilities": h.get("capabilities", []),
            }
    return hospitals[0]


def _send_pre_alert(hospital: dict, incident_data: dict) -> dict:
    payload = {
        "hospital_id": hospital.get("hospital_id", "H001"),
        "hospital_name": hospital.get("name", "Unknown Hospital"),
        "patient_condition": incident_data.get("incident_type", "medical_emergency"),
        "eta_minutes": hospital.get("eta_minutes", 7),
        "resources_needed": incident_data.get("resources_needed", ["trauma_bay"]),
    }
    try:
        resp = lambda_client.invoke(
            FunctionName=MOCK_HOSPITAL_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode(),
        )
        return json.loads(resp["Payload"].read())
    except Exception as e:
        logger.error("Mock hospital pre-alert failed", exc_info=e)
        return {"status": "pending", "notes": "Pre-alert delivery pending"}


def _to_dynamo(obj):
    """Recursively convert float → Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dynamo(v) for v in obj]
    return obj


def _update_incident(incident_id: str, result: dict, t0: int) -> None:
    table = dynamodb.Table(INCIDENTS_TABLE)
    table.update_item(
        Key={"incident_id": incident_id, "timestamp": "latest"},
        UpdateExpression="SET medical_result = :m, medical_at_ms = :ts",
        ExpressionAttributeValues={":m": _to_dynamo(result), ":ts": t0},
    )


def _push_to_dashboard(incident_id: str, payload: dict) -> None:
    global apigw_mgmt
    if not WS_ENDPOINT:
        return
    try:
        if apigw_mgmt is None:
            endpoint = WS_ENDPOINT.replace("wss://", "https://")
            apigw_mgmt = boto3.client(
                "apigatewaymanagementapi",
                endpoint_url=endpoint,
                region_name=os.environ["AWS_DEPLOY_REGION"],
            )
        conn_table = dynamodb.Table(CONNECTIONS_TABLE)
        conns = conn_table.query(
            IndexName="incident-index",
            KeyConditionExpression="incident_id = :iid",
            ExpressionAttributeValues={":iid": incident_id},
        ).get("Items", [])
        data = json.dumps(payload).encode()
        for conn in conns:
            try:
                apigw_mgmt.post_to_connection(ConnectionId=conn["connection_id"], Data=data)
            except Exception:
                pass
    except Exception as e:
        logger.warning("_push_to_dashboard failed (non-fatal)", exc_info=e)


def _iso_ts() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
