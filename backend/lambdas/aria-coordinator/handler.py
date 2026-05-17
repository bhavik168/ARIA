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
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=os.environ["AWS_DEPLOY_REGION"])
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

# Bedrock Agent IDs — set by CDK after agents are created.
# When present, coordinator uses invoke_agent() (true multi-agent orchestration).
# When absent (local dev / first deploy), falls back to direct Lambda invocation.
NAVIGATION_AGENT_ID = os.environ.get("NAVIGATION_AGENT_ID", "")
NAVIGATION_AGENT_ALIAS_ID = os.environ.get("NAVIGATION_AGENT_ALIAS_ID", "")
MEDICAL_AGENT_ID = os.environ.get("MEDICAL_AGENT_ID", "")
MEDICAL_AGENT_ALIAS_ID = os.environ.get("MEDICAL_AGENT_ALIAS_ID", "")
HAZMAT_AGENT_ID = os.environ.get("HAZMAT_AGENT_ID", "")
HAZMAT_AGENT_ALIAS_ID = os.environ.get("HAZMAT_AGENT_ALIAS_ID", "")

SYNTHESIS_MODEL_ID = os.environ.get(
    "SYNTHESIS_MODEL_ID",
    "us.anthropic.claude-sonnet-4-20250514-v1:0",
)

# Timeout budgets (seconds)
AGENT_TIMEOUTS = {
    "navigation": 8,
    "medical": 10,
    "hazmat": 10,
    "report": 30,
}


@logger.inject_lambda_context
def lambda_handler(event, context):
    # Bedrock Agent action group invocation
    if event.get("messageVersion") == "1.0" and "actionGroup" in event:
        return _handle_agent_action(event)

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

    # Enrich incident_data with verifier classification if available
    incident_data = _apply_verifier_enrichment(incident_id, incident_data)

    results = _run_specialist_agents(incident_id, context_so_far, incident_data, t0)
    card = _synthesize_card(incident_id, context_so_far, results, incident_data, t0)

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


def _handle_agent_action(event: dict) -> dict:
    """Handle Bedrock Agent action group invocation (synthesize_recommendation function)."""
    params = {p["name"]: p["value"] for p in event.get("parameters", [])}
    incident_id = params.get("incident_id", "")
    context_so_far = params.get("context_so_far", "")
    trigger_reason = params.get("trigger_reason", "coordinator_agent")

    logger.info("Coordinator agent action invoked", extra={"incident_id": incident_id})
    t0 = int(time.time() * 1000)

    incident_data = _load_incident(incident_id)
    incident_data = _apply_verifier_enrichment(incident_id, incident_data)
    results = _run_specialist_agents(incident_id, context_so_far, incident_data, t0)
    card = _synthesize_card(incident_id, context_so_far, results, incident_data, t0)

    blocked, block_reason = _apply_guardrail(card)
    if not blocked:
        _save_recommendation(incident_id, card)
        _push_to_dashboard(incident_id, {"type": "recommendation_ready", "card": card})

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup"),
            "function": event.get("function"),
            "functionResponse": {
                "responseBody": {
                    "TEXT": {"body": json.dumps(card, default=str)}
                }
            },
        },
    }


def _run_specialist_agents(incident_id: str, context: str, incident_data: dict, t0: int) -> dict:
    """Invoke specialist agents concurrently via Bedrock multi-agent orchestration.

    Uses invoke_agent() when Bedrock Agent IDs are configured (true orchestration).
    Falls back to direct Lambda invocation when running locally or on first deploy.
    """
    incident_type = incident_data.get("incident_type", "unknown")
    verifier = incident_data.get("verifier_classification", {})
    verifier_json = json.dumps(verifier, default=str)

    # verifier_classification injected so each agent receives AI-enriched context
    payload_base = {
        "incident_id": incident_id,
        "context_so_far": context,
        "incident_data": incident_data,
        "verifier_classification": verifier,
    }

    # (fn_name, payload, agent_id, alias_id)
    agents_to_run: dict[str, tuple] = {
        "navigation": (
            NAVIGATION_FUNCTION,
            {**payload_base, "incident_type": incident_type},
            NAVIGATION_AGENT_ID,
            NAVIGATION_AGENT_ALIAS_ID,
        ),
        "report": (REPORT_FUNCTION, {**payload_base, "action": "start_logging"}, "", ""),
    }
    if incident_type in ("medical", "accident", "unknown"):
        agents_to_run["medical"] = (
            MEDICAL_FUNCTION, {**payload_base}, MEDICAL_AGENT_ID, MEDICAL_AGENT_ALIAS_ID,
        )
    if incident_type in ("fire", "hazmat"):
        agents_to_run["hazmat"] = (
            HAZMAT_FUNCTION, {**payload_base}, HAZMAT_AGENT_ID, HAZMAT_AGENT_ALIAS_ID,
        )

    results = {}

    def _invoke_sync(agent_name: str, fn_name: str, payload: dict, agent_id: str, alias_id: str) -> tuple:
        start = time.time()
        try:
            if agent_id and alias_id:
                result = _invoke_via_bedrock_agent(
                    agent_name, agent_id, alias_id, incident_id, context, verifier_json,
                    payload.get("trigger_reason", ""),
                )
            else:
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
                "via": "bedrock_agent" if (agent_id and alias_id) else "lambda_direct",
            })
            return agent_name, result
        except Exception as e:
            logger.error(f"Agent {agent_name} failed", exc_info=e)
            return agent_name, {"error": str(e), "status": "failed"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_invoke_sync, name, fn, payload, agent_id, alias_id): name
            for name, (fn, payload, agent_id, alias_id) in agents_to_run.items()
        }
        for future in concurrent.futures.as_completed(futures, timeout=max(AGENT_TIMEOUTS.values())):
            name, result = future.result()
            results[name] = result

            if name == "navigation" and incident_data.get("severity") == "critical":
                _push_to_dashboard(incident_id, {
                    "type": "partial_approval_available",
                    "unit": result.get("recommended_unit"),
                })

    return results


def _invoke_via_bedrock_agent(
    agent_name: str,
    agent_id: str,
    alias_id: str,
    incident_id: str,
    context: str,
    verifier_json: str,
    trigger_reason: str,
) -> dict:
    """Call a Bedrock Agent via invoke_agent() and collect the streaming response."""
    input_text = (
        f"Process this 911 emergency incident.\n"
        f"incident_id: {incident_id}\n"
        f"context_so_far: {context[:400]}\n"
        f"trigger_reason: {trigger_reason}\n"
        f"verifier_classification_json: {verifier_json}"
    )
    session_id = f"{incident_id}-{agent_name}-{int(time.time())}"
    try:
        resp = bedrock_agent_runtime.invoke_agent(
            agentId=agent_id,
            agentAliasId=alias_id,
            sessionId=session_id,
            inputText=input_text,
        )
        completion = ""
        for event in resp.get("completion", []):
            chunk = event.get("chunk", {})
            if "bytes" in chunk:
                completion += chunk["bytes"].decode("utf-8")

        completion = completion.strip()
        completion = completion.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(completion)
        except json.JSONDecodeError:
            logger.warning(f"Agent {agent_name} returned non-JSON — wrapping", extra={"raw": completion[:200]})
            return {"status": "ok", "raw_response": completion}
    except Exception as e:
        logger.error(f"invoke_agent failed for {agent_name}", exc_info=e)
        return {"status": "failed", "error": str(e)}


def _synthesize_card(incident_id: str, context: str, results: dict, incident_data: dict, t0: int) -> dict:
    nav = results.get("navigation", {})
    med = results.get("medical", {})
    haz = results.get("hazmat", {})
    verifier = incident_data.get("verifier_classification", {})

    agents_json = json.dumps({
        "navigation": {k: v for k, v in nav.items() if k != "error"},
        "medical": {k: v for k, v in med.items() if k != "error"},
        "hazmat": {k: v for k, v in haz.items() if k != "error"},
    }, default=str)

    prompt = (
        "You are ARIA, an AI emergency dispatch coordinator synthesizing a real-time recommendation card. "
        "Based on the 911 transcript excerpt, verifier AI classification, and specialist agent outputs below, "
        "produce a precise recommendation for the dispatcher.\n\n"
        f"TRANSCRIPT (excerpt):\n{context[:500]}\n\n"
        f"VERIFIER AI CLASSIFICATION:\n{json.dumps(verifier)}\n\n"
        f"SPECIALIST AGENT OUTPUTS:\n{agents_json}\n\n"
        "Reply ONLY with valid JSON matching this exact schema — no markdown, no explanation:\n"
        '{\n'
        '  "incident_type": "medical|fire|hazmat|crime|accident|unknown",\n'
        '  "severity": "critical|urgent|moderate|minor",\n'
        '  "summary": "2-3 sentence plain-English description of what is happening",\n'
        '  "dispatcher_action": "One clear sentence: what the dispatcher must do right now",\n'
        '  "triage_protocol": "Specific triage steps for responders, or null if not applicable",\n'
        '  "hazard_warnings": ["list of specific hazards responders must know about"],\n'
        '  "ai_confidence": "high|medium|low",\n'
        '  "reasoning_summary": "One sentence explaining why this recommendation was made"\n'
        '}'
    )

    try:
        resp = bedrock_runtime.invoke_model(
            modelId=SYNTHESIS_MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}],
            }),
            contentType="application/json",
            accept="application/json",
        )
        raw = json.loads(resp["body"].read())
        text = raw["content"][0]["text"].strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        synthesized = json.loads(text)
        logger.info("Sonnet synthesis complete", extra={"incident_id": incident_id})
    except Exception as e:
        logger.error("Sonnet synthesis failed — falling back to Python dict", exc_info=e)
        synthesized = _synthesize_card_fallback(nav, med, haz, context)

    return {
        **synthesized,
        "incident_id": incident_id,
        "recommended_unit": nav.get("recommended_unit"),
        "recommended_hospital": med.get("recommended_hospital"),
        "requires_approval": True,
        "generated_at_ms": int(time.time() * 1000),
        "agent_results": {k: v.get("status", "ok") for k, v in results.items()},
    }


def _synthesize_card_fallback(nav: dict, med: dict, haz: dict, context: str) -> dict:
    agents_ok = all(r.get("status") == "ok" for r in (nav, med) if r)
    confidence = "high" if agents_ok else "low"
    return {
        "incident_type": nav.get("incident_type", "unknown"),
        "severity": "urgent",
        "summary": context[:200] + "..." if len(context) > 200 else context,
        "dispatcher_action": "Dispatch recommended unit — manual verification required.",
        "triage_protocol": med.get("triage_protocol"),
        "hazard_warnings": haz.get("hazard_warnings", []),
        "ai_confidence": confidence,
        "reasoning_summary": "Fallback synthesis — Sonnet unavailable.",
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
    try:
        table.update_item(
            Key={"incident_id": incident_id, "timestamp": "latest"},
            UpdateExpression="SET dispatcher_approved = :t, approved_at_ms = :ts",
            ConditionExpression="attribute_exists(incident_id)",
            ExpressionAttributeValues={
                ":t": True,
                ":ts": int(time.time() * 1000),
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return _respond(404, {"error": "incident not found", "incident_id": incident_id})
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


def _apply_verifier_enrichment(incident_id: str, incident_data: dict) -> dict:
    """Read verifier classification from DynamoDB and refine incident type / severity."""
    verifier = incident_data.get("verifier_classification")
    if not verifier:
        return incident_data

    # Upgrade severity if verifier says critical
    current_severity = incident_data.get("severity", "urgent")
    verifier_severity = verifier.get("severity", "urgent")
    if verifier_severity == "critical" and current_severity != "critical":
        incident_data["severity"] = "critical"
        logger.info("Coordinator upgraded severity per verifier", extra={
            "incident_id": incident_id,
            "from": current_severity,
            "to": verifier_severity,
        })

    # Correct incident type if verifier strongly disagrees
    verifier_confidence = verifier.get("confidence", "low")
    if verifier_confidence in ("high", "medium"):
        # Map verifier booleans to incident_type priority
        if verifier.get("medical") and incident_data.get("incident_type") not in ("medical", "accident"):
            incident_data["incident_type"] = "medical"
            logger.info("Coordinator corrected incident_type per verifier", extra={
                "incident_id": incident_id,
                "corrected_to": "medical",
                "confidence": verifier_confidence,
            })
        elif verifier.get("fire") and incident_data.get("incident_type") not in ("fire", "hazmat"):
            incident_data["incident_type"] = "fire"
            logger.info("Coordinator corrected incident_type per verifier", extra={
                "incident_id": incident_id,
                "corrected_to": "fire",
                "confidence": verifier_confidence,
            })
        elif verifier.get("hazmat") and incident_data.get("incident_type") != "hazmat":
            incident_data["incident_type"] = "hazmat"
            logger.info("Coordinator corrected incident_type per verifier", extra={
                "incident_id": incident_id,
                "corrected_to": "hazmat",
                "confidence": verifier_confidence,
            })

    # Append detected conditions to resources_needed for medical incidents
    detected = verifier.get("detected_conditions", [])
    if detected and incident_data.get("incident_type") in ("medical", "accident", "unknown"):
        existing = set(incident_data.get("resources_needed", []))
        existing.update(detected)
        incident_data["resources_needed"] = list(existing)

    # If verifier flagged low confidence, mark for dispatcher review
    if verifier_confidence == "low":
        incident_data["_verifier_low_confidence"] = True

    _push_to_dashboard(incident_id, {
        "type": "context_enrichment",
        "source": "coordinator",
        "verifier_classification": verifier,
        "refined_incident_type": incident_data.get("incident_type"),
        "refined_severity": incident_data.get("severity"),
    })

    return incident_data


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
