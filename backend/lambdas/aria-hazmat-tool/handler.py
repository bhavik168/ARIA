"""
aria-hazmat-tool — retrieves hazard data from KB, calculates evacuation radius, recommends PPE.

Triggered by aria-stream-processor (FireWatcher / HazmatWatcher) or aria-coordinator.
Uses FEMA ERG and NIOSH guides from Bedrock Knowledge Base.
"""
import json
import os
import time
import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
metrics = Metrics()

bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=os.environ["AWS_DEPLOY_REGION"])
bedrock_runtime = boto3.client("bedrock-runtime", region_name=os.environ["AWS_DEPLOY_REGION"])
dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_DEPLOY_REGION"])
apigw_mgmt = None

INCIDENTS_TABLE = os.environ["INCIDENTS_TABLE"]
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
BEDROCK_KB_ID = os.environ.get("BEDROCK_KB_ID", "")
WS_ENDPOINT = os.environ.get("WS_ENDPOINT", "")
HAZMAT_MODEL_ID = os.environ.get(
    "HAZMAT_MODEL_ID",
    "us.anthropic.claude-3-5-haiku-20241022-v1:0",
)

FIRE_DEFAULTS = {
    "hazard_type": "structure_fire",
    "evacuation_radius_meters": 150,
    "protective_equipment": ["SCBA", "structural firefighting gear", "gloves"],
    "suppression_approach": "Standard engine company attack — establish water supply, initiate primary search",
    "fema_erg_guide_number": None,
}

HAZMAT_DEFAULTS = {
    "hazard_type": "chemical_unknown",
    "evacuation_radius_meters": 300,
    "protective_equipment": ["Level B HAZMAT suit", "SCBA", "chemical resistant gloves"],
    "suppression_approach": "Do not enter until substance identified — isolate and deny entry",
    "fema_erg_guide_number": "111",
}


@logger.inject_lambda_context
def lambda_handler(event, context):
    if event.get("action") == "ping":
        return {"status": "warm"}
    if event.get("messageVersion") == "1.0" and "actionGroup" in event:
        return _handle_agent_action(event)
    return _handle_direct(event)


def _handle_agent_action(event: dict) -> dict:
    """Handle Bedrock Agent action group invocation."""
    action_group = event.get("actionGroup", "HazmatActions")
    function = event.get("function", "assess_hazard")
    params = {p["name"]: p["value"] for p in event.get("parameters", [])}

    incident_id = params.get("incident_id", "")
    context_so_far = params.get("context_so_far", "")
    trigger_reason = params.get("trigger_reason", "fire_keyword_detected")
    verifier_json = params.get("verifier_classification_json", "{}")
    try:
        verifier = json.loads(verifier_json)
    except (json.JSONDecodeError, TypeError):
        verifier = {}

    logger.info("Hazmat agent action invoked", extra={"incident_id": incident_id, "function": function})
    result = _run_hazmat(incident_id, context_so_far, trigger_reason, verifier, int(time.time() * 1000))

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
    trigger_reason = event.get("trigger_reason", "fire_keyword_detected")
    verifier = event.get("verifier_classification", {})

    logger.info("Hazmat tool invoked (direct)", extra={"incident_id": incident_id, "trigger": trigger_reason})
    result = _run_hazmat(incident_id, context_so_far, trigger_reason, verifier, t0)
    _push_to_dashboard(incident_id, {"type": "agent_complete", "agent": "hazmat", "result": result})
    return result


def _run_hazmat(incident_id: str, context_so_far: str, trigger_reason: str, verifier: dict, t0: int) -> dict:
    is_hazmat = trigger_reason in ("hazmat_keyword_detected", "hazmat_updated", "verifier_hazmat_detected") \
        or verifier.get("hazmat") \
        or "chemical" in context_so_far.lower()
    kb_result = _retrieve_hazard_data(context_so_far, is_hazmat)
    interpreted = _interpret_hazard_data(kb_result, context_so_far, is_hazmat, verifier)

    elapsed_ms = int(time.time() * 1000) - t0
    metrics.add_metric("hazmat_agent_complete_ms", unit=MetricUnit.Milliseconds, value=elapsed_ms)

    result = {**(_build_result(kb_result, is_hazmat)), **interpreted, "incident_id": incident_id, "elapsed_ms": elapsed_ms}
    _update_incident(incident_id, result, t0)
    return result


def _retrieve_hazard_data(context: str, is_hazmat: bool) -> dict:
    query = (
        f"Hazmat chemical spill evacuation radius protective equipment: {context[:300]}"
        if is_hazmat
        else f"Structure fire evacuation radius suppression approach: {context[:300]}"
    )

    if not BEDROCK_KB_ID:
        return {}

    try:
        resp = bedrock_agent_runtime.retrieve(
            knowledgeBaseId=BEDROCK_KB_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 5}},
        )
        chunks = resp.get("retrievalResults", [])
        if chunks:
            return {
                "content": chunks[0]["content"]["text"][:800],
                "source": chunks[0].get("location", {}).get("s3Location", {}).get("uri", ""),
                "score": chunks[0].get("score", 0),
            }
    except Exception as e:
        logger.warning("KB retrieval failed, using defaults", exc_info=e)
    return {}


def _interpret_hazard_data(kb_result: dict, context: str, is_hazmat: bool, verifier: dict) -> dict:
    """Call Claude Haiku to produce incident-specific hazard instructions from raw KB text."""
    kb_text = kb_result.get("content", "")
    if not kb_text:
        return {}

    incident_kind = "chemical hazmat spill" if is_hazmat else "structure fire"
    conditions = verifier.get("detected_conditions", [])
    severity = verifier.get("severity", "urgent")

    prompt = (
        f"You are a hazmat/fire safety coordinator. Given the caller transcript and relevant FEMA/NIOSH "
        f"knowledge base excerpt, provide specific responder instructions for this {incident_kind}.\n\n"
        f"CALLER TRANSCRIPT:\n{context[:300]}\n\n"
        f"SEVERITY: {severity}. "
        f"{'AI-detected conditions: ' + ', '.join(conditions) + '.' if conditions else ''}\n\n"
        f"KNOWLEDGE BASE EXCERPT:\n{kb_text[:600]}\n\n"
        "Reply ONLY with valid JSON — no markdown:\n"
        "{\n"
        '  "hazard_warnings": ["specific hazard warnings for responders"],\n'
        '  "evacuation_radius_meters": integer,\n'
        '  "protective_equipment": ["required PPE items"],\n'
        '  "suppression_approach": "specific approach for this incident",\n'
        '  "priority_action": "one sentence: what responders must do first"\n'
        "}"
    )

    try:
        resp = bedrock_runtime.invoke_model(
            modelId=HAZMAT_MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 400,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}],
            }),
            contentType="application/json",
            accept="application/json",
        )
        raw = json.loads(resp["body"].read())
        text = raw["content"][0]["text"].strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(text)
    except Exception as e:
        logger.warning("Hazard data interpretation failed — using KB defaults", exc_info=e)
        return {}


def _build_result(kb_result: dict, is_hazmat: bool) -> dict:
    defaults = HAZMAT_DEFAULTS if is_hazmat else FIRE_DEFAULTS
    result = {**defaults, "status": "ok", "source_document": kb_result.get("source", "default-sop")}
    if kb_result.get("content"):
        result["kb_excerpt"] = kb_result["content"]
    return result


def _update_incident(incident_id: str, result: dict, t0: int) -> None:
    table = dynamodb.Table(INCIDENTS_TABLE)
    table.update_item(
        Key={"incident_id": incident_id, "timestamp": "latest"},
        UpdateExpression="SET hazmat_result = :h, hazmat_at_ms = :ts",
        ExpressionAttributeValues={":h": result, ":ts": t0},
    )


def _push_to_dashboard(incident_id: str, payload: dict) -> None:
    global apigw_mgmt
    if not WS_ENDPOINT:
        return
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
