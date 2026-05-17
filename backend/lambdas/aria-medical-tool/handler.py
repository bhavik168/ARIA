"""
aria-medical-tool — retrieves triage protocol from KB, identifies closest hospital, sends pre-alert.

Triggered by aria-stream-processor (MedicalWatcher) or aria-coordinator.
Uses Bedrock Knowledge Base for protocol retrieval.
Calls aria-mock-hospital for pre-alert.
"""
import json
import os
import time
import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
metrics = Metrics()

dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_DEPLOY_REGION"])
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=os.environ["AWS_DEPLOY_REGION"])
lambda_client = boto3.client("lambda", region_name=os.environ["AWS_DEPLOY_REGION"])
apigw_mgmt = None

HOSPITALS_TABLE = os.environ["HOSPITALS_TABLE"]
INCIDENTS_TABLE = os.environ["INCIDENTS_TABLE"]
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
BEDROCK_KB_ID = os.environ.get("BEDROCK_KB_ID", "")
MOCK_HOSPITAL_FUNCTION = os.environ.get("MOCK_HOSPITAL_FUNCTION", "aria-mock-hospital")
WS_ENDPOINT = os.environ.get("WS_ENDPOINT", "")


@logger.inject_lambda_context
def lambda_handler(event, context):
    t0 = int(time.time() * 1000)
    incident_id = event.get("incident_id", "")
    context_so_far = event.get("context_so_far", "")
    incident_data = event.get("incident_data", {})

    logger.info("Medical tool invoked", extra={"incident_id": incident_id})

    triage_protocol, source_doc = _retrieve_triage_protocol(context_so_far)
    hospital = _find_closest_hospital(incident_data)
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
    _push_to_dashboard(incident_id, {"type": "agent_complete", "agent": "medical", "result": result})
    return result


def _retrieve_triage_protocol(context: str) -> tuple[str, str]:
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
                best["content"]["text"][:500],
                best.get("location", {}).get("s3Location", {}).get("uri", "knowledge-base"),
            )
    except Exception as e:
        logger.warning("KB retrieval failed", exc_info=e)

    return "BLS protocol: assess ABCs, call for ALS backup, prepare defibrillator.", "fallback"


def _find_closest_hospital(incident_data: dict) -> dict:
    table = dynamodb.Table(HOSPITALS_TABLE)
    resp = table.scan(Limit=10)
    hospitals = resp.get("Items", [])
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


def _update_incident(incident_id: str, result: dict, t0: int) -> None:
    table = dynamodb.Table(INCIDENTS_TABLE)
    table.update_item(
        Key={"incident_id": incident_id, "timestamp": "latest"},
        UpdateExpression="SET medical_result = :m, medical_at_ms = :ts",
        ExpressionAttributeValues={":m": result, ":ts": t0},
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
