"""
aria-stream-processor — the real-time spine of ARIA.

Receives one stabilized word event at a time from aria-ingest.
Runs all domain watchers in-process (pure Python, zero network).
Fires specialist agents asynchronously on first watcher trigger.
Pushes every word to the dashboard WebSocket immediately.
"""
import json
import os
import re
import time
import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
metrics = Metrics()

# Module-level clients — connection reuse across warm invocations
lambda_client = boto3.client("lambda", region_name=os.environ["AWS_DEPLOY_REGION"])
dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_DEPLOY_REGION"])
apigw_mgmt = None  # Initialized lazily with the WS endpoint

INCIDENTS_TABLE = os.environ["INCIDENTS_TABLE"]
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
COORDINATOR_FUNCTION = os.environ.get("COORDINATOR_FUNCTION", "aria-coordinator")
NAVIGATION_FUNCTION = os.environ.get("NAVIGATION_FUNCTION", "aria-navigation-tool")
MEDICAL_FUNCTION = os.environ.get("MEDICAL_FUNCTION", "aria-medical-tool")
HAZMAT_FUNCTION = os.environ.get("HAZMAT_FUNCTION", "aria-hazmat-tool")
WS_ENDPOINT = os.environ.get("WS_ENDPOINT", "")

# ─── Domain Watcher Patterns ─────────────────────────────────────────────────

LOCATION_PATTERNS = [
    re.compile(r'\b\d+\s+\w+\s+(Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr|Lane|Ln)\b', re.I),
    re.compile(r'\b(corner|intersection)\s+of\b', re.I),
    re.compile(r'\b\d{5}\b'),
    re.compile(r'\b(north|south|east|west)\b.*\b(street|avenue|road|drive)\b', re.I),
]

MEDICAL_KEYWORDS = frozenset({
    "not breathing", "chest pain", "unconscious", "heart attack",
    "bleeding", "overdose", "seizure", "choking", "collapsed",
    "unresponsive", "cardiac arrest", "stroke", "not responding",
    "passed out", "can't breathe", "difficulty breathing",
})

FIRE_KEYWORDS = frozenset({
    "fire", "smoke", "burning", "explosion", "flames", "gas leak",
    "on fire", "house fire", "building fire", "structure fire",
})

HAZMAT_KEYWORDS = frozenset({
    "chemical", "fumes", "spill", "toxic", "chlorine", "ammonia",
    "carbon monoxide", "hazmat", "leak", "acid", "biohazard",
})

CRIME_KEYWORDS = frozenset({
    "gun", "shot", "stabbed", "robbery", "weapon", "knife",
    "shooting", "armed", "gunshot", "assault", "attack",
})

SEVERITY_KEYWORDS = frozenset({
    "not moving", "multiple people", "mass casualty", "many victims",
    "several people", "crowd", "dozens",
})

# In-memory context buffer per Lambda execution context (warm invocations reuse this)
_context_buffer: dict[str, str] = {}
_watcher_fired: dict[str, set] = {}  # incident_id → set of fired watcher names
_word_count: dict[str, int] = {}


@logger.inject_lambda_context
def lambda_handler(event, context):
    incident_id = event.get("incident_id", "")
    word = event.get("word", "")
    speaker = event.get("speaker_label", "caller")
    timestamp_ms = event.get("timestamp_ms", int(time.time() * 1000))

    if not incident_id or not word:
        return {"status": "skipped"}

    # Step 1 — Append to context buffer
    _context_buffer.setdefault(incident_id, "")
    _context_buffer[incident_id] += f" {word}"
    _word_count[incident_id] = _word_count.get(incident_id, 0) + 1
    context_so_far = _context_buffer[incident_id].strip()

    # Async checkpoint write every 10 words (non-blocking)
    if _word_count[incident_id] % 10 == 0:
        _checkpoint_context(incident_id, context_so_far, timestamp_ms)

    # Step 2 — Push word to dashboard WebSocket
    _push_to_dashboard(incident_id, {
        "type": "transcript_word",
        "word": word,
        "speaker": speaker,
        "timestamp_ms": timestamp_ms,
        "transcript_so_far": context_so_far,
    })

    # Step 3 — Run domain watchers in-process
    fired = _watcher_fired.setdefault(incident_id, set())
    context_lower = context_so_far.lower()

    if "location" not in fired and _check_location(context_lower):
        fired.add("location")
        logger.info("LocationWatcher fired", extra={"incident_id": incident_id})
        metrics.add_metric("watcher_location_fired_ms", unit=MetricUnit.Milliseconds, value=timestamp_ms)
        _fire_agent(NAVIGATION_FUNCTION, incident_id, context_so_far, "location_detected", timestamp_ms)

    if "medical" not in fired and _check_keywords(context_lower, MEDICAL_KEYWORDS):
        fired.add("medical")
        logger.info("MedicalWatcher fired", extra={"incident_id": incident_id})
        metrics.add_metric("watcher_medical_fired_ms", unit=MetricUnit.Milliseconds, value=timestamp_ms)
        _fire_agent(MEDICAL_FUNCTION, incident_id, context_so_far, "medical_keyword_detected", timestamp_ms)

    if "fire" not in fired and _check_keywords(context_lower, FIRE_KEYWORDS):
        fired.add("fire")
        logger.info("FireWatcher fired", extra={"incident_id": incident_id})
        _fire_agent(HAZMAT_FUNCTION, incident_id, context_so_far, "fire_keyword_detected", timestamp_ms)

    if "hazmat" not in fired and _check_keywords(context_lower, HAZMAT_KEYWORDS):
        fired.add("hazmat")
        logger.info("HazmatWatcher fired", extra={"incident_id": incident_id})
        _fire_agent(HAZMAT_FUNCTION, incident_id, context_so_far, "hazmat_keyword_detected", timestamp_ms)

    if "crime" not in fired and _check_keywords(context_lower, CRIME_KEYWORDS):
        fired.add("crime")
        logger.info("CrimeWatcher fired", extra={"incident_id": incident_id})
        _fire_agent(NAVIGATION_FUNCTION, incident_id, context_so_far, "crime_keyword_detected", timestamp_ms)

    return {"status": "ok", "word": word, "watchers_fired": list(fired)}


def _check_location(text: str) -> bool:
    return any(p.search(text) for p in LOCATION_PATTERNS)


def _check_keywords(text: str, keyword_set: frozenset) -> bool:
    return any(kw in text for kw in keyword_set)


def _fire_agent(function_name: str, incident_id: str, context: str, trigger_reason: str, ts: int) -> None:
    """Async invoke — stream processor returns immediately, agent runs in parallel."""
    payload = {
        "incident_id": incident_id,
        "context_so_far": context,
        "trigger_reason": trigger_reason,
        "triggered_at_ms": ts,
        "source": "stream_processor",
    }
    try:
        lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="Event",  # async — fire and forget
            Payload=json.dumps(payload).encode(),
        )
    except Exception as e:
        logger.error(f"Failed to fire agent {function_name}", exc_info=e)


def _checkpoint_context(incident_id: str, context: str, ts: int) -> None:
    """Async DynamoDB write to persist context in case Lambda recycles."""
    payload = {
        "incident_id": incident_id,
        "context": context,
        "checkpoint_at_ms": ts,
        "action": "checkpoint",
    }
    try:
        lambda_client.invoke(
            FunctionName=os.environ.get("STREAM_PROCESSOR_FUNCTION", "aria-stream-processor"),
            InvocationType="Event",
            Payload=json.dumps(payload).encode(),
        )
    except Exception:
        pass  # Checkpoint failure is non-fatal — context is still in memory


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
        except apigw_mgmt.exceptions.GoneException:
            conn_table.delete_item(Key={"connection_id": conn["connection_id"]})
        except Exception as e:
            logger.warning("Failed to push to connection", exc_info=e)
