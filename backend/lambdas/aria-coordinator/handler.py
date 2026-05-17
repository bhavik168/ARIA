"""
aria-coordinator — synthesizes specialist agent results into one recommendation card.

Triggered by aria-stream-processor when watchers fire, or by REST API for approve/override.
Runs specialist agents concurrently. Streams partial results to dashboard.
Synthesizes final recommendation card once all agents complete or timeout.
"""
import json
import os
import time
import concurrent.futures
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
REPORT_FUNCTION = os.environ.get("REPORT_FUNCTION", "aria-report")
WS_ENDPOINT = os.environ.get("WS_ENDPOINT", "")
GUARDRAIL_ID = os.environ.get("GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.environ.get("GUARDRAIL_VERSION", "DRAFT")

# Timeout budgets (seconds)
AGENT_TIMEOUTS = {
    "navigation": 8,
    "medical": 10,
    "hazmat": 10,
    "report": 30,
}


@logger.inject_lambda_context
def lambda_handler(event, context):
    # REST approve/override routes
    http_method = event.get("httpMethod")
    if http_method == "POST":
        path = event.get("path", "")
        if path.endswith("/approve"):
            return _handle_approve(event)
        elif path.endswith("/override"):
            return _handle_override(event)

    # Async invocation from stream processor
    incident_id = event.get("incident_id", "")
    context_so_far = event.get("context_so_far", "")
    trigger_reason = event.get("trigger_reason", "stream_processor")
    t0 = int(time.time() * 1000)

    if not incident_id:
        return {"status": "skipped"}

    logger.info("Coordinator starting", extra={"incident_id": incident_id, "trigger": trigger_reason})
    _push_to_dashboard(incident_id, {"type": "agent_started", "agent": "coordinator"})

    incident_data = _load_incident(incident_id)
    if incident_data.get("recommendation_ready"):
        return {"status": "already_complete"}

    results = _run_specialist_agents(incident_id, context_so_far, incident_data, t0)
    card = _synthesize_card(incident_id, context_so_far, results, t0)

    # Guardrail check on synthesized card before surfacing to dispatcher
    blocked, block_reason = _apply_guardrail(card)
    if blocked:
        logger.warning("Guardrail blocked recommendation card", extra={
            "incident_id": incident_id, "reason": block_reason,
        })
        _push_to_dashboard(incident_id, {
            "type": "guardrail_blocked",
            "reason": block_reason,
            "fallback": "Manual protocol required — contact supervisor",
        })
        return {"status": "guardrail_blocked", "reason": block_reason}

    _save_recommendation(incident_id, card)
    _push_to_dashboard(incident_id, {"type": "recommendation_ready", "card": card})

    elapsed = int(time.time() * 1000) - t0
    metrics.add_metric("coordinator_card_complete_ms", unit=MetricUnit.Milliseconds, value=elapsed)
    logger.info("Coordinator card complete", extra={"incident_id": incident_id, "ms": elapsed})

    return {"status": "ok", "incident_id": incident_id, "card": card}


def _run_specialist_agents(incident_id: str, context: str, incident_data: dict, t0: int) -> dict:
    """Invoke all relevant specialist agents concurrently. Never block stream processor."""
    incident_type = incident_data.get("incident_type", "unknown")
    severity = incident_data.get("severity", "urgent")
    payload_base = {"incident_id": incident_id, "context_so_far": context, "incident_data": incident_data}

    agents_to_run = {
        "navigation": (NAVIGATION_FUNCTION, {**payload_base, "incident_type": incident_type}),
        "report": (REPORT_FUNCTION, {**payload_base, "action": "start_logging"}),
    }
    if incident_type in ("medical", "accident", "unknown"):
        agents_to_run["medical"] = (MEDICAL_FUNCTION, {**payload_base})
    if incident_type in ("fire", "hazmat"):
        agents_to_run["hazmat"] = (HAZMAT_FUNCTION, {**payload_base})

    results = {}

    def _invoke_sync(agent_name: str, fn_name: str, payload: dict) -> tuple:
        start = time.time()
        try:
            resp = lambda_client.invoke(
                FunctionName=fn_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload).encode(),
            )
            result = json.loads(resp["Payload"].read())
            elapsed_ms = int((time.time() - start) * 1000)
            metrics.add_metric(f"{agent_name}_agent_complete_ms", unit=MetricUnit.Milliseconds, value=elapsed_ms)
            _push_to_dashboard(incident_id, {
                "type": "agent_complete",
                "agent": agent_name,
                "elapsed_ms": elapsed_ms,
            })
            return agent_name, result
        except Exception as e:
            logger.error(f"Agent {agent_name} failed", exc_info=e)
            return agent_name, {"error": str(e), "status": "failed"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_invoke_sync, name, fn, payload): name
            for name, (fn, payload) in agents_to_run.items()
        }
        for future in concurrent.futures.as_completed(
            futures, timeout=max(AGENT_TIMEOUTS.values())
        ):
            name, result = future.result()
            results[name] = result

            # For critical severity — push partial approval as soon as navigation returns
            if name == "navigation" and incident_data.get("severity") == "critical":
                _push_to_dashboard(incident_id, {
                    "type": "partial_approval_available",
                    "unit": result.get("recommended_unit"),
                })

    return results


def _synthesize_card(incident_id: str, context: str, results: dict, t0: int) -> dict:
    nav = results.get("navigation", {})
    med = results.get("medical", {})
    haz = results.get("hazmat", {})

    return {
        "incident_id": incident_id,
        "incident_type": results.get("navigation", {}).get("incident_type", "unknown"),
        "severity": "critical",  # Will be refined by Haiku verifier output
        "summary": context[:200] + "..." if len(context) > 200 else context,
        "recommended_unit": nav.get("recommended_unit"),
        "recommended_hospital": med.get("recommended_hospital"),
        "hazard_warnings": haz.get("hazard_warnings", []),
        "triage_protocol": med.get("triage_protocol"),
        "ai_confidence": "high" if all(r.get("status") != "failed" for r in results.values()) else "low",
        "reasoning_summary": "Recommendation synthesized from Navigation, Medical, and Specialist agents.",
        "requires_approval": True,
        "generated_at_ms": int(time.time() * 1000),
        "agent_results": {k: v.get("status", "ok") for k, v in results.items()},
    }


def _apply_guardrail(card: dict) -> tuple[bool, str]:
    """
    Apply Bedrock guardrail to the synthesized recommendation card text.
    Returns (blocked: bool, reason: str).
    Skips gracefully if GUARDRAIL_ID is not configured.
    """
    if not GUARDRAIL_ID:
        return False, ""

    # Flatten card to text for guardrail evaluation
    card_text = (
        f"Incident type: {card.get('incident_type', '')}. "
        f"Severity: {card.get('severity', '')}. "
        f"Summary: {card.get('summary', '')}. "
        f"Reasoning: {card.get('reasoning_summary', '')}. "
        f"Triage: {card.get('triage_protocol', '')}."
    )

    try:
        resp = bedrock_runtime.apply_guardrail(
            guardrailIdentifier=GUARDRAIL_ID,
            guardrailVersion=GUARDRAIL_VERSION,
            source="OUTPUT",
            content=[{"text": {"text": card_text}}],
        )
        action = resp.get("action", "NONE")
        if action == "GUARDRAIL_INTERVENED":
            outputs = resp.get("outputs", [])
            reason = outputs[0].get("text", "policy violation") if outputs else "policy violation"
            return True, reason
        return False, ""
    except Exception as e:
        # Guardrail failure is non-fatal — log and continue
        logger.warning("Guardrail apply_guardrail call failed — continuing without guardrail", exc_info=e)
        return False, ""


def _handle_approve(event: dict) -> dict:
    path_params = event.get("pathParameters") or {}
    incident_id = path_params.get("id", "")
    table = dynamodb.Table(INCIDENTS_TABLE)
    table.update_item(
        Key={"incident_id": incident_id, "timestamp": "latest"},
        UpdateExpression="SET dispatcher_approved = :t, approved_at_ms = :ts",
        ExpressionAttributeValues={
            ":t": True,
            ":ts": int(time.time() * 1000),
        },
    )
    _push_to_dashboard(incident_id, {"type": "dispatch_logged", "incident_id": incident_id})
    return _respond(200, {"status": "approved", "incident_id": incident_id})


def _handle_override(event: dict) -> dict:
    path_params = event.get("pathParameters") or {}
    incident_id = path_params.get("id", "")
    body = json.loads(event.get("body") or "{}")
    overrides_table = dynamodb.Table(os.environ.get("OVERRIDES_TABLE", "aria-overrides"))
    overrides_table.put_item(Item={
        "incident_id": incident_id,
        "timestamp": str(int(time.time() * 1000)),
        "aria_recommendation": body.get("aria_recommendation"),
        "dispatcher_choice": body.get("dispatcher_choice"),
        "override_reason": body.get("override_reason", "Other"),
        "notes": body.get("notes", ""),
    })
    return _respond(200, {"status": "override_recorded", "incident_id": incident_id})


def _load_incident(incident_id: str) -> dict:
    table = dynamodb.Table(INCIDENTS_TABLE)
    result = table.query(
        KeyConditionExpression="incident_id = :id",
        ExpressionAttributeValues={":id": incident_id},
        ScanIndexForward=False,
        Limit=1,
    )
    return result.get("Items", [{}])[0]


def _save_recommendation(incident_id: str, card: dict) -> None:
    table = dynamodb.Table(INCIDENTS_TABLE)
    table.update_item(
        Key={"incident_id": incident_id, "timestamp": "latest"},
        UpdateExpression="SET recommendation_card = :card, recommendation_ready = :t",
        ExpressionAttributeValues={":card": card, ":t": True},
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


def _respond(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body, default=str),
    }
