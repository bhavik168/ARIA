"""
aria-report — generates structured after-action report from incident DynamoDB record.

Triggered by aria-coordinator at incident close.
Reads full incident from DynamoDB, generates report JSON + markdown, writes to S3.
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
s3 = boto3.client("s3", region_name=os.environ["AWS_DEPLOY_REGION"])
bedrock_runtime = boto3.client("bedrock-runtime", region_name=os.environ["AWS_DEPLOY_REGION"])
apigw_mgmt = None

INCIDENTS_TABLE = os.environ["INCIDENTS_TABLE"]
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
ARIA_BUCKET = os.environ.get("ARIA_BUCKET", "")
REPORTS_PREFIX = "reports"
WS_ENDPOINT = os.environ.get("WS_ENDPOINT", "")

REPORT_MODEL_ID = os.environ.get(
    "REPORT_MODEL_ID",
    "us.anthropic.claude-sonnet-4-20250514-v1:0",
)


@logger.inject_lambda_context
def lambda_handler(event, context):
    # Bedrock Agent action group invocation
    if event.get("messageVersion") == "1.0" and "actionGroup" in event:
        return _handle_agent_action(event)

    t0 = int(time.time() * 1000)
    incident_id = event.get("incident_id", "")
    action = event.get("action", "generate_report")

    if action == "start_logging":
        # Called at incident start — just create initial log entry
        return {"status": "logging_started", "incident_id": incident_id}

    if not incident_id:
        return {"status": "skipped"}

    logger.info("Generating after-action report", extra={"incident_id": incident_id})

    incident = _load_full_incident(incident_id)
    report = _generate_report(incident)

    report_key = f"reports/{incident_id}/report.json"
    md_key = f"reports/{incident_id}/report.md"

    _write_to_s3(report_key, json.dumps(report, indent=2, default=str))
    _write_to_s3(md_key, _render_markdown(report, incident))
    _index_report(incident_id, report_key, md_key)

    elapsed_ms = int(time.time() * 1000) - t0
    metrics.add_metric("report_complete_ms", unit=MetricUnit.Milliseconds, value=elapsed_ms)

    report_url = f"s3://{ARIA_BUCKET}/{report_key}" if ARIA_BUCKET else ""
    _push_to_dashboard(incident_id, {
        "type": "report_generated",
        "report_url": report_url,
        "incident_id": incident_id,
    })

    return {"status": "ok", "incident_id": incident_id, "report_url": report_url, "elapsed_ms": elapsed_ms}


def _handle_agent_action(event: dict) -> dict:
    """Handle Bedrock Agent action group invocation (generate_after_action_report function)."""
    params = {p["name"]: p["value"] for p in event.get("parameters", [])}
    incident_id = params.get("incident_id", "")

    logger.info("Report agent action invoked", extra={"incident_id": incident_id})

    incident = _load_full_incident(incident_id)
    report = _generate_report(incident)
    report_key = f"reports/{incident_id}/report.json"
    md_key = f"reports/{incident_id}/report.md"
    _write_to_s3(report_key, json.dumps(report, indent=2, default=str))
    _write_to_s3(md_key, _render_markdown(report, incident))
    _index_report(incident_id, report_key, md_key)

    report_url = f"s3://{ARIA_BUCKET}/{report_key}" if ARIA_BUCKET else ""
    _push_to_dashboard(incident_id, {"type": "report_generated", "report_url": report_url, "incident_id": incident_id})

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup"),
            "function": event.get("function"),
            "functionResponse": {
                "responseBody": {
                    "TEXT": {"body": json.dumps({"status": "ok", "incident_id": incident_id, "report_url": report_url}, default=str)}
                }
            },
        },
    }


def _load_full_incident(incident_id: str) -> dict:
    table = dynamodb.Table(INCIDENTS_TABLE)
    resp = table.query(
        KeyConditionExpression="incident_id = :id",
        ExpressionAttributeValues={":id": incident_id},
        ScanIndexForward=True,
    )
    items = resp.get("Items", [])
    if not items:
        return {"incident_id": incident_id, "error": "not_found"}
    latest = max(items, key=lambda x: x.get("timestamp", "0"))
    return latest


def _generate_report(incident: dict) -> dict:
    return {
        "incident_id": incident.get("incident_id"),
        "report_generated_at": int(time.time()),
        "incident_type": incident.get("incident_type", "unknown"),
        "severity": incident.get("severity", "unknown"),
        "timeline": {
            "call_start_ms": incident.get("t0_ms"),
            "navigation_result_ms": incident.get("navigation_at_ms"),
            "medical_result_ms": incident.get("medical_at_ms"),
            "recommendation_card_ms": incident.get("recommendation_ready_at_ms"),
            "dispatcher_approved_ms": incident.get("approved_at_ms"),
        },
        "recommendation_card": incident.get("recommendation_card"),
        "navigation_result": incident.get("navigation_result"),
        "medical_result": incident.get("medical_result"),
        "hazmat_result": incident.get("hazmat_result"),
        "dispatcher_approved": incident.get("dispatcher_approved", False),
        "overrides": [],  # Populated from aria-overrides table in full impl
        "total_response_time_ms": _calc_response_time(incident),
    }


def _calc_response_time(incident: dict) -> int:
    t0 = incident.get("t0_ms", 0)
    approved = incident.get("approved_at_ms", 0)
    if t0 and approved:
        return approved - t0
    return 0


def _render_markdown(report: dict, incident: dict) -> str:
    """Call Claude Sonnet to write an AI-authored after-action report narrative."""
    incident_summary = json.dumps({
        "incident_id": incident.get("incident_id"),
        "incident_type": incident.get("incident_type", "unknown"),
        "severity": incident.get("severity", "unknown"),
        "transcript_excerpt": incident.get("recommendation_card", {}).get("summary", ""),
        "dispatcher_action_taken": incident.get("recommendation_card", {}).get("dispatcher_action"),
        "ai_reasoning": incident.get("recommendation_card", {}).get("reasoning_summary"),
        "recommendation_card": incident.get("recommendation_card"),
        "navigation_result": incident.get("navigation_result"),
        "medical_result": incident.get("medical_result"),
        "hazmat_result": incident.get("hazmat_result"),
        "verifier_classification": incident.get("verifier_classification"),
        "dispatcher_approved": incident.get("dispatcher_approved", False),
        "total_response_time_ms": report.get("total_response_time_ms", 0),
        "timeline": report.get("timeline"),
    }, default=str)

    prompt = (
        "You are ARIA, an AI emergency dispatch system. Write a professional, factual after-action report "
        "for the following 911 incident in markdown format. Include: an executive summary, a chronological "
        "timeline of AI agent actions, the recommendation that was surfaced to the dispatcher, "
        "dispatcher decision, and one key lesson or observation. Use professional emergency services language.\n\n"
        f"INCIDENT DATA:\n{incident_summary}\n\n"
        "Write the full markdown report now. Use ## headers, bullet points, and a clean structure."
    )

    try:
        resp = bedrock_runtime.invoke_model(
            modelId=REPORT_MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2048,
                "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}],
            }),
            contentType="application/json",
            accept="application/json",
        )
        raw = json.loads(resp["body"].read())
        return raw["content"][0]["text"].strip()
    except Exception as e:
        logger.error("Sonnet report generation failed — using fallback template", exc_info=e)
        return _render_markdown_fallback(report)


def _render_markdown_fallback(report: dict) -> str:
    iid = report.get("incident_id", "UNKNOWN")
    itype = report.get("incident_type", "unknown")
    severity = report.get("severity", "unknown")
    approved = "Yes" if report.get("dispatcher_approved") else "No"
    rt = report.get("total_response_time_ms", 0)
    rt_s = round(rt / 1000, 1) if rt else "N/A"

    return f"""# ARIA After-Action Report
**Incident ID:** {iid}
**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S UTC')}

## Incident Summary
- **Type:** {itype}
- **Severity:** {severity}
- **Dispatcher Approved:** {approved}
- **Total Response Time:** {rt_s}s

## Recommendation Card
```json
{json.dumps(report.get('recommendation_card', {}), indent=2, default=str)}
```

## Agent Performance
- Navigation: {report['timeline'].get('navigation_result_ms', 'N/A')}ms
- Medical: {report['timeline'].get('medical_result_ms', 'N/A')}ms
- Full Card: {report['timeline'].get('recommendation_card_ms', 'N/A')}ms
"""


def _write_to_s3(key: str, content: str) -> None:
    if not ARIA_BUCKET:
        return
    s3.put_object(
        Bucket=ARIA_BUCKET,
        Key=key,
        Body=content.encode(),
        ContentType="application/json" if key.endswith(".json") else "text/markdown",
    )


def _index_report(incident_id: str, json_key: str, md_key: str) -> None:
    table = dynamodb.Table(INCIDENTS_TABLE)
    table.update_item(
        Key={"incident_id": incident_id, "timestamp": "latest"},
        UpdateExpression="SET report_s3_key = :k, report_md_key = :m, report_generated = :t",
        ExpressionAttributeValues={
            ":k": json_key,
            ":m": md_key,
            ":t": int(time.time()),
        },
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
