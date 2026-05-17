import json
import os
import uuid
import time
import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
metrics = Metrics()

# Module-level client init — reused across warm invocations
dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_DEPLOY_REGION"])
lambda_client = boto3.client("lambda", region_name=os.environ["AWS_DEPLOY_REGION"])
transcribe_client = boto3.client("transcribe-streaming", region_name=os.environ["AWS_DEPLOY_REGION"])

INCIDENTS_TABLE = os.environ["INCIDENTS_TABLE"]
STREAM_PROCESSOR_FUNCTION = os.environ["STREAM_PROCESSOR_FUNCTION"]


@logger.inject_lambda_context
def lambda_handler(event, context):
    http_method = event.get("httpMethod", "GET")
    path = event.get("path", "")

    if http_method == "POST" and path.endswith("/start"):
        return _start_session(event)
    elif http_method == "GET":
        return _get_status(event)
    return _respond(400, {"error": "Unknown route"})


def _start_session(event: dict) -> dict:
    body = json.loads(event.get("body") or "{}")
    audio_file_key = body.get("audio_file_key", "")
    incident_id = str(uuid.uuid4())
    t0_ms = int(time.time() * 1000)

    table = dynamodb.Table(INCIDENTS_TABLE)
    table.put_item(Item={
        "incident_id": incident_id,
        "timestamp": str(t0_ms),
        "status": "ingesting",
        "audio_file_key": audio_file_key,
        "t0_ms": t0_ms,
        "ttl": int(time.time()) + (30 * 24 * 3600),  # 30-day TTL
    })

    logger.info("Session started", extra={"incident_id": incident_id})

    ws_url = os.environ.get("WS_ENDPOINT", "").replace("https://", "wss://")
    return _respond(200, {
        "incident_id": incident_id,
        "websocket_url": ws_url,
        "status": "ingesting",
    })


def _get_status(event: dict) -> dict:
    path_params = event.get("pathParameters") or {}
    incident_id = path_params.get("id", "")
    if not incident_id:
        return _respond(400, {"error": "incident_id required"})

    table = dynamodb.Table(INCIDENTS_TABLE)
    result = table.query(
        KeyConditionExpression="incident_id = :id",
        ExpressionAttributeValues={":id": incident_id},
        ScanIndexForward=False,
        Limit=1,
    )
    items = result.get("Items", [])
    if not items:
        return _respond(404, {"error": "Incident not found"})
    return _respond(200, items[0])


def _respond(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
