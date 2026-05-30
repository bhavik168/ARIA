"""
aria-verifier — semantic incident classifier using Bedrock Claude Haiku 3.5.

Triggered by aria-stream-processor every 10 words (or when any watcher fires).
Reads transcript context, classifies via Haiku, and:
1. Triggers specialist agents that haven't fired yet but are semantically detected.
2. Pushes context enrichment to coordinator + dashboard.

This replaces brittle hardcoded keyword matching with real semantic understanding.
"""
import json
import os
import time
import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
metrics = Metrics()

lambda_client = boto3.client("lambda", region_name=os.environ["AWS_DEPLOY_REGION"])
dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_DEPLOY_REGION"])
bedrock_runtime = boto3.client("bedrock-runtime", region_name=os.environ["AWS_DEPLOY_REGION"])
apigw_mgmt = None

INCIDENTS_TABLE = os.environ["INCIDENTS_TABLE"]
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
NAVIGATION_FUNCTION = os.environ.get("NAVIGATION_FUNCTION", "aria-navigation-tool")
MEDICAL_FUNCTION = os.environ.get("MEDICAL_FUNCTION", "aria-medical-tool")
HAZMAT_FUNCTION = os.environ.get("HAZMAT_FUNCTION", "aria-hazmat-tool")
WS_ENDPOINT = os.environ.get("WS_ENDPOINT", "")

# Claude Haiku 3.5 model ID (cross-region inference)
VERIFIER_MODEL_ID = os.environ.get(
    "VERIFIER_MODEL_ID",
    "us.anthropic.claude-3-5-haiku-20241022-v1:0",
)

# In-memory deduplication per Lambda warm context
_verifier_fired_agents: dict[str, set] = {}


@logger.inject_lambda_context
def lambda_handler(event, context):
    if event.get("action") == "ping":
        return {"status": "warm"}
    t0 = int(time.time() * 1000)
    incident_id = event.get("incident_id", "")
    transcript = event.get("context_so_far", "")
    timestamp_ms = event.get("timestamp_ms", t0)

    if not incident_id or not transcript:
        return {"status": "skipped"}

    logger.info("Verifier invoked", extra={"incident_id": incident_id, "words": len(transcript.split())})

    classification = _classify_transcript(transcript)
    elapsed_ms = int(time.time() * 1000) - t0
    metrics.add_metric("verifier_classify_ms", unit=MetricUnit.Milliseconds, value=elapsed_ms)

    # Track what this verifier run decided
    logger.info("Verifier classification", extra={
        "incident_id": incident_id,
        "classification": classification,
        "elapsed_ms": elapsed_ms,
    })

    # 1. Trigger any undetected specialist agents
    _trigger_missing_agents(incident_id, transcript, classification, timestamp_ms)

    # 2. Push enrichment to coordinator + dashboard
    _push_enrichment(incident_id, classification, elapsed_ms)

    return {
        "status": "ok",
        "incident_id": incident_id,
        "classification": classification,
        "verifier_ms": elapsed_ms,
    }


def _classify_transcript(transcript: str) -> dict:
    """Call Bedrock Claude Haiku 3.5 to semantically classify the transcript."""
    system_prompt = (
        "You are a 911 emergency call classifier. Given the caller transcript below, "
        "classify the incident type, severity, and any inferred conditions. "
        "Reply ONLY with valid JSON, no markdown, no explanations."
    )

    user_prompt = f"""Transcript: "{transcript}"

Reply ONLY with valid JSON matching this exact schema:
{{
  "medical": true or false,
  "fire": true or false,
  "hazmat": true or false,
  "crime": true or false,
  "severity": "critical" or "urgent" or "moderate" or "minor",
  "victim_count_estimate": null or an integer,
  "detected_conditions": ["list of inferred medical or hazard conditions"],
  "confidence": "high" or "medium" or "low",
  "location_hint": null or a string describing the location if any,
  "notes": "brief reasoning in one sentence"
}}"""

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 256,
        "temperature": 0.0,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        resp = bedrock_runtime.invoke_model(
            modelId=VERIFIER_MODEL_ID,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json",
        )
        raw = json.loads(resp["body"].read())
        content = raw.get("content", [])
        if content:
            text = content[0].get("text", "")
            # Strip any accidental markdown fences
            text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = json.loads(text)
            return _sanitize_classification(parsed)
    except json.JSONDecodeError as e:
        logger.warning("Verifier returned invalid JSON", extra={"error": str(e), "raw": text if 'text' in locals() else "n/a"})
    except Exception as e:
        logger.error("Bedrock verifier call failed", exc_info=e)

    # Fallback: return neutral classification so we don't block anything
    return _neutral_classification()


def _sanitize_classification(raw: dict) -> dict:
    """Ensure the parsed JSON has all required keys with valid values."""
    return {
        "medical": bool(raw.get("medical", False)),
        "fire": bool(raw.get("fire", False)),
        "hazmat": bool(raw.get("hazmat", False)),
        "crime": bool(raw.get("crime", False)),
        "severity": raw.get("severity", "urgent") if raw.get("severity") in ("critical", "urgent", "moderate", "minor") else "urgent",
        "victim_count_estimate": raw.get("victim_count_estimate") if isinstance(raw.get("victim_count_estimate"), int) else None,
        "detected_conditions": raw.get("detected_conditions", []) if isinstance(raw.get("detected_conditions"), list) else [],
        "confidence": raw.get("confidence", "low") if raw.get("confidence") in ("high", "medium", "low") else "low",
        "location_hint": raw.get("location_hint") if isinstance(raw.get("location_hint"), str) else None,
        "notes": raw.get("notes", "") if isinstance(raw.get("notes"), str) else "",
    }


def _neutral_classification() -> dict:
    return {
        "medical": False,
        "fire": False,
        "hazmat": False,
        "crime": False,
        "severity": "urgent",
        "victim_count_estimate": None,
        "detected_conditions": [],
        "confidence": "low",
        "location_hint": None,
        "notes": "Verifier fallback — no classification available",
    }


def _trigger_missing_agents(incident_id: str, transcript: str, classification: dict, ts: int) -> None:
    """If Haiku detected a domain that hasn't triggered yet, fire the agent asynchronously."""
    fired = _verifier_fired_agents.setdefault(incident_id, set())

    # Also check DynamoDB for already-fired agents (in case Lambda cold-started)
    _sync_fired_from_ddb(incident_id, fired)

    agent_map = {
        "medical": (MEDICAL_FUNCTION, "verifier_medical_detected"),
        "fire": (HAZMAT_FUNCTION, "verifier_fire_detected"),
        "hazmat": (HAZMAT_FUNCTION, "verifier_hazmat_detected"),
        "crime": (NAVIGATION_FUNCTION, "verifier_crime_detected"),
    }

    for domain, (fn_name, trigger_reason) in agent_map.items():
        if classification.get(domain) and domain not in fired:
            fired.add(domain)
            logger.info(f"Verifier triggering {domain} agent", extra={
                "incident_id": incident_id,
                "agent": domain,
                "trigger_reason": trigger_reason,
            })
            _async_invoke_agent(fn_name, incident_id, transcript, trigger_reason, ts)
            metrics.add_metric(f"verifier_triggered_{domain}", unit=MetricUnit.Count, value=1)

    # If location hint present and location agent hasn't fired, try navigation
    if classification.get("location_hint") and "location" not in fired:
        fired.add("location")
        _async_invoke_agent(NAVIGATION_FUNCTION, incident_id, transcript, "verifier_location_detected", ts)


def _sync_fired_from_ddb(incident_id: str, fired: set) -> None:
    """Read incident record to see which agents already ran, to avoid duplicates."""
    try:
        table = dynamodb.Table(INCIDENTS_TABLE)
        resp = table.get_item(Key={"incident_id": incident_id, "timestamp": "latest"})
        item = resp.get("Item", {})
        if item.get("medical_result"):
            fired.add("medical")
        if item.get("navigation_result"):
            fired.add("location")  # navigation covers location
        if item.get("hazmat_result"):
            fired.add("hazmat")
            fired.add("fire")  # hazmat tool handles both
    except Exception:
        pass  # Non-fatal; worst case we might duplicate an agent invoke


def _async_invoke_agent(function_name: str, incident_id: str, context: str, trigger_reason: str, ts: int) -> None:
    payload = {
        "incident_id": incident_id,
        "context_so_far": context,
        "trigger_reason": trigger_reason,
        "triggered_at_ms": ts,
        "source": "verifier",
    }
    try:
        lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="Event",
            Payload=json.dumps(payload).encode(),
        )
    except Exception as e:
        logger.error(f"Verifier failed to invoke {function_name}", exc_info=e)


def _push_enrichment(incident_id: str, classification: dict, verifier_ms: int) -> None:
    """Write enrichment to incident record and push to dashboard WebSocket."""
    enrichment = {
        "type": "context_enrichment",
        "source": "verifier",
        "classification": classification,
        "verifier_ms": verifier_ms,
        "enriched_at_ms": int(time.time() * 1000),
    }

    # Persist to DynamoDB for coordinator to read
    try:
        table = dynamodb.Table(INCIDENTS_TABLE)
        table.update_item(
            Key={"incident_id": incident_id, "timestamp": "latest"},
            UpdateExpression="SET verifier_classification = :c, verifier_at_ms = :t",
            ExpressionAttributeValues={":c": classification, ":t": int(time.time() * 1000)},
        )
    except Exception as e:
        logger.warning("Failed to persist verifier classification", exc_info=e)

    # Push to dashboard
    _push_to_dashboard(incident_id, enrichment)


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
    data = json.dumps(payload, default=str).encode()
    for conn in conns:
        try:
            apigw_mgmt.post_to_connection(ConnectionId=conn["connection_id"], Data=data)
        except apigw_mgmt.exceptions.GoneException:
            conn_table.delete_item(Key={"connection_id": conn["connection_id"]})
        except Exception:
            pass
